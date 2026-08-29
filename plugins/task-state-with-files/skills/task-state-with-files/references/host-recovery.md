# Host Recovery

The Skill workflow is portable. Lifecycle recovery is host-specific and must use the
smallest native surface that actually reaches the next model request.

| Host | User Skill location | Recovery boundary | Output contract |
|---|---|---|---|
| Codex | Installed Plugin Skill | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| Claude Code | `~/.claude/skills/task-state-with-files` | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| ZCode | `~/.zcode/skills/task-state-with-files` | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| Kimi Code | `~/.kimi/skills/task-state-with-files` | `SessionStart(startup|resume)` and `PostCompact` | plain stdout context |
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
