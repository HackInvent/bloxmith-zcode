#!/usr/bin/env python3
"""Opt-in real Zcode engine check with a local fake provider, never a paid model.

Usage: python3 tests/probe_installed_engine.py --engine PATH --node EXECUTABLE
Add --electron when EXECUTABLE is the Zcode desktop binary. This is separate from
the hermetic framework suites and never changes the user's Zcode configuration.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading


def main():
    """Verify final JSON and resumption against the actually installed engine."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--electron", action="store_true")
    args = parser.parse_args()
    requests = []

    class Provider(BaseHTTPRequestHandler):
        """Implement only a local OpenAI-compatible completion fixture."""

        def log_message(self, *_args):
            """Keep prompts and headers out of probe logs."""

        def do_POST(self):
            """Return a final answer or equivalent SSE without tool execution."""
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            choice = {"index": 0, "finish_reason": "stop"}
            result = {"id": "fixture-response", "object": "chat.completion", "created": 1,
                      "model": "fixture-model", "choices": [{**choice, "message": {"role": "assistant", "content": "READY"}}],
                      "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}}
            if body.get("stream"):
                result.update(object="chat.completion.chunk", choices=[{**choice, "delta": {"role": "assistant", "content": "READY"}}])
                payload = ("data: " + json.dumps(result) + "\n\ndata: [DONE]\n\n").encode()
                content_type = "text/event-stream"
            else:
                payload = json.dumps(result).encode()
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TemporaryDirectory(prefix="zcode-protocol-probe-") as name:
            directory = Path(name)
            configuration = {
                "provider": {"fixture": {"kind": "openai-compatible", "options": {
                    "baseURL": f"http://127.0.0.1:{server.server_port}/v1", "apiKey": "fixture-only"},
                    "models": {"fixture-model": {"contextWindow": 128000, "maxOutputTokens": 1000}}}},
                "model": {"main": "fixture/fixture-model", "lite": "fixture/fixture-model"},
                "storage": {"dir": str(directory / "storage"), "sessionDbPath": str(directory / "sessions.sqlite")},
                "features": {"mcp": False, "memory": False, "subagent": False, "skill": False},
                "hooks": {"enabled": False}, "logging": {"level": "error"},
            }
            (directory / "zcode.json").write_text(json.dumps(configuration))
            env = {**os.environ, "ZCODE_STORAGE_DIR": str(directory / "storage"),
                   "ZCODE_LOG_DIR": str(directory / "logs"), "ZCODE_MODEL_TELEMETRY_ENABLED": "false"}
            if args.electron:
                env["ELECTRON_RUN_AS_NODE"] = "1"
            block = Path(__file__).resolve().parents[1]
            identifier = None
            for prompt in ("Remember probe-marker-42. Reply READY without tools.", "Reply READY without tools."):
                call = [args.node, str(block / "engine_runner.cjs"), str(args.engine.resolve()),
                        "--json", "--no-color", "--mode", "plan"]
                if identifier:
                    call += ["--resume", identifier]
                read_fd, write_fd = os.pipe()
                child = subprocess.Popen([sys.executable, "-I", str(block / "cli_guard.py"), str(read_fd), *call],
                    cwd=directory, env=env, pass_fds=(read_fd,), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                os.close(read_fd)
                try:
                    stdout, stderr = child.communicate(json.dumps({"prompt": prompt}).encode(), timeout=35)
                    if child.returncode:
                        # Only fixture invocations run here; never print headers or prompts.
                        raise AssertionError(f"Local fixture engine exited {child.returncode}: {stderr.decode()[-1500:]}")
                    result = json.loads(stdout)
                    assert result["response"] == "READY" and result["projection"]["status"] == "idle", result.keys()
                    assert result["sessionId"].startswith("sess_")
                    if identifier:
                        assert identifier == result["sessionId"]
                    identifier = result["sessionId"]
                finally:
                    os.close(write_fd)
                    child.wait(timeout=5)
            assert len(requests) >= 2
            assert any("probe-marker-42" in json.dumps(r.get("messages")) for r in requests[1:])
            print("[ok] Real Zcode engine: final JSON, same session resumed, previous context forwarded; local provider only.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
