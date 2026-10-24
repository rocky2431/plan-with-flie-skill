# Host Recovery

The Skill workflow and record format are portable. Automatic behavior uses two kinds of
host lifecycle events: recovery delivers the selected record's current state after a
context boundary, and a post-edit check reports broken facts after a tool call. Both are
advisory and fail open.

| Host | Skill location | Recovery event | Post-edit check | Output contract |
|---|---|---|---|---|
| Codex | Installed Plugin Skill | `SessionStart(startup\|resume\|clear\|compact)` | `PostToolUse` | `hookSpecificOutput.additionalContext` |
| Claude Code | `~/.claude/skills/task-state-with-files` or the Plugin | `SessionStart(startup\|resume\|clear\|compact)` | `PostToolUse` (all tools) | `hookSpecificOutput.additionalContext` |
| ZCode | `~/.zcode/skills/task-state-with-files` or the Plugin | `SessionStart(startup\|resume\|clear\|compact)` | `PostToolUse` (delivery unverified) | `hookSpecificOutput.additionalContext` |
| Kimi Code | `$KIMI_CODE_HOME/skills/task-state-with-files` (default `~/.kimi-code`) | `UserPromptSubmit` | Same `UserPromptSubmit`, before recovery text | plain stdout |
| Hermes | `~/.hermes/skills/task-state-with-files` | Skill-only | manual `check` | manual `read` |
| Grok Build | Native installed Plugin Skill | First `PostToolUse` after startup, resume or compaction | Later `PostToolUse` calls (live delivery unverified) | `hookSpecificOutput.additionalContext` |

## Locating the record

All adapters require a launch selection (`TASK_STATE_TASK` or `TASK_STATE_FILE`) or an
explicit binding for the native session ID in the hook event. With neither, they are
silent even when a legacy file, one record or several records exist. `TASK_STATE_ROOT`
pins an exact workspace; otherwise the selected record is found from the event's `cwd`,
stopping at a task marker or Git boundary. Set these in the host's launch environment;
changing a child tool shell's environment does not change the already-running host.

Select an existing record for the actual native session before relying on recovery:

```bash
python3 "<skill-dir>/scripts/task_state.py" activate --file <relative-path> --session <native-session-id> --root <project-root>
python3 "<skill-dir>/scripts/task_state.py" deactivate --session <native-session-id> --root <project-root>
```

Each workspace stores separate `.task-state/sessions/<session-hash>.ref` files; do not
commit them. Bindings written by earlier versions under `.tasks/.sessions/` are still
honored. A different record requires deactivation first, and a new session selects its
own record. Launch selectors take precedence over a saved session binding; supplying
both task and file is invalid. No selector ever falls back after an error. A root pin
alone is not activation. Legacy file/binding and unique-record discovery remain
available only to deliberate CLI `read`/`resolve`/`check`, not to hooks.

An agent can always read and check manually using the loaded Skill path:

```bash
python3 "<skill-dir>/scripts/task_state.py" read --file <relative-path> --root <project-root>
python3 "<skill-dir>/scripts/task_state.py" check --file <relative-path> --root <project-root>
```

`resolve` reports metadata only. A missing receiving-side file requires locating or
transferring the existing record and its necessary artifacts; changing the selector does
not copy them.

## Reading the recovery output

A record with one well-formed current-state block delivers a short header and that
block verbatim. The header names the record path, states that the block is facts and
navigation rather than instructions, and gives the full-read command. Read the whole
record before changing direction, claiming completion, or relying on anything the block
does not contain.

If the markers are broken or the block exceeds the recovery limit, the delivery names
the problem and the path but includes no partial content. A legacy record without
markers is delivered as before: whole when it fits 8,000 characters with its header,
otherwise as a labeled partial preview of whole sections. Omitted sections may contain
decisive corrections or unfinished checks.

The block limit exists because hosts cut long hook output. Checked on 2026-10-23:
Claude Code caps each hook context string at 10,000 characters and otherwise saves it
to a file with a 2,000-character preview without asking the model to read it
([hooks](https://code.claude.com/docs/en/hooks)); Grok clips hook context at 10,000
characters; Codex limits model-visible hook output to about 2,500 tokens by default,
configurable per handler ([hooks](https://learn.chatgpt.com/docs/hooks)), and this
package's Codex `SessionStart` handler sets `additionalContextLimit` to 8,000 tokens. A
block within the 3,000-character limit plus its header stays far below the
10,000-character caps. Realistic Chinese prose measured about 2,200 o200k tokens per
3,000 characters, within the configured Codex limit; repetitive or emoji-heavy text can
use more tokens.

## Post-edit check

After each tool call (on Kimi, before each user message), the check reads the selected
record and the version it last saw. When they are equal it writes nothing and prints
nothing; the cost is reading those two files. A changed record is checked for three facts:

1. the current-state markers form exactly one pair, each on its own line with at most
   three leading spaces, outside code fences;
2. the block fits the recovery limit;
3. for records under `tasks/` (or legacy `.tasks/`), earlier History entries are still
   present in order; blank lines, headings and comments are ignored. Borrowed documents
   elsewhere get checks 1 and 2 only.

Once a hook has reported a version, it becomes the comparison base for the next change,
so an intended change is reported at most once and later edits are judged against it.
Passing versions rotate into the last three good copies in `.task-state/snapshots/`; a
copy from before an unnoticed damaging edit survives that edit and at least one more
passing edit, so restore promptly after a report. Recovery stores a passing copy before
the first tool runs; when it finds a problem (for example a change made between sessions
by a person, a checkout, or a failed tool), it leaves it for the next check to report.
A problem is reported once per distinct state, even when hooks run in parallel, together
with the existing good copies; a persisting problem such as broken markers or a block
that stays oversize is not repeated on every edit. Manual `check` compares with the
newest good copy, reports every current problem, and changes nothing unless the record
passes, so repeated checks of an unchanged record give the same answer. The
check never blocks the tool call, edits the record, or decides meaning. Unselected
sessions and internal errors are silent, and an unreadable copy never hides a problem
in the record. Records without markers are copied but never reported for missing
markers. The check knows nothing about whether a statement is stale; keeping the current
state true remains the model's job.

## Verification boundary

Repository tests run the hook executables with realistic event payloads and check their
output contracts, root/task selection, opt-out, rejection behavior, and the post-edit
check. Installer tests use temporary homes. These prove local script behavior, not a
particular installed host's end-to-end delivery after context compaction.

To establish that installed behavior, use an authorized disposable task, write a
recognizable intent, correction and unfinished check into the current-state block,
trigger the host's real compaction or resume boundary, and inspect whether the next
model request receives and uses the block. For the post-edit check, damage the markers
with a tool call and observe whether the report reaches the model. Record host version,
event, selected record, and observed behavior. A fresh agent reading a generated hook
packet is a behavioral exercise, not that native lifecycle test.

For missing recovery, inspect selection with `resolve`, read with `read`, then check the
installed hook and host event/output contract. Do not compensate by adding a Stop hook,
heartbeat, or per-model-step injector. Hermes uses this package's manual path. Codex runs
plugin hooks only after the user trusts the current hook definition.

## Kimi Code

Kimi Code 0.41.0 ignores returned text from `SessionStart` and `PostCompact`, and its
documentation describes `PostToolUse` as an observational, fire-and-forget event. The
adapter therefore runs both the check and recovery on every user message, including after
resume: a check report, if any, precedes the recovery text in the same output. It does
not fire on non-user autonomous continuations; manual `check` reports the same facts. Kimi's own post-compaction journal pointer helps recover
conversation history but is not this Skill's state delivery. API compatibility does not
confer another client's hook lifecycle or return-value handling.

Use either the native `kimi.plugin.json` package or the user installer. Enabling both
registers duplicate hooks. The installer honors `KIMI_CODE_HOME` for both Skill files and
config; `~/.kimi` belongs to the legacy Python CLI.

Primary references, checked on 2026-09-06:
[Kimi hooks](https://www.kimi.com/code/docs/kimi-code-cli/customization/hooks.html),
[Skill discovery](https://www.kimi.com/code/docs/kimi-code-cli/customization/skills.html),
[environment variables](https://www.kimi.com/code/docs/kimi-code-cli/configuration/env-vars.html).

## Grok Build

Add Excellent Skill Marketplace, then install with
`grok plugin install task-state-with-files --trust`. The native manifest selects Grok's
camelCase `sessionId`; it never guesses from an inherited host identity. Use
`GROK_SESSION_ID` from the current Grok terminal-tool environment when activating a
selected record. Files alone remain inactive.

Grok discards SessionStart and PostCompact stdout. Those events reset a per-session
delivery marker in `GROK_PLUGIN_DATA`; the next PostToolUse runs the post-edit check and
delivers the selected record's current state once, with any check report before it.
Later PostToolUse calls run only the check.
SessionEnd clears that marker. There is no model call, polling, background service or
record rewrite. A turn without tools cannot receive PostToolUse context; invoke the
Skill's read command when needed.

On 2026-10-14, Grok 1.0.52 in the real user configuration recovered a bound marker
after native session/load and a changed marker after native compact_conversation. The
model reported each new marker from injected context without reading the note. That
observation predates the current-state block and the post-edit check; whether later
`PostToolUse` reports reach the model is not yet verified on a live host. The
`SessionStart` and `PostCompact` branches store a passing copy before any tool runs.
Primary contract: [Grok hooks](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/10-hooks.md).
