"""Zcode CLI adapter using only the public BloxSmith block contract."""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time

from bloxsmith_app.block_api import BlockRuntimeOutput, BlockRuntimeResult, TEXT_PLAIN
from .session_state import ZcodeError, ZcodeCancelled, SessionFile, check_cancel, session_id
from .launcher import resolve_launch

MAX_ACTIVATION_SECONDS = 240  # Leave cleanup time before the managed hook's 300s limit.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
PERMISSIONS = ("build", "plan", "edit")


def boolean(value):
    """Normalize authored checkbox values without treating 'false' as true."""
    return value is True or value == 1 or str(value).lower() in {"true", "yes", "on"}


def normalize_config(raw, model):
    """Validate authored settings before processes or persistent state are touched."""
    config = {**model.get("config", {}), **(raw or {})}
    for key in ("working_directory_input_enabled", "use_persistent_session", "dangerously_allow_all"):
        config[key] = boolean(config[key])
    for key in ("zcode_binary", "engine_script", "node_binary", "working_directory", "permission_mode", "session_generation"):
        config[key] = str(config.get(key) or "").strip()
        if "\x00" in config[key] or "\n" in config[key]:
            raise ZcodeError(f"Invalid {key}.")
    if not config["zcode_binary"]:
        raise ZcodeError("Zcode executable is required.")
    if config["permission_mode"] not in PERMISSIONS:
        raise ZcodeError("Unknown permission mode. Bypass requires the explicit danger checkbox.")
    for key, default, upper in (("timeout_sec", 240, 240), ("max_prompt_chars", 250000, 1000000)):
        try:
            value = int(config.get(key, default))
        except (ValueError, TypeError) as error:
            raise ZcodeError(f"{key} must be an integer.") from error
        if value < 1:
            raise ZcodeError(f"{key} must be positive.")
        # Stay below the managed host's deadline, including process cleanup.
        config[key] = min(value, upper)
    for unsupported in ("model", "effort", "mcp_refs"):
        if config.get(unsupported):
            raise ZcodeError(f"{unsupported} is configured in Zcode itself, not in this block.")
    mappings = config.get("instruction_inputs", {})
    if not isinstance(mappings, dict) or any(not str(k).isdigit() or not str(v).isdigit() for k, v in mappings.items()):
        raise ZcodeError("Instruction sources must map output IDs to input IDs.")
    config["instruction_inputs"] = {str(k): str(v) for k, v in mappings.items()}
    if len(config["session_generation"]) > 64:
        raise ZcodeError("Invalid session generation.")
    return config


def is_working_directory_port(port):
    """Recognize the native control type or the historical name on graph/runtime ports."""
    read = port.get if isinstance(port, dict) else lambda key, default=None: getattr(port, key, default)
    types = read("accepts") or read("types") or ()
    return (str(read("name", "")).strip().lower() == "working_directory"
            or "config/working-directory" in types)


def directory_input_enabled(config, ports):
    """Like Codex, keep an existing control port active even if its config flag is stale."""
    return boolean(config.get("working_directory_input_enabled")) or any(is_working_directory_port(p) for p in ports)


def working_directory(context, config):
    """Resolve input > explicit config, validate it, and never silently choose a process cwd."""
    value = str(config.get("working_directory") or "").strip()
    if directory_input_enabled(config, context.input_ports):
        for port in context.input_ports:
            if not is_working_directory_port(port):
                continue
            incoming = context.input_value(port.id, port.name, default="")
            if incoming is not None and not isinstance(incoming, str):
                raise ZcodeError("The working_directory input must contain a directory path as text.")
            if incoming and incoming.strip():
                value = incoming.strip()
                break
    if not value:
        raise ZcodeError("Working directory is required. Select a directory or provide it through the working_directory input.")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = context.root_dir / path
    path = path.resolve()
    if not path.is_dir():
        raise ZcodeError("Working directory does not exist or is not a directory.")
    return path


def build_prompt(context, port, config):
    """Preserve stable port IDs, JSON, zero and false values; exclude control data."""
    mapping = config["instruction_inputs"]
    source_id = mapping.get(str(port.id))
    instruction = str(getattr(port, "instruction", "") or "")
    if source_id:
        source = next((p for p in context.input_ports if str(p.id) == source_id), None)
        if source is None:
            raise ZcodeError(f"Instruction input {source_id} is missing for output {port.id}.")
        supplied = context.input_value(source.id, source.name, default="")
        if supplied is not None and supplied != "":
            if not isinstance(supplied, str):
                raise ZcodeError("An instruction input must contain text.")
            if supplied.strip():
                instruction = supplied
    sections = []
    for input_port in context.input_ports:
        if str(input_port.id) in mapping.values() or is_working_directory_port(input_port):
            continue
        value = context.input_value(input_port.id, input_port.name, default=None)
        if value is None or value == "":
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        sections.append(f"[BEGIN INPUT {input_port.name}]\n{text}\n[END INPUT {input_port.name}]")
    if instruction.strip():
        sections.append("Instruction:\n\n" + instruction.strip())
    prompt = "\n\n".join(sections)
    if not prompt:
        raise ZcodeError("Zcode prompt is empty.")
    if len(prompt) > config["max_prompt_chars"]:
        raise ZcodeError(f"Zcode prompt too long: {len(prompt)} characters; limit {config['max_prompt_chars']}.")
    return prompt


def redact(context, value):
    """Apply the public secret redactor before returning text to the workflow."""
    return context.redact_secrets(str(value or ""))


def run_cli(context, args, *, prompt, directory, deadline, env, stdin_prompt):
    """Bound output and tie the CLI process tree to the owning runtime host."""
    guard = Path(__file__).with_name("cli_guard.py")
    read_fd, write_fd = os.pipe()
    process = None
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            if not stdin_prompt and len(prompt.encode()) > 64000:
                raise ZcodeError("Standalone CLI prompts are limited to 64000 UTF-8 bytes. Select an engine_script for larger prompts.")
            call = args if stdin_prompt else args + ["--prompt", prompt]
            process = subprocess.Popen(
                [sys.executable, "-I", str(guard), str(read_fd), *call],
                cwd=directory, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                pass_fds=(read_fd,), env=env)
            os.close(read_fd)
            read_fd = -1
            sent = False
            packet = json.dumps({"prompt": prompt}).encode() if stdin_prompt else b""
            while True:
                check_cancel(context)
                if time.monotonic() >= deadline:
                    raise ZcodeError("Zcode timed out. No partial answer was published.")
                if os.fstat(stdout.fileno()).st_size > MAX_RESPONSE_BYTES or os.fstat(stderr.fileno()).st_size > MAX_RESPONSE_BYTES:
                    raise ZcodeError("Zcode response exceeded the 4 MiB limit.")
                try:
                    process.communicate(input=None if sent else packet, timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    sent = True
            if max(os.fstat(stdout.fileno()).st_size, os.fstat(stderr.fileno()).st_size) > MAX_RESPONSE_BYTES:
                raise ZcodeError("Zcode response exceeded the 4 MiB limit.")
            stdout.seek(0)
            stderr.seek(0)
            return process.returncode, stdout.read(MAX_RESPONSE_BYTES + 1).decode("utf-8", "replace"), stderr.read(MAX_RESPONSE_BYTES).decode("utf-8", "replace")
    finally:
        # Closing the lifetime pipe stops only the guard's private CLI group.
        os.close(write_fd)
        if read_fd >= 0:
            os.close(read_fd)
        if process is not None:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def initialize(context, model):
    """Restore/forget the association at Run, without invoking Zcode or emitting data."""
    try:
        config = normalize_config(context.config, model)
        if not config["use_persistent_session"] and not callable(context.services.get("get_block_storage_dir")):
            return BlockRuntimeResult()
        try:
            state = SessionFile(context)
        except Exception as error:
            if not config["use_persistent_session"] and "block_storage.missing_scope" in str(error):
                return BlockRuntimeResult()
            raise
        with state.locked(context, time.monotonic() + 5):
            record = state.read()
            # At Run, a dynamic input may not have received anything yet. Restore
            # the association now; the execution validates the actual directory.
            directory = record.get("working_directory", "") if directory_input_enabled(config, context.input_ports) else str(working_directory(context, config))
            identifier = state.reusable(record, directory=directory, generation=config["session_generation"]) if config["use_persistent_session"] else ""
            if record and not identifier:
                state.save("", directory=directory, generation=config["session_generation"])
            setter = context.services.get("set_node_runtime_value")
            if callable(setter):
                setter("zcode_session_id", identifier)
            return BlockRuntimeResult(metadata={"zcode_session_id": identifier})
    except ZcodeCancelled:
        return BlockRuntimeResult(status="cancelled")
    except Exception as error:
        return BlockRuntimeResult(status="failed", exit_code=1, error=str(error), logs=[f"[zcode-init-error] {error}"])


def final_result(raw):
    """Accept only Zcode's completed JSON summary, never events or partial text."""
    try:
        result = json.loads(raw)
    except ValueError as error:
        raise ZcodeError("Zcode returned invalid JSON. Update the CLI; no raw output was published.") from error
    if not isinstance(result, dict) or not isinstance(result.get("projection"), dict) or result["projection"].get("status") != "idle":
        raise ZcodeError("Zcode did not return a final result.")
    if not isinstance(result.get("response"), str) or not result["response"].strip():
        raise ZcodeError("Zcode final response is empty or is not text.")
    session_id(result.get("sessionId"))
    return result


def execute(context, model):
    """Run outputs sequentially with one instance session and final text only."""
    records, outputs, logs = [], [], []
    identifier = ""
    started = time.monotonic()
    metadata = {}
    try:
        config = normalize_config(context.config, model)
        directory = working_directory(context, config)
        prompts = [(port, build_prompt(context, port, config)) for port in context.output_ports]
        if not prompts:
            raise ZcodeError("At least one output is required.")
        check_cancel(context)
        launch, env, stdin_prompt = resolve_launch(config)
        persistent = config["use_persistent_session"]
        # Stateless calls do not require instance scope. A scoped call still clears
        # a previously persisted association when the checkbox is disabled.
        state = None
        if persistent:
            state = SessionFile(context)
        elif callable(context.services.get("get_block_storage_dir")):
            try:
                state = SessionFile(context)
            except Exception as error:
                if "block_storage.missing_scope" not in str(error):
                    raise
        deadline = started + MAX_ACTIVATION_SECONDS
        with state.locked(context, deadline) if state else nullcontext():
            if state:
                record = state.read()
                identifier = state.reusable(record, directory=directory, generation=config["session_generation"]) if persistent else ""
                if not persistent:
                    state.save("", directory=directory, generation=config["session_generation"])
            setter = context.services.get("set_node_runtime_value")
            if callable(setter):
                setter("zcode_session_id", identifier)
            metadata["zcode_session_id"] = identifier
            for port, prompt in prompts:
                check_cancel(context)
                args = launch + ["--json", "--no-color", "--mode",
                    "yolo" if config["dangerously_allow_all"] else config["permission_mode"]]
                if persistent and identifier:
                    args.extend(["--resume", identifier])
                command = shlex.join(args) + (" < <prompt via stdin>" if stdin_prompt else " --prompt <omitted>")
                metadata.update(last_zcode_command=command, working_directory=str(directory))
                logs.append(f"[zcode-cmd] {context.node_id}.{port.id}: {command}")
                code, raw, stderr = run_cli(context, args, prompt=prompt, directory=directory,
                    deadline=min(deadline, time.monotonic() + config["timeout_sec"]), env=env, stdin_prompt=stdin_prompt)
                logs.append(f"[zcode-exit] {context.node_id}.{port.id}: exit_code={code}")
                if code:
                    if "Model config is missing" in stderr:
                        raise ZcodeError("Zcode headless model is not configured. Configure the local Zcode CLI model/provider first; desktop sign-in alone is not sufficient.")
                    # CLI stderr may contain provider credentials or echoed prompts.
                    raise ZcodeError(f"Zcode exited with code {code}. Check local CLI authentication, model configuration and session availability.")
                if len(raw.encode()) > MAX_RESPONSE_BYTES:
                    raise ZcodeError("Zcode response exceeded the 4 MiB limit.")
                result = final_result(raw)
                text = result.get("response")
                if not isinstance(text, str):
                    raise ZcodeError("Zcode final result is not text.")
                check_cancel(context)
                if persistent:
                    returned_id = session_id(result.get("sessionId"))
                    if identifier and returned_id != identifier:
                        raise ZcodeError("Zcode returned a different session. The saved association was not changed.")
                    identifier = returned_id
                    state.save(identifier, directory=directory, generation=config["session_generation"])
                metadata["zcode_session_id"] = identifier if persistent else ""
                if callable(setter):
                    setter("zcode_session_id", identifier if persistent else "")
                usage = result.get("usage") or {}
                safe_usage = {k: v for k, v in usage.items() if k in {"inputTokens", "outputTokens", "totalTokens", "cacheReadTokens", "cacheWriteTokens"} and isinstance(v, (int, float))} if isinstance(usage, dict) else {}
                records.append({"port_id": port.id, "usage": safe_usage, "prompt_chars": len(prompt)})
                outputs.append(BlockRuntimeOutput(port_id=port.id, port_name=port.name,
                    value=redact(context, text), content_type=TEXT_PLAIN,
                    metadata={**metadata, "usage": safe_usage, "prompt_chars": len(prompt)}))
        metadata.update(outputs=records, duration=round(time.monotonic() - started, 3))
        logs.append(f"[done] Zcode {context.node_id}: {len(outputs)} output(s) emitted.")
        return BlockRuntimeResult(outputs=outputs, logs=logs, metadata=metadata,
                                  last_message=outputs[-1].value, worker_received=outputs[-1].value)
    except ZcodeCancelled as error:
        return BlockRuntimeResult(status="cancelled", logs=logs + [f"[zcode-cancelled] {context.node_id}"], metadata=metadata)
    except Exception as error:
        message = redact(context, str(error))[:4000]
        return BlockRuntimeResult(status="failed", error=message, exit_code=1, last_message=message,
            logs=logs + [f"[zcode-error] {context.node_id}: {message}"], metadata=metadata)
