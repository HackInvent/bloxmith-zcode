# Zcode

<!-- block-metadata:start -->
[![Block version: 0.1.0](https://img.shields.io/badge/block-0.1.0-blue)](model.json)
[![BloxSmith compatibility: 1.0.9](https://img.shields.io/badge/BloxSmith-1.0.9-brightgreen)](compatibility.json)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

Verified BloxSmith versions: **1.0.9** (bundled-block tests; see [test evidence](compatibility.json)).
<!-- block-metadata:end -->

[![Zcode — violet pixel-art terminal module with directory, instruction and session symbols](media/thumbnail.webp)](media/cover.png)

*Concept illustration of the block's function, not a Studio screenshot. [Artwork and generation prompt](media/README.md).*

Run the local **Zcode agent**, with the same workflow pattern as the Codex block:
named inputs, one instruction per output, a working directory and an optional
persistent session. The block launches the agent, **not the desktop UI**.

## Prerequisites

- Linux/POSIX and an installed official Zcode CLI or Zcode Desktop containing
  `resources/glm/zcode.cjs`. Zcode is not downloaded or redistributed by this block.
- Configure the **headless Zcode model/provider and authentication** on the machine
  running Studio. Desktop sign-in alone is not sufficient in all installations.
  Verify that a harmless `--prompt` call succeeds before running a workflow.
- An explicit engine script needs a compatible Node runtime; the desktop engine
  can use its own Electron/Node runtime automatically. An old system Node may lack
  `node:sqlite` and cannot run recent Zcode engines.

The adapter follows the final JSON protocol observed in **Zcode CLI 0.16.5**.
Some flags advertised by that version's help are not accepted by its parser:
in particular, do not assume Claude-compatible `--model`, `--effort`,
`--settings`, `--max-turns` or MCP flags. The model and MCP tools are configured
in **Zcode itself**, not in this block or a BloxSmith wallet field. The block does
not read, migrate or modify Zcode credentials/configuration.

Official references: [Zcode source and CLI](https://github.com/zai-org/ZCode),
[installation and provider setup](https://zcode.z.ai/en/docs/install).

## Ports and execution

| Port | Type | Behavior |
| --- | --- | --- |
| `in` (additional inputs allowed) | Text, message or JSON | Named context for the instruction; JSON, zero and false are preserved. |
| Optional `working_directory` | `config/working-directory`, text or message | Created immediately by its checkbox; non-empty value overrides the configured directory. |
| `out` (additional outputs allowed) | Final text | One Zcode call per output, using that output's instruction. |

The Instructions tab can map an existing data input to an output instruction.
A non-empty text value replaces that instruction; an empty or whitespace-only value uses the fixed
instruction. Mappings use **port IDs**, not display order. Mapped control inputs
are excluded from ordinary prompt context. No input is created implicitly for an
instruction override. Adding/removing ports uses the standard inspector.

Outputs run sequentially and share one session when persistence is enabled. No
partial/tool/reasoning events are published. All output calls must succeed before
the activation returns outputs; a later failure can still leave earlier successful
turns in Zcode's history. Inputs follow the framework's ordinary all-input readiness.
Both One Shot Simulation (`centralized`) and Active Runtime (`zeromq_active`)
**execute Zcode and can make provider calls**; simulation is not a provider dry-run.

## Properties

- **Working directory:** an explicit existing directory is required, either in
  this field or from its input. Relative paths resolve from the runtime root;
  `~` expands locally. Enabling the checkbox immediately creates the optional
  `working_directory` port in both the modal and inspector, without Apply.
  Disabling it immediately removes that port and its links. **Cancel** does not
  undo this explicit port operation; other drafts remain local until Apply.
- **Persistent session:** enabled by default. The session ID is shown and can be
  copied in properties once restored at Run or obtained from a successful call.
- **New session:** Apply schedules a reset for the next Run/execution, without
  deleting Zcode history. Unchecking persistence forgets the block association
  at that point. Zcode may still keep its own history; this is not incognito mode.
- **Permission mode:** `build` (default), `plan` or `edit`, passed explicitly.
  This unattended block cannot ask interactive approval questions. A separate
  **Danger** checkbox explicitly selects Zcode's unrestricted `yolo` mode.
  It is never enabled implicitly, even though Zcode's own headless default is yolo.
- **Zcode executable:** `zcode` by default; a command name or executable path,
  never a shell command. A standard desktop installation is recognized by files.
- **Engine script / Node runtime:** normally empty. Select an explicit `.cjs` or
  `.js` entry and compatible Node executable for another installation. A missing
  engine in a recognized desktop layout is an error, never a GUI fallback.
- **Timeout:** 1–240 seconds per call, with a 240-second whole-activation budget.
- **Prompt limit:** 1–1,000,000 characters, default 250,000. Standalone executable
  mode additionally caps prompts at 64,000 UTF-8 bytes due to OS argument limits.

Desktop/explicit-engine mode passes the prompt through stdin to a block-owned
Node launcher and sets process-local argv before loading the official CLI. It
does not patch Zcode. Standalone executable mode uses the public `--prompt`
argument: the prompt can be visible to OS process-inspection tools. Neither mode
puts the prompt in block command diagnostics. Do not feed secrets as instructions.
Tools, plugins, hooks, project instructions and permissions configured in Zcode
still apply. This block is not a filesystem/security sandbox.

The opaque, keyboard-accessible properties dialog has Settings, Instructions,
Ports and Diagnostics tabs, pinned actions and internal scrolling on small screens.
English and French catalogs are included. Drafts survive diagnostic refresh.

### Alignment with native Codex

The directory port has the native control type `config/working-directory`, also
accepts `text/plain` and `message/*`, uses `multiplicity: many` and is optional for
execution. It is recognized by type or its historical `working_directory` name,
not by display order. An existing port is reused even if the config flag is stale;
repeated synchronization does not duplicate it. Non-empty input takes precedence
over static configuration, whitespace input falls back to it, and the directory
never enters the prompt. **The previous implicit runtime-root fallback is removed:**
both sources blank or an invalid directory fail before starting Zcode. Dynamic
sessions may initialize at Run before the input arrives; validation happens before
the actual call. The switch is disabled while saving and displays failures without
saving unrelated drafts.
As with Codex, an optional input does not delay execution. If a PUSH source must
arrive first, set this port to **Required for execution** in the Ports inspector.

The common workflow remains named inputs, per-output instructions, persistent
block/instance sessions, explicit danger permission, prompt limits, redacted
diagnostics and Apply for ordinary settings. There are deliberate boundaries:

- Model/effort and MCP setup remain in Zcode's own configuration; unsupported CLI
  flags are not added to imitate Codex controls.
- The native paired instruction/effective ports are protected by a Codex-only
  graph operation. Generic deletion also refuses them. Full parity needs a generic
  atomic framework operation. This block keeps its existing explicit input-ID
  bindings instead of bypassing protections or rewriting graph files.
- The framework's global Codex instruction and native manual-conversation surface
  are not silently applied to Zcode.

## Persistence and cancellation

Only the block's session association is stored in `zcode_session.json`, using
`context.services["get_block_storage_dir"]()`. There are no guessed instance paths.
The file is atomic, mode 0600, bounded and protected by a cross-process lock.
Malformed state fails explicitly. A copied instance, changed directory or requested
reset starts a distinct session; an unavailable external session fails without
silently creating another one. No transcript, prompt or credential is saved here.

Run Stop/cancellation and timeouts terminate the activation's CLI process group.
A lifetime pipe also covers forced termination of an isolated managed host.
New instructions do **not** interrupt an already running instruction; this block
does not replace the framework's scheduling/queueing rules.

The framework's manual-conversation UI is currently reserved for trusted native
blocks; this managed package does not expose or bypass that surface.

## Verification and limits

Block-owned tests cover prompt building and reordered ports, configuration errors,
multiple outputs, session restore/reset/disable/copy, concurrency, final JSON
validation, cancellation, timeouts, bounded output, engine launching, and actual
managed/linked package execution in both runtime modes. Browser tests exercise
Apply, tabs, French labels and desktop/narrow layouts in the real framework shell.
Provider access is simulated in regression suites. A live model reply requires
separate local Zcode setup and is not implied by compatibility evidence.

An optional probe runs an **installed real engine** against a local HTTP model
fixture in a temporary workspace and checks final JSON plus session context reuse:

```sh
python3 tests/probe_installed_engine.py --engine ENGINE_SCRIPT --node NODE_EXECUTABLE
```

Add `--electron` only when the executable is Zcode Desktop's Electron binary.
No real provider is used and no personal configuration is written. This probe
passed with the locally installed Zcode engine **0.16.5**; production provider
credentials/model availability are a separate prerequisite.

The source is an initial **0.1.0** package. No public repository, release or
catalog entry is created by local implementation/testing.

## License

[Apache License 2.0](LICENSE). Zcode and the BloxSmith framework retain their own
licenses and are not included in this package.

## Properties ergonomics

The canvas card has its own release-scoped stylesheet: a type badge, a prominent
block name, a two-line instruction preview and a permission-mode/timeout summary.
Empty instructions and input overrides are explicit. Long titles and settings
are truncated visually with tooltips; the standard shell, status and ports are
unchanged. Browser tests check these cards before opening any properties surface.

Modal and inspector styles are owned by this package and scoped to its exact
release. Forms adapt to narrow panels, checkboxes stay beside their labels, and
long values do not widen the inspector. Existing labels are associated with
controls; keyboard navigation complements the block’s own tab handlers.
These presentation helpers do not change port bindings, authored settings,
runtime behavior or the block’s original surface cleanup.
