# Host Recovery

The Skill workflow and working-note format are portable. Automatic recovery uses a
host-specific lifecycle event and returns advisory task context.

| Host | Skill location | Bundled event | Output contract |
|---|---|---|---|
| Codex | Installed Plugin Skill | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| Claude Code | `~/.claude/skills/task-state-with-files` | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| ZCode | `~/.zcode/skills/task-state-with-files` | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| Kimi Code | `$KIMI_CODE_HOME/skills/task-state-with-files` (default `~/.kimi-code`) | `UserPromptSubmit` | plain stdout in model context and UI |
| Hermes | `~/.hermes/skills/task-state-with-files` | Skill-only | manual `read` |

## Locating the record

All adapters require a launch selection (`TASK_STATE_TASK` or `TASK_STATE_FILE`) or
an explicit binding for the native `session_id` in the hook event. With neither,
they are silent even when a legacy file, one record or several records exist.
`TASK_STATE_ROOT` pins an exact workspace; otherwise the selected recovery uses the
nearest task root from the event’s `cwd`, stopping at a task marker or Git boundary. Set these in the host's launch environment;
changing a child tool shell's environment does not change the already-running host.

Select an existing record for the actual native session before relying on recovery:

```bash
python3 "<skill-dir>/scripts/task_state.py" activate --task <task-id> --session <native-session-id> --root <project-root>
python3 "<skill-dir>/scripts/task_state.py" deactivate --session <native-session-id> --root <project-root>
```

`activate --file <relative-path>` selects an existing business note. Each workspace
stores separate `.tasks/.sessions/<session-hash>.ref` files; do not commit them.
A different record requires deactivation first, and a new session selects its own
record. Launch selectors take precedence over a saved session binding; supplying both
task and file is invalid. No selector ever falls back after an error. A root pin alone
is not activation. If the host does not expose a native session ID, use launch selectors
or explicit full reads. Legacy file/binding and unique-record discovery remain available
only to deliberate CLI `read`/`resolve`, not unselected hooks.

An agent can always select and read manually using the loaded Skill path:

```bash
python3 "<skill-dir>/scripts/task_state.py" read --task <task-id> --root <project-root>
python3 "<skill-dir>/scripts/task_state.py" read --file docs/wip/example.md --root <project-root>
```

`resolve` reports metadata only. A missing receiving-side file requires locating or
transferring the existing record and its necessary artifacts; changing the selector does
not copy them.

## Reading the recovery output

A record that fits the 8,000-character budget with its header arrives intact. Larger
records yield a labeled partial preview of complete sections. Read the whole selected
record before making continuation decisions from a partial preview. Omitted sections
may contain decisive corrections or unfinished checks.

All adapters are advisory and fail open. Unselected recovery is silent. An invalid explicitly selected
record or binding emits a bounded diagnostic. `TASK_STATE_DISABLED=1` silences every bundled adapter
for an unrelated one-shot invocation. No adapter schedules continuation or blocks stopping.

## Verification boundary

Repository tests run the hook executables with realistic event payloads and check their
output contracts, root/task selection, opt-out, and rejection behavior. Installer tests
use temporary homes. These prove local script behavior, not a particular installed
host's end-to-end recovery after context compaction.

To establish that installed behavior, use an authorized disposable task, write a
recognizable intent/correction/unfinished check, trigger the host's real compaction or
resume boundary, and inspect whether the next model request receives and uses the state.
Record host version, event, selected record, and observed continuation. A fresh agent
reading a generated hook packet is a behavioral exercise, not that native lifecycle test.

For missing recovery, inspect selection with `resolve`, read with `read`, then check the
installed hook and host event/output contract. Do not compensate by adding a Stop hook,
heartbeat, or per-model-step injector. Hermes currently uses this package's manual path.

Kimi Code 0.41.0 ignores returned text from `SessionStart` and `PostCompact`.
The adapter rereads state on every user message, including after resume, and emits
at most 8,000 characters. It does not fire on non-user autonomous continuations.
Kimi's own post-compaction journal pointer helps recover conversation history but
is not this Skill's state injection. API compatibility does not confer another
client's hook lifecycle or return-value handling.

Use either the native `kimi.plugin.json` package or the user installer. Enabling
both registers duplicate recovery hooks. The installer honors `KIMI_CODE_HOME`
for both Skill files and config; `~/.kimi` belongs to the legacy Python CLI.

Primary references, checked on 2026-09-06:
[Kimi hooks](https://www.kimi.com/code/docs/kimi-code-cli/customization/hooks.html),
[Skill discovery](https://www.kimi.com/code/docs/kimi-code-cli/customization/skills.html),
[environment variables](https://www.kimi.com/code/docs/kimi-code-cli/configuration/env-vars.html).
