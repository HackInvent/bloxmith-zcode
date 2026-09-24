"""Hermetic Zcode CLI and context fixtures; no credentials or developer paths."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from bloxsmith_app.block_api import BlockRuntimeContext


@contextmanager
def fake_zcode():
    """Implement the documented final JSON protocol without calling a model."""
    with TemporaryDirectory(prefix="zcode-block-test-") as name:
        directory = Path(name)
        executable = directory / "zcode"
        executable.write_text('''#!/usr/bin/env python3
import json, os, sys, time, uuid
from pathlib import Path
args = sys.argv[1:]
allowed_flags = {"--json", "--no-color", "--mode", "--resume", "--prompt"}
assert not any(a.startswith("--") and a not in allowed_flags for a in args)
value = lambda flag, default="": args[args.index(flag) + 1] if flag in args else default
prompt = value("--prompt")
directory = Path(os.environ["TEST_ZCODE_DIR"])
identifier = value("--resume") or "sess_" + uuid.uuid4().hex
record = {"argv": args, "prompt": prompt, "cwd": os.getcwd(), "pid": os.getpid(), "session_id": identifier}
with (directory / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(record) + "\\n")
mode = os.environ.get("TEST_ZCODE_MODE", "ok")
if mode == "sleep": time.sleep(30)
if mode == "exit":
    print("private-provider-credential fake failure", file=sys.stderr)
    sys.exit(3)
if mode == "bad-json": print("not json"); sys.exit(0)
if mode == "oversize": print("x" * (5 * 1024 * 1024)); sys.exit(0)
history = directory / (identifier + ".session")
if "--resume" in args and not history.exists():
    print("No conversation found for this session. Start a new session.", file=sys.stderr)
    sys.exit(1)
turn = int(history.read_text()) + 1 if history.exists() else 1
history.write_text(str(turn))
result = {"sessionId": identifier, "response": "fake zcode response",
          "projection": {"status": "error" if mode == "error-result" else "idle"},
          "usage": {"inputTokens": 7, "outputTokens": 3}}
if mode == "invalid-id": result["sessionId"] = "not-a-session"
if mode == "mismatch-id": result["sessionId"] = "sess_" + uuid.uuid4().hex
if mode == "empty-result": result["response"] = ""
if mode == "array": result = [result]
if mode == "missing-model":
    print("Model config is missing", file=sys.stderr); sys.exit(1)
print(json.dumps(result))
''', encoding="utf-8")
        executable.chmod(0o700)
        with patch.dict(os.environ, {"PATH": str(directory) + os.pathsep + os.environ.get("PATH", ""),
                                     "TEST_ZCODE_DIR": str(directory), "TEST_ZCODE_MODE": "ok"}):
            yield directory


def calls(directory):
    """Read only the test executable's captured invocations."""
    path = directory / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def context(directory, *, config=None, inputs=None, input_ports=None, output_ports=None, storage=None, services=None):
    """Build a portable public runtime context, optionally bound to test storage."""
    bound = dict(services or {})
    if storage:
        storage.mkdir(exist_ok=True)
        bound["get_block_storage_dir"] = lambda: storage
    return BlockRuntimeContext(run_id="test-run", node_id="zcode-test", kind="zcode", root_dir=directory,
        config={"working_directory": str(directory), "timeout_sec": 5, "use_persistent_session": bool(storage), **(config or {})},
        inputs=inputs if inputs is not None else {1: "hello"}, input_ports=tuple(input_ports or [SimpleNamespace(id=1, name="in")]),
        output_ports=tuple(output_ports or [SimpleNamespace(id=1, name="out", instruction="Return a concise answer.")]), services=bound)


def node(*, version="0.1.0", persistent=False):
    """Use the existing technical kind and declared version for managed installs."""
    from blocs.zcode.block import ZcodeBlock
    result = ZcodeBlock().build_node_payload(node_id="zcode-test", position={"x": 340, "y": 160})
    result["block_version"] = version
    result["config"].update(use_persistent_session=persistent, timeout_sec=8)
    result["outputs"][0]["instruction"] = "Return a concise answer."
    return result
