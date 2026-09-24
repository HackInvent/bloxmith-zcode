#!/usr/bin/env python3
"""Zcode runtime: sessions, prompts, launchers, cancellation and both engines."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from types import SimpleNamespace as Port
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from blocs.zcode.block import ZcodeBlock
from blocs.zcode.runtime import build_prompt
from blocs.zcode.launcher import resolve_launch
from zcode_fixtures import fake_zcode, calls, context, node
from block_test_packages import install_test_package
from ui_smoke_common import (isolated_server, graph_payload, text_node, display_node, data_edge,
    create_project_api, create_run_api, wait_for_run_predicate, stop_run_api, get_run_api, prepare_run_api, play_run_api)


def successful(block, ctx):
    """Assert failures with useful diagnostics, never silently accept empty output."""
    result = block.execute_runtime(ctx)
    assert result.status == "success", (result.error, result.logs)
    assert result.outputs and result.outputs[0].value == "fake zcode response"
    return result


def test_prompts_and_configuration():
    """Named inputs preserve types; IDs survive reordering and instruction overrides."""
    block = ZcodeBlock()
    with fake_zcode() as directory:
        ctx = context(directory, inputs={7: {"count": 0}, 3: False, 9: "dynamic instruction"},
            config={"instruction_inputs": {"1": "9"}},
            input_ports=[Port(id=9, name="instruction"), Port(id=3, name="flag"), Port(id=7, name="data")])
        result = successful(block, ctx)
        call = calls(directory)[0]
        assert '"count": 0' in call["prompt"] and "false" in call["prompt"]
        assert "dynamic instruction" in call["prompt"] and "Return a concise" not in call["prompt"]
        assert "[BEGIN INPUT instruction]" not in call["prompt"]
        assert "dynamic instruction" not in json.dumps(result.metadata)
        assert "--json" in call["argv"] and "--prompt" in call["argv"]
        assert call["argv"][call["argv"].index("--mode")+1] == "build"
        assert "--resume" not in call["argv"]
        ctx.config["max_prompt_chars"] = 8
        assert block.execute_runtime(ctx).status == "failed"
        assert len(calls(directory)) == 1
        for bad in ({"model": "--injected"}, {"effort": "invalid"}, {"permission_mode": "yolo"}, {"mcp_refs": "bad"}):
            assert block.execute_runtime(context(directory, config=bad)).status == "failed"
        assert len(calls(directory)) == 1
        successful(block, context(directory, config={"dangerously_allow_all": True}))
        assert calls(directory)[-1]["argv"][calls(directory)[-1]["argv"].index("--mode")+1] == "yolo"


def test_launchers_and_limits():
    """Detect desktop engines without a GUI; bridge stdin using a real Node process."""
    with fake_zcode() as directory:
        block = ZcodeBlock()
        engine = directory / "engine.cjs"
        engine.write_text('''const fs = require('node:fs');
const prompt = process.argv[process.argv.indexOf('--prompt') + 1];
if (!prompt.includes('private-marker-42')) process.exit(4);
if (fs.readFileSync('/proc/self/cmdline', 'utf8').includes('private-marker-42')) process.exit(5);
console.log(JSON.stringify({sessionId:'sess_engine42', response:'fake zcode response', projection:{status:'idle'}}));
''')
        successful(block, context(directory, inputs={1: "private-marker-42"},
            config={"engine_script": str(engine), "node_binary": shutil.which("node")}))
        # Automatic desktop detection must use its bundled Node, even on a host
        # whose system Node cannot load node:sqlite. No desktop process is launched.
        desktop = directory / "Desktop"
        script = desktop / "resources" / "glm" / "zcode.cjs"
        script.parent.mkdir(parents=True)
        script.write_text("// fixture")
        binary = desktop / "zcode"
        shutil.copy2(directory / "zcode", binary)
        cfg = {**block.default_config(), "zcode_binary": str(binary), "working_directory": str(directory)}
        argv, env, stdin = resolve_launch(cfg)
        assert stdin and argv[0] == str(binary) and argv[-1] == str(script)
        assert env["ELECTRON_RUN_AS_NODE"] == "1"
        script.unlink()  # Remove only this fixture's engine to simulate a broken install.
        (desktop / "resources" / "app.asar").write_text("fixture")
        result = block.execute_runtime(context(directory, config=cfg))
        assert result.status == "failed" and "Desktop engine" in result.error
        for config in ({"engine_script": str(directory / "absent.cjs")}, {"timeout_sec": 0},
                       {"max_prompt_chars": 0}, {"working_directory": str(directory / "absent")},
                       {"session_generation": "x" * 65}, {"instruction_inputs": {"1": "999"}}):
            assert block.execute_runtime(context(directory, config=config)).status == "failed"
        assert block.execute_runtime(context(directory, inputs={1: "é" * 33000})).status == "failed"
        # Persistence cannot guess a storage location for an unscoped run.
        assert block.execute_runtime(context(directory, config={"use_persistent_session": True})).status == "failed"
        other = directory / "work"
        other.mkdir()
        successful(block, context(directory, inputs={1: "hello", 7: str(other)},
            input_ports=[Port(id=1, name="in"), Port(id=7, name="working_directory")],
            config={"working_directory_input_enabled": True}))
        assert calls(directory)[-1]["cwd"] == str(other)
        assert "[BEGIN INPUT working_directory]" not in calls(directory)[-1]["prompt"]


def test_blank_instruction_fallback():
    """An empty override, including whitespace, keeps the saved instruction like Codex."""
    with fake_zcode() as directory:
        for incoming in (None, "", " \n\t "):
            successful(ZcodeBlock(), context(directory, inputs={1: "hello", 9: incoming},
                input_ports=[Port(id=9, name="instruction"), Port(id=1, name="in")],
                config={"instruction_inputs": {"1": "9"}}))
            assert "Return a concise answer." in calls(directory)[-1]["prompt"]
            assert "[BEGIN INPUT instruction]" not in calls(directory)[-1]["prompt"]


def test_sessions():
    """Same block resumes across runs; disable/reset/copy/cwd changes stay isolated."""
    with fake_zcode() as directory:
        storage = directory / "block-storage"
        state = {}
        services = {"set_node_runtime_value": lambda k, v: state.update({k: v})}
        outputs = [Port(id=2, name="second", instruction="Second"), Port(id=1, name="first", instruction="First")]
        ctx = context(directory, storage=storage, output_ports=outputs, services=services)
        successful(ZcodeBlock(), ctx)
        first, second = calls(directory)
        assert first["session_id"] == second["session_id"] and "--resume" in second["argv"]
        assert state["zcode_session_id"] == first["session_id"]
        successful(ZcodeBlock(), context(directory, storage=storage))
        assert calls(directory)[-1]["session_id"] == first["session_id"]
        initialized = ZcodeBlock().initialize_runtime(context(directory, storage=storage, services=services))
        assert initialized.status == "success" and not initialized.outputs
        assert state["zcode_session_id"] == first["session_id"]
        record = storage / "zcode_session.json"
        assert record.stat().st_mode & 0o777 == 0o600
        assert "prompt" not in record.read_text()
        copied = directory / "copied-block"
        shutil.copytree(storage, copied)
        successful(ZcodeBlock(), context(directory, storage=copied))
        assert calls(directory)[-1]["session_id"] != first["session_id"]
        initialized = ZcodeBlock().initialize_runtime(context(directory, storage=storage, services=services, config={"use_persistent_session": False}))
        assert initialized.status == "success" and state["zcode_session_id"] == ""
        assert json.loads(record.read_text())["session_id"] == ""
        successful(ZcodeBlock(), context(directory, storage=storage, config={"use_persistent_session": False}))
        assert json.loads(record.read_text())["session_id"] == ""
        assert "--resume" not in calls(directory)[-1]["argv"]
        successful(ZcodeBlock(), context(directory, storage=storage))
        third_id = calls(directory)[-1]["session_id"]
        assert third_id != first["session_id"]
        successful(ZcodeBlock(), context(directory, storage=storage, config={"session_generation": "reset-1"}))
        reset_id = calls(directory)[-1]["session_id"]
        assert reset_id != third_id
        other = directory / "work"
        other.mkdir()
        successful(ZcodeBlock(), context(directory, storage=storage, config={"working_directory": str(other), "session_generation": "reset-1"}))
        assert calls(directory)[-1]["session_id"] != reset_id
        # An invalid association must not silently disappear or launch another call.
        count = len(calls(directory))
        record.write_text("broken")
        assert ZcodeBlock().execute_runtime(context(directory, storage=storage)).status == "failed"
        assert len(calls(directory)) == count


def test_session_rendering():
    """Fresh result metadata wins over stale initialization, including empty IDs."""
    block = ZcodeBlock()
    for result in ({"zcode_session_id": "sess_fresh", "runtime_state": {"zcode_session_id": ""}},
                   {"metadata": {"zcode_session_id": "sess_fresh"}, "runtime_state": {"zcode_session_id": ""}}):
        assert 'sess_fresh' in block.render_modal(node=node(), payload={"runtime": {"result": result}})["html"]
    result = {"zcode_session_id": "", "runtime_state": {"zcode_session_id": "sess_stale"}}
    assert 'sess_stale' not in block.render_modal(node=node(), payload={"runtime": {"result": result}})["html"]


def test_concurrency():
    """Two hook instances serialize their shared persistent session."""
    with fake_zcode() as directory, ThreadPoolExecutor(max_workers=2) as pool:
        storage = directory / "storage"
        contexts = [context(directory, storage=storage) for _ in range(2)]
        results = list(pool.map(lambda c: ZcodeBlock().execute_runtime(c), contexts))
        assert all(r.status == "success" for r in results), results
        invocations = calls(directory)
        assert len(invocations) == 2 and invocations[0]["session_id"] == invocations[1]["session_id"]
        assert "--resume" not in invocations[0]["argv"] and "--resume" in invocations[1]["argv"]


def test_failures():
    """Failures and incomplete results emit nothing; timeouts stop the CLI."""
    block = ZcodeBlock()
    with fake_zcode() as directory:
        for mode in ("exit", "bad-json", "error-result", "oversize", "empty-result", "invalid-id", "array", "missing-model"):
            with patch.dict(os.environ, {"TEST_ZCODE_MODE": mode}):
                result = block.execute_runtime(context(directory))
                assert result.status == "failed" and not result.outputs, (mode, result)
                assert "private-provider-credential" not in repr(result)
        with patch.dict(os.environ, {"TEST_ZCODE_MODE": "sleep"}):
            result = block.execute_runtime(context(directory, config={"timeout_sec": 1}))
            assert result.status == "failed" and "timed out" in result.error
            assert_process_stopped(calls(directory)[-1]["pid"])
        result = block.execute_runtime(context(directory, config={"zcode_binary": str(directory / "missing-executable")}))
        assert result.status == "failed" and not result.outputs


def assert_process_stopped(pid, timeout=2):
    """Linux process state is read-only; zombies are not running CLI work."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        stat = Path(f"/proc/{pid}/stat")
        if not stat.exists() or stat.read_text().split(") ", 1)[1].startswith("Z"):
            return
        time.sleep(.02)
    raise AssertionError(f"Fake Zcode process {pid} is still alive")


def test_cancel():
    """Stop terminates this call and never publishes an unfinished answer."""
    with fake_zcode() as directory, patch.dict(os.environ, {"TEST_ZCODE_MODE": "sleep"}):
        cancelled = threading.Event()
        timer = threading.Timer(.4, cancelled.set)
        timer.start()
        try:
            result = ZcodeBlock().execute_runtime(context(directory, services={"cancel_requested": cancelled.is_set}))
            assert result.status == "cancelled" and not result.outputs
            assert_process_stopped(calls(directory)[-1]["pid"])
        finally:
            timer.cancel()


def test_managed_stop():
    """The host's hard Stop must close the guard pipe and stop the fake CLI too."""
    with fake_zcode() as directory, patch.dict(os.environ, {"TEST_ZCODE_MODE": "sleep"}), isolated_server() as server:
        model = install_test_package(server, "zcode")
        consumer = node(version=model["version"])
        consumer["config"]["working_directory"] = str(directory)
        document = graph_payload("Zcode Stop", [text_node("seed", "Seed", "hello", 0, 0), consumer],
                                 [data_edge("in", "seed", 1, "zcode-test", 1)])
        # A real live Run is prepared, then played. /api/runs creates a one-shot
        # execution, not the active session controlled by the editor's Stop.
        created = prepare_run_api(server, document, runtime_mode="zeromq_active")
        play_run_api(server, created["run_id"])
        try:
            deadline = time.monotonic() + 10
            while not calls(directory) and time.monotonic() < deadline:
                time.sleep(.05)
            assert calls(directory), "The fake CLI must start before Stop"
        finally:
            stop_run_api(server, created["run_id"])
        try:
            assert_process_stopped(calls(directory)[-1]["pid"], timeout=5)
        except AssertionError:
            run = get_run_api(server, created["run_id"])
            print(json.dumps({"status": run.get("status"), "logs": run.get("logs", [])[-20:]}), flush=True)
            raise


def test_installed_runtimes():
    """Exercise real managed/linked host RPC, both engines and scoped resume."""
    for origin in ("managed", "linked"):
        with fake_zcode() as directory, isolated_server() as server:
            model = install_test_package(server, "zcode", origin=origin)
            runtime_directory = directory / "runtime-input"
            runtime_directory.mkdir()
            for mode in ("centralized", "zeromq_active"):
                consumer = node(version=model["version"], persistent=True)
                consumer["config"]["working_directory"] = str(directory)
                # Require this source in the fixture so both engines receive it
                # before execution; newly created UI ports remain optional.
                consumer["inputs"].insert(0, {"id": 7, "name": "runtime_directory", "title": "Runtime directory",
                    "accepts": ["config/working-directory", "text/plain", "message/*"], "multiplicity": "many",
                    "required": True, "execution_requirement": "required_for_execution"})
                graph = graph_payload("Zcode package test", [text_node("seed", "Seed", "hello", 0, 0), consumer,
                    text_node("directory", "Directory", str(runtime_directory), 0, 180), display_node("sink", "Sink", 700, 0)],
                    [data_edge("in", "seed", 1, "zcode-test", 1), data_edge("directory", "directory", 1, "zcode-test", 7),
                     data_edge("out", "zcode-test", 1, "sink", 1)])
                project = create_project_api(server, document=graph)["project"]
                previous = None
                for _ in range(2):
                    created = create_run_api(server, graph, project_id=project["project_id"], runtime_mode=mode)
                    try:
                        run = wait_for_run_predicate(server, created["run_id"],
                            lambda r: r.get("node_statuses", {}).get("sink") == "success" or r.get("status") == "failed",
                            "Zcode did not deliver a result", timeout_sec=25)
                        assert run.get("status") != "failed", run.get("logs")
                        assert "fake zcode response" in str(run.get("output_values"))
                        current = calls(directory)[-1]
                        assert current["cwd"] == str(runtime_directory), current
                        assert str(runtime_directory) not in current["prompt"]
                        # The UI must also accept flattened engine metadata.
                        rendered = ZcodeBlock().render_modal(node=consumer, payload={"runtime": {"result": run["results"]["zcode-test"]}})
                        assert current["session_id"] in rendered["html"], run["results"]["zcode-test"]
                        if previous:
                            assert current["session_id"] == previous and "--resume" in current["argv"]
                        previous = current["session_id"]
                    finally:
                        stop_run_api(server, created["run_id"])
                print(f"[ok] Zcode {origin} {mode} persistence", flush=True)


def test_working_directory_contract():
    """Match Codex's dedicated control port, input precedence and pre-launch validation."""
    block = ZcodeBlock()
    authored = node()
    result = block.handle_ui_action(node=authored, action="sync_working_directory_input", values={"enabled": True})
    update, creation = result["graph_operations"]
    assert update["config"] == {"working_directory_input_enabled": True}
    assert creation["name"] == "working_directory" and creation["multiplicity"] == "many"
    assert creation["accepts"] == ["config/working-directory", "text/plain", "message/*"]
    assert creation["execution_requirement"] == "not_required_for_execution"
    control = {k: v for k, v in creation.items() if k not in {"op", "node_id", "direction"}}
    control.update(id=7, name="renamed_directory")
    authored["inputs"].insert(0, control)
    assert block._config(authored)["working_directory_input_enabled"] is True
    repeated = block.handle_ui_action(node=authored, action="sync_working_directory_input", values={"enabled": True})
    assert len(repeated["graph_operations"]) == 1, repeated
    removed = block.handle_ui_action(node=authored, action="sync_working_directory_input", values={"enabled": False})
    assert removed["graph_operations"][-1] == {"op": "delete_port", "node_id": authored["id"], "direction": "input", "port_id": 7, "cascade": True}
    with fake_zcode() as directory:
        target = directory / "input-directory"
        target.mkdir()
        ports = [Port(id=7, name="renamed_directory", accepts=("config/working-directory",)), Port(id=1, name="in")]
        for flag in (True, False):
            successful(block, context(directory, inputs={1: "hello", 7: " input-directory "}, input_ports=ports,
                                      config={"working_directory_input_enabled": flag}))
            assert calls(directory)[-1]["cwd"] == str(target)
            assert "[BEGIN INPUT renamed_directory]" not in calls(directory)[-1]["prompt"]
        for blank in ("", "  ", None):
            successful(block, context(directory, inputs={1: "hello", 7: blank}, input_ports=ports))
            assert calls(directory)[-1]["cwd"] == str(directory)
        legacy = [Port(id=7, name="working_directory", accepts=("directory/path",)), Port(id=1, name="in")]
        successful(block, context(directory, inputs={1: "hello", 7: str(target)}, input_ports=legacy))
        assert calls(directory)[-1]["cwd"] == str(target)
        count = len(calls(directory))
        for incoming in ("", "missing-directory", 123, {"path": str(target)}):
            failed = block.execute_runtime(context(directory, inputs={1: "hello", 7: incoming}, input_ports=ports,
                                                   config={"working_directory": ""}))
            assert failed.status == "failed", failed
        assert len(calls(directory)) == count, "Invalid directories must fail before starting the CLI"
        waiting = block.initialize_runtime(context(directory, input_ports=ports, storage=directory / "pending-session",
                                                  config={"working_directory": "", "working_directory_input_enabled": False}))
        assert waiting.status == "success" and not waiting.outputs


def main():
    for test in (test_prompts_and_configuration, test_working_directory_contract, test_blank_instruction_fallback, test_launchers_and_limits, test_sessions, test_session_rendering, test_concurrency, test_failures, test_cancel, test_managed_stop, test_installed_runtimes):
        test()
        print(f"[ok] {test.__name__}", flush=True)


if __name__ == "__main__":
    main()
