"""Resolve the official Zcode CLI or its desktop-bundled Node engine."""

import os
from pathlib import Path
import shutil

from .session_state import ZcodeError


def executable(value):
    """Resolve an explicit path or PATH command without a shell or arguments."""
    path = shutil.which(str(Path(value).expanduser()))
    if not path:
        raise ZcodeError("Zcode executable could not be found. Check the executable/runtime settings.")
    return Path(path).resolve()


def resolve_launch(config):
    """Detect desktop files without opening its GUI; return argv, env, stdin mode.

    An explicit engine uses node_binary (or node from PATH). Desktop discovery
    uses Electron's built-in Node, so it does not require a recent system Node.
    """
    env = dict(os.environ)
    script = str(config.get("engine_script") or "")
    if script:
        engine = Path(script).expanduser().resolve()
        if not engine.is_file() or engine.suffix not in {".cjs", ".js"}:
            raise ZcodeError("The Zcode engine script must be an existing .cjs or .js file.")
        node = executable(config.get("node_binary") or "node")
    else:
        binary = executable(config["zcode_binary"])
        candidates = [binary.parent / "resources" / "glm" / "zcode.cjs",
                      binary.parent.parent / "Resources" / "glm" / "zcode.cjs"]
        engine = next((p for p in candidates if p.is_file()), None)
        if engine is None:
            if any((p / "app.asar").exists() for p in
                   (binary.parent / "resources", binary.parent.parent / "Resources")):
                raise ZcodeError("Zcode Desktop engine was not found. Set engine_script after checking the installation.")
            if config.get("node_binary"):
                raise ZcodeError("node_binary requires an engine_script or a detected desktop engine.")
            return [str(binary)], env, False
        node = executable(config["node_binary"]) if config.get("node_binary") else binary
        if node == binary:
            env["ELECTRON_RUN_AS_NODE"] = "1"
    if any((p / "app.asar").exists() for p in
           (node.parent / "resources", node.parent.parent / "Resources")):
        env["ELECTRON_RUN_AS_NODE"] = "1"
    return [str(node), str(Path(__file__).with_name("engine_runner.cjs")), str(engine)], env, True
