# Task State with Files for Agent CLIs

A portable Agent Skill that keeps substantive task progress in an owner-readable file
below the current task directory. Native, non-blocking recovery adapters are provided
where a host exposes a lifecycle event that can reach the next model request.

The package intentionally has no `Stop` Hook, goal loop, heartbeat, semantic
completion gate or automatic continuation. Kimi recovery runs on user messages.

## Host support

| Host | Installation | Automatic recovery |
|---|---|---|
| Codex | Marketplace Plugin | `SessionStart(startup|resume|clear|compact)` |
| Claude Code | User Skill + user Hook | `SessionStart(startup|resume|clear|compact)` |
| ZCode | User Skill + user Hook | `SessionStart(startup|resume|clear|compact)` |
| Kimi Code | Native plugin or user Skill + Hook | `UserPromptSubmit`, before the next user-origin request |
| Hermes | User Skill | manual file recovery |

Hermes deliberately remains Skill-only. Its dynamic context hook is `pre_llm_call`, a
per-turn surface rather than a dedicated post-compaction recovery event. Installing a
continuous injector merely for feature parity would add recurring context cost and
would violate this package's narrow recovery boundary.

Kimi Code 0.41.0 executes `SessionStart` and `PostCompact` scripts but discards
returned recovery text. This package uses `UserPromptSubmit` to inject the latest
bounded state (up to 8,000 characters) whenever the user sends a message. The text
also appears in Kimi's UI. It does not restore immediately after autonomous
compaction without a new user message. Native journal recovery is separate.
See [Kimi's hook contract](https://www.kimi.com/code/docs/kimi-code-cli/customization/hooks.html).
OpenAI/Anthropic API compatibility does not imply identical client hook behavior.

## State locations

Session-scoped state is stored at `work/task-state.md`, relative to the event `cwd`.
Repository-shared WIP may live at an established project path such as
`docs/wip/<slug>.md`; `work/task-state.ref` then contains only that relative path.

Absolute bindings, parent traversal, symlink escape, dual state sources, and missing
shared targets fail closed. Canonical absolute paths are used only inside the resolver
to prove containment and are never written into task state or injected into model
context.

## Install Codex

The Codex Plugin includes both the Skill and its recovery Hook:

```bash
codex plugin marketplace add rocky2431/plan-with-flie-skill
codex plugin add task-state-with-files@rocky-task-state
```

Review and trust the bundled Hook when Codex asks. For local development, add the
repository checkout instead:

```bash
codex plugin marketplace add ./plan-with-flie-skill
codex plugin add task-state-with-files@rocky-task-state
```

## Install Kimi, ZCode, Claude Code, and Hermes

Run the user-scope installer from a reviewed checkout:

```bash
python3 scripts/install_user.py install \
  --hosts kimi,zcode,claude,hermes

python3 scripts/install_user.py doctor \
  --hosts kimi,zcode,claude,hermes
```

The installer copies the same standard Skill into each host's native user directory.
It merges one managed recovery entry into Kimi, ZCode, and Claude Code without
replacing unrelated configuration. Existing Skill copies and configuration files are
copied to `~/.local/state/task-state-with-files/backups/<timestamp>-install/` before
mutation. No login, model, provider, MCP, or credential setting is changed.

Kimi uses `$KIMI_CODE_HOME/skills` and `$KIMI_CODE_HOME/config.toml`, defaulting to
`~/.kimi-code`. Reinstalling replaces this package's legacy `SessionStart` and
`PostCompact` block at the selected root with one `UserPromptSubmit` hook. The old
Python `kimi-cli` directory `~/.kimi` is not migrated or deleted by this installer.
Choose the native plugin or the user installer, not both, to avoid duplicate hooks.

Restart each CLI after installation. Remove only this package's managed entries with:

```bash
python3 scripts/install_user.py uninstall \
  --hosts kimi,zcode,claude,hermes
```

Uninstall also creates recovery copies before removing the managed Skill directories.

## Skill-only use

The directory
`plugins/task-state-with-files/skills/task-state-with-files` is a valid standalone
Agent Skill. A Skill-only install retains the workflow and CLI but has no automatic
lifecycle recovery unless the current host adapter is installed.

## Task-state CLI

Resolve `<skill-dir>` from the loaded `SKILL.md` path exposed by the host:

```bash
python3 "<skill-dir>/scripts/task_state.py" init \
  --objective "Ship the observable outcome" --root .

python3 "<skill-dir>/scripts/task_state.py" bind \
  docs/wip/example.md --root .

python3 "<skill-dir>/scripts/task_state.py" resolve --root .
```

`init` is idempotent. `bind` refuses to replace a different binding or coexist with a
session-local state file.

## One-shot and concurrent sessions

An unrelated one-shot command may deliberately ignore active state in the same
directory by setting `TASK_STATE_DISABLED=1` for that invocation.

The locality key is the current `cwd`, not a hidden global session registry. Two
independent tasks must therefore use separate task directories or Git worktrees.
Sessions may share a bound WIP file only when they are collaborating on the same task.

## Design choices

This project was informed by
[`OthmanAdi/planning-with-files`](https://github.com/OthmanAdi/planning-with-files),
including its recovery, path-containment, parallel-task, opt-out, and
install-verification work. It is an independent, host-adapted implementation rather
than a vendored copy.

See [the architecture note](docs/architecture.md) for the detailed boundaries and
[the Skill's host reference](plugins/task-state-with-files/skills/task-state-with-files/references/host-recovery.md)
for exact lifecycle behavior.

## Development

The implementation uses only the Python standard library.

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

CI runs the same suite on Linux, macOS, and Windows. The current cross-host Hook
commands are installed for the local POSIX CLI environment; Codex retains its separate
Windows hook command.

For the native Kimi transport smoke (requires `kimi` on PATH):

```bash
python3 tests/probe_kimi_recovery.py
```

The probe uses an isolated Kimi home and a local stub model endpoint. It checks
that recovery reaches the actual host model request; it does not test model
judgment or unattended post-compaction execution.
