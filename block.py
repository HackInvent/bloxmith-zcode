"""Autonomous Zcode block: public runtime, UI bindings and release assets."""

from html import escape
import json

from bloxsmith_app.block_api import (
    BlockDefinition, render_inspector_template, render_node_card_template,
    render_path_browser_control,
)
from .runtime import (execute, initialize, normalize_config, boolean, PERMISSIONS,
                      is_working_directory_port, directory_input_enabled)


class ZcodeBlock(BlockDefinition):
    """One Zcode CLI call per output, with optional instance-scoped continuation."""

    kind = "zcode"

    def initialize_runtime(self, context):
        """Restore the session identifier before any business input arrives."""
        return initialize(context, self.model)

    def execute_runtime(self, context):
        """Use the identical generic adapter in centralized and active runtimes."""
        return execute(context, self.model)

    def normalize_config(self, config):
        """Expose strict block-owned configuration validation for tooling/tests."""
        return normalize_config(config, self.model)

    def text(self, key, fallback):
        """Mark static UI text for block-owned English/French localization."""
        full = f"block.zcode.{key}"
        return f'<span data-i18n="{full}">{escape(self.translate(full, fallback=fallback))}</span>'

    def field(self, config, key, title, *, kind="text", attrs="", options=None):
        """Render accessible generic config bindings, including inline checkboxes."""
        value = config.get(key, "")
        label = self.text(key, title)
        binding = f'data-block-config-field="{key}"'
        if kind == "checkbox":
            return f'<label class="zcode-check"><input type="checkbox" {binding}{" checked" if boolean(value) else ""}>{label}</label>'
        if options is not None:
            control = f'<select {binding}>' + "".join(
                f'<option value="{escape(str(k), quote=True)}"{" selected" if str(k) == str(value) else ""}>{escape(str(v))}</option>'
                for k, v in options) + '</select>'
        else:
            numeric = 'data-block-value-type="integer"' if kind == "number" else ""
            control = f'<input type="{kind}" {binding} {numeric} {attrs} value="{escape(str(value), quote=True)}">'
        return f'<label class="field-group">{label}{control}</label>'

    def _config(self, node):
        """Keep even invalid authored values editable; validation happens at Apply/Run."""
        config = {**self.default_config(), **(node.get("config") or {})}
        config["working_directory_input_enabled"] = directory_input_enabled(config, node.get("inputs") or [])
        return config

    def _configuration_html(self, node, payload):
        """Group common tasks first, with permissions and limits in Advanced."""
        config = self._config(node)
        picker = render_path_browser_control(
            input_id="zcode-working-directory", label="Working directory", value=config["working_directory"],
            placeholder="Select a directory or use the input", select_mode="directory",
            label_key="block.zcode.working_directory", placeholder_key="block.zcode.directory_placeholder",
            input_attrs='data-block-config-field="working_directory"')
        result = (payload.get("runtime") or {}).get("result") or {}
        meta = result.get("metadata") or {}
        state = result.get("runtime_state") or {}
        # Execution metadata is newer than the Active Runtime's initialization
        # snapshot. An explicitly empty execution ID must also win after reset.
        identifier = str(result.get("zcode_session_id", meta.get("zcode_session_id", state.get("zcode_session_id", ""))) or "")
        return (
            '<div class="zcode-settings-stack"><section class="zcode-modal-section">'
            f'<h3>{self.text("execution", "Execution")}</h3>'
            f'<label class="field-group">{self.text("title", "Block name")}<input data-block-title-field value="{escape(str(node.get("title") or self.default_title()), quote=True)}"></label>'
            f'{picker}<label class="zcode-check"><input type="checkbox" data-zcode-working-directory-input-enabled{" checked" if config["working_directory_input_enabled"] else ""}>'
            f'{self.text("working_directory_input_enabled", "Use an input for the working directory")}</label>'
            f'<p class="field-hint">{self.text("directory_hint", "This switch applies immediately. Turning it off removes the input and its links. A non-empty input overrides the configured directory.")}</p>'
            '<p class="field-hint" data-zcode-directory-feedback role="status" aria-live="polite" hidden></p>'
            f'<p class="field-hint">{self.text("model_hint", "Model, credentials and MCP tools come from your local Zcode configuration. Desktop sign-in alone may not configure the headless engine.")}</p>'
            '</section><section class="zcode-modal-section">'
            f'<h3>{self.text("session", "Session")}</h3>'
            f'<div class="zcode-session-row"><code data-zcode-session-id>{escape(identifier)}</code>'
            f'<span data-zcode-session-empty{" hidden" if identifier else ""}>{self.text("session_empty", "Available after the first successful execution")}</span>'
            f'<button type="button" class="ghost-btn" data-zcode-copy-session{" disabled" if not identifier else ""}>{self.text("copy", "Copy")}</button></div>'
            f'{self.field(config, "use_persistent_session", "Use a persistent Zcode session", kind="checkbox")}'
            f'<p class="field-hint">{self.text("session_hint", "One session per block and blueprint instance. All outputs share it sequentially. Disabling persistence forgets the association at the next execution, not the Zcode transcript.")}</p>'
            f'<input type="hidden" data-block-config-field="session_generation" value="{escape(str(config["session_generation"]), quote=True)}">'
            f'<button type="button" class="ghost-btn" data-zcode-reset-session>{self.text("reset_session", "New session on next execution")}</button>'
            '<p class="field-hint" data-zcode-session-feedback role="status"></p>'
            '</section><details class="zcode-modal-section"><summary>'
            f'{self.text("advanced", "Permissions and limits")}</summary><div class="zcode-advanced">'
            f'{self.field(config, "permission_mode", "Permission mode", options=[(p, p) for p in PERMISSIONS])}'
            f'{self.field(config, "dangerously_allow_all", "Danger: bypass all permission checks", kind="checkbox")}'
            f'<p class="zcode-warning">{self.text("permissions_hint", "Build, plan and edit keep Zcode permission checks. There is no approval dialog in this unattended block. Danger explicitly enables yolo mode.")}</p>'
            f'{self.field(config, "zcode_binary", "Zcode executable")}'
            f'{self.field(config, "engine_script", "Engine script (optional)")}'
            f'{self.field(config, "node_binary", "Node runtime (optional)")}'
            f'<p class="field-hint">{self.text("engine_hint", "Leave these two fields empty for automatic detection. An explicit engine script needs a compatible Node runtime. No installation files are changed.")}</p>'
            '<div class="zcode-config-grid">'
            f'{self.field(config, "timeout_sec", "Timeout per call (s)", kind="number", attrs="min=1 max=240 step=1")}'
            f'{self.field(config, "max_prompt_chars", "Prompt limit (characters)", kind="number", attrs="min=1 max=1000000 step=1000")}</div>'
            f'<p class="field-hint">{self.text("limits_hint", "240 seconds maximum for the whole activation. Authentication uses the local Zcode CLI; no API key is stored in this block.")}</p>'
            '</div></details></div>'
        )

    def _instructions_html(self, node):
        """Per-output editors and explicit data-input overrides keyed by stable ID."""
        config = self._config(node)
        mapping = config.get("instruction_inputs") or {}
        panels = []
        for port in node.get("outputs", []):
            pid = str(port["id"])
            source = str(mapping.get(pid, ""))
            options = f'<option value="">{escape(self.translate("block.zcode.fixed_instruction", fallback="Use the instruction below"))}</option>'
            inputs = [p for p in node.get("inputs", []) if not is_working_directory_port(p)]
            for p in inputs:
                options += f'<option value="{p["id"]}"{" selected" if str(p["id"]) == source else ""}>{escape(str(p.get("name") or p["id"]))} (#{p["id"]})</option>'
            if source and source not in {str(p["id"]) for p in inputs}:
                options += f'<option value="{escape(source, quote=True)}" selected>#{escape(source)} — unavailable</option>'
            panels.append(
                f'<section class="zcode-modal-section zcode-output-editor"><h3>{escape(str(port.get("title") or port.get("name") or pid))}</h3>'
                f'<label class="field-group">{self.text("instruction_source", "Instruction source")}<select data-zcode-instruction-source="{pid}">{options}</select></label>'
                f'<label class="field-group">{self.text("instruction", "Instruction")}<textarea rows="14" spellcheck="false" data-block-output-field="instruction" data-block-output-port-id="{pid}">{escape(str(port.get("instruction") or ""))}</textarea></label>'
                f'<p class="field-hint">{self.text("instruction_hint", "A non-empty selected input replaces this instruction. Other inputs are included as named data. Port order does not change the mapping.")}</p></section>')
        return f'<input type="hidden" data-block-config-field="instruction_inputs" data-block-value-type="json" value="{escape(json.dumps(mapping), quote=True)}">' + ''.join(panels)

    def render_modal(self, *, node, payload=None):
        """Render an opaque, responsive modal with pinned actions and owned tabs."""
        payload = payload or {}
        result = (payload.get("runtime") or {}).get("result") or {}
        command = str(result.get("last_zcode_command") or (result.get("metadata") or {}).get("last_zcode_command") or "")
        panels = [("attributes", "settings", "Settings", self._configuration_html(node, payload)),
                  ("instructions", "instructions", "Instructions", self._instructions_html(node)),
                  ("ports", "ports", "Ports", self._render_generic_modal_ports(node)),
                  ("last-cmd", "diagnostics", "Diagnostics", f'<section class="zcode-modal-section"><h3>{self.text("last_command", "Last command")}</h3><pre data-zcode-last-command>{escape(command)}</pre><p class="field-hint">{self.text("command_hint", "The prompt is omitted. CLI errors never echo provider credentials.")}</p></section>')]
        tabs, body = [], []
        for index, (key, text_key, title, content) in enumerate(panels):
            selected = index == 0
            tabs.append(f'<button type="button" class="zcode-modal-tab" data-zcode-modal-tab data-zcode-tab-id="{key}" id="zcode-tab-{key}" role="tab" aria-controls="zcode-panel-{key}" aria-selected="{str(selected).lower()}" tabindex="{0 if selected else -1}">{self.text(text_key, title)}</button>')
            body.append(f'<section class="zcode-modal-panel" data-zcode-modal-panel data-zcode-tab-id="{key}" id="zcode-panel-{key}" role="tabpanel" aria-labelledby="zcode-tab-{key}"{"" if selected else " hidden"}>{content}</section>')
        template = (self.directory / "block_modal.html").read_text(encoding="utf-8")
        for key, value in {"node_id": escape(str(node.get("id") or ""), quote=True),
                           "node_title": escape(str(node.get("title") or self.default_title())),
                           "tabs": ''.join(tabs), "panels": ''.join(body)}.items():
            template = template.replace("{{ " + key + " }}", value)
        return {"html": template, "context": {"node_id": node.get("id"), "node_kind": self.kind}}

    def render_inspector_panel(self, *, node, payload=None):
        """Reuse the same settings and instructions with the standard ports editor."""
        template = (self.directory / "inspector_panel.html").read_text(encoding="utf-8")
        template = template.replace("{{ settings }}", self._configuration_html(node, payload or {}))
        template = template.replace("{{ instructions }}", self._instructions_html(node))
        return {"html": render_inspector_template(template=template, node=node, payload=payload),
                "context": {"node_id": node.get("id"), "full_panel": True}}

    def render_node_card(self, *, node, payload=None):
        """Show a bounded instruction and settings preview inside the standard shell."""
        config = self._config(node)
        port = next(iter(node.get("outputs") or []), {})
        instruction = " ".join(str(port.get("instruction") or "").split())
        instruction_key = ""
        if (config.get("instruction_inputs") or {}).get(str(port.get("id"))):
            instruction_key = "block.zcode.card_input_instruction"
            instruction = self.translate(instruction_key, fallback="Instruction from input")
        elif not instruction:
            instruction_key = "block.zcode.card_empty_instruction"
            instruction = self.translate(instruction_key, fallback="No instruction")
        if len(instruction) > 240:
            instruction = instruction[:239] + "…"
        permission = "yolo" if boolean(config.get("dangerously_allow_all")) else config["permission_mode"]
        try:
            timeout = str(min(int(config["timeout_sec"]), 240))
        except (TypeError, ValueError, OverflowError):
            timeout = "—"
        rendered = render_node_card_template(block=self, node=node, node_classes=["zcode-node"], replacements={
            "title": node.get("title") or self.default_title(), "instruction": instruction,
            "instruction_key": instruction_key, "configuration": f"{permission} · {timeout} s"})
        # Authored instructions are data, never translation keys.
        rendered["html"] = rendered["html"].replace(' data-i18n=""', '').replace(' data-i18n-title=""', '')
        return rendered

    def _directory_port_operations(self, node, enabled):
        """Build idempotent public operations; keep unrelated ports and existing IDs intact."""
        existing = next((p for p in node.get("inputs", []) if is_working_directory_port(p)), None)
        if enabled and existing is None:
            return [{"op": "create_port", "node_id": node["id"], "direction": "input",
                     "name": "working_directory", "title": "Working directory",
                     "accepts": ["config/working-directory", "text/plain", "message/*"],
                     "multiplicity": "many", "required": False, "execution_requirement": "not_required_for_execution"}]
        if not enabled and existing is not None:
            return [{"op": "delete_port", "node_id": node["id"], "direction": "input", "port_id": existing["id"], "cascade": True}]
        return []

    def handle_ui_action(self, *, node, action, values, payload=None):
        """Persist the directory switch immediately; other authored fields still use Apply."""
        if action == "sync_working_directory_input":
            if not node.get("id"):
                return {"error": "missing_node_id"}
            enabled = boolean(values.get("enabled"))
            return {"graph_operations": [
                {"op": "update_node_config", "node_id": node["id"], "config": {"working_directory_input_enabled": enabled}},
                *self._directory_port_operations(node, enabled)], "rerender_inspector": False}
        result = super().handle_ui_action(node=node, action=action, values=values, payload=payload)
        patch = result.get("node_patch") or {}
        if "config" not in patch:
            return result
        try:
            config = self.normalize_config({**self._config(node), **patch["config"]})
        except ValueError as error:
            return {"error": str(error)}
        patch["config"] = config
        operations = self._directory_port_operations(node, config["working_directory_input_enabled"])
        if operations:
            result.update(graph_operations=operations, rerender_inspector=True)
        return result
