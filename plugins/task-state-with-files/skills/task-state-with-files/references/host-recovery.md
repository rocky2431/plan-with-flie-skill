# Host Recovery

The Skill workflow is portable. Lifecycle recovery is host-specific and must use the
smallest native surface that actually reaches the next model request.

| Host | User Skill location | Recovery boundary | Output contract |
|---|---|---|---|
| Codex | Installed Plugin Skill | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| Claude Code | `~/.claude/skills/task-state-with-files` | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| ZCode | `~/.zcode/skills/task-state-with-files` | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| Kimi Code | `$KIMI_CODE_HOME/skills/task-state-with-files` (default `~/.kimi-code`) | `UserPromptSubmit` | plain stdout appended to context and UI |
| Hermes | `~/.hermes/skills/task-state-with-files` | Skill-only | manual file recovery |

Hermes exposes dynamic context injection through `pre_llm_call`, but that is a per-turn
surface rather than a dedicated post-compaction event. This package deliberately does
not add continuous injection merely to make the feature matrix look uniform. The state
file remains available, and the Skill tells Hermes how to recover it manually.

All adapters are advisory and fail open. Missing state is silent. Invalid state returns
a bounded diagnostic. Never add a `Stop` hook, heartbeat, goal loop, or incomplete-plan
continuation to compensate for a host difference.

`TASK_STATE_DISABLED=1` makes every bundled lifecycle adapter silent for an unrelated
one-shot invocation.

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
