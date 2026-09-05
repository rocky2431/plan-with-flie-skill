# Task State with Files for Agent CLIs

A portable Agent Skill for carrying task understanding across long work, context
compaction, and agent handoffs. One working note connects the user's intent, what has
been learned and why, execution progress, and the next useful action.

## What the note preserves

- **Current understanding:** intended outcome, constraints and user corrections,
  established facts, assumptions, approach, step progress, and next action.
- **Judgments and corrections:** evidence-backed decisions, rejected approaches,
  feedback that changed the plan, and conditions for revisiting a conclusion.
- **Evidence and artifacts:** accessible files, source identifiers, commands and results,
  and the conditions under which a claim was verified.

For example, a retry that disproves an ordering assumption is progress even before code
changes. Record the observation and its effect on the approach. A code change awaiting
its required check remains in progress. These distinctions let the receiving agent
continue from supported conclusions and unfinished work.

The Skill calls for concise, verifiable judgment summaries. Update affected portions as
understanding changes; preserve uncertainty and important corrections. It does not ask
for private internal reasoning, transcripts, or a new summary of the entire task every turn.
See [the working-note examples](plugins/task-state-with-files/skills/task-state-with-files/references/working-notes.md).

## Start or resume a task

Resolve `<skill-dir>` from the loaded `SKILL.md` path exposed by the host:

```bash
python3 "<skill-dir>/scripts/task_state.py" init \
  --task example --objective "Ship the observable outcome"

python3 "<skill-dir>/scripts/task_state.py" read --task example

python3 "<skill-dir>/scripts/task_state.py" resolve --task example
```

`init --task` creates `.tasks/<task-id>.md` once. It never overwrites an existing record;
read an existing ID and confirm it identifies the same task. IDs contain 1–64 lowercase
letters, digits, or hyphens and start with a letter or digit. `read` returns the complete
record; `resolve` returns JSON location/status metadata only.

Fill the note from the actual request, then work in useful steps: read the current step
and its evidence, act and verify, update the affected understanding and progress, and
continue the authorized work. Checkpoint at meaningful changes, before handoff, and
before leaving unfinished work. The Skill leaves semantic judgment to the agent.

## Locations and selection

New tasks use `.tasks/<task-id>.md`. Keep the same record across sessions and agents.
Existing project notes can be read directly:

```bash
python3 "<skill-dir>/scripts/task_state.py" read --file docs/wip/example.md
```

Without `--root`, discovery walks from the current directory to the nearest task marker
or Git boundary, stopping at the user's home. A subdirectory can therefore recover its
parent task. `--root <project-directory>` pins an exact root, including when another
workspace is the intended source. Paths inside a task record are relative to its root.

Without a task/file selector, a legacy `work/task-state.md` or `work/task-state.ref`
takes precedence. Otherwise a single `.tasks/*.md` is selected. Multiple named records
return an ambiguity diagnostic; choose explicitly. A missing or invalid explicit
selection never falls back to another task.

Compatibility with earlier releases is retained:

```bash
python3 "<skill-dir>/scripts/task_state.py" init --objective "Legacy session task"
python3 "<skill-dir>/scripts/task_state.py" bind docs/wip/example.md
```

`init` without `--task` retains the legacy session-file behavior. `bind` writes one
relative path to `work/task-state.ref` and refuses a different existing binding or a
coexisting session file. Absolute paths, parent traversal, missing targets, and symlink
escapes are rejected. Explicit `--file` can still read an existing project record.

Archive completed named notes according to project convention, or move them to
`.tasks/archive/<task-id>.md`, outside active discovery. Archived notes remain available
with `read --file`. Remove disposable session files and bindings when no unfinished work
depends on them. Completion does not automatically promote task notes into global memory.

## Multiple tasks and handoffs

Select `--task` on each CLI call, or set `TASK_STATE_TASK=<task-id>` when launching a host
so its recovery hooks select that task. `TASK_STATE_ROOT` pins the workspace. These
variables affect `read`, `resolve`, and hooks; pass the ID explicitly to `init --task`.
Explicit CLI selectors override environment selection, and `--root` overrides the root
variable. A tool shell cannot change an already-running host's launch environment.

Each task has one writer; collaborating workers return evidence for the owning agent to
integrate. Do not rewrite a shared active binding to switch independent concurrent tasks.
An unrelated one-shot host invocation can use `TASK_STATE_DISABLED=1` to suppress recovery.

A handoff includes the task ID or relative record path, actual workspace, relevant
revision and uncommitted artifacts, and next action. Verify the receiver can access the
record and required evidence. Naming a task, writing a `.ref`, or creating a Git worktree
does not transfer files. Use the authorized transfer mechanism for uncommitted/ignored
records and artifacts; this package provides no automatic synchronization.

## Host recovery

| Host | Installation | Bundled recovery event | Context output |
|---|---|---|---|
| Codex | Marketplace Plugin | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| Claude Code | User Skill + Hook | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| ZCode | User Skill + Hook | `SessionStart(startup|resume|clear|compact)` | `additionalContext` |
| Kimi Code | Native plugin or user Skill + Hook | `UserPromptSubmit` | plain stdout in model context and UI |
| Hermes | User Skill | manual `read` | file content |

Adapters use the same discovery, selection, and renderer. A record fitting the 8,000
character context budget arrives intact. Larger records produce a **partial preview**
of whole sections with an explicit instruction to read the complete file. The preview
is not a semantic summary. Missing state is silent; ambiguity or invalid state returns
an advisory diagnostic. Hooks never block stopping or schedule another turn.

Tests exercise adapter subprocess contracts and recovery behavior. They do not establish
that every installed host version delivers state to its next model request after a real
compaction. See [host recovery](plugins/task-state-with-files/skills/task-state-with-files/references/host-recovery.md)
for the validation boundary.

## Install

The Codex Plugin bundles both Skill and recovery Hook:

```bash
codex plugin marketplace add rocky2431/plan-with-flie-skill
codex plugin add task-state-with-files@rocky-task-state
```

For development, replace the marketplace source with a local reviewed checkout, such as
`./plan-with-flie-skill`. Review and trust the bundled Hook when Codex asks.

For Kimi, ZCode, Claude Code, and Hermes, run from a reviewed checkout:

```bash
python3 scripts/install_user.py install --hosts kimi,zcode,claude,hermes
python3 scripts/install_user.py doctor --hosts kimi,zcode,claude,hermes
```

The installer copies the Skill into each host's native user directory and merges only
its managed hook entries. Existing Skill/config files are backed up under
`~/.local/state/task-state-with-files/backups/<timestamp>-install/` before mutation.
Restart the host after installation. Remove managed entries with:

```bash
python3 scripts/install_user.py uninstall --hosts kimi,zcode,claude,hermes
```

Uninstall also creates recovery copies. A standalone installation of
`plugins/task-state-with-files/skills/task-state-with-files` retains the workflow and CLI;
automatic lifecycle recovery requires a supported adapter. Hermes remains Skill-only.

## Development and background

The implementation uses the Python standard library. Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

CI runs this suite on Linux, macOS, and Windows. Non-Codex hook installation currently
targets the local POSIX CLI environment; Codex has a separate Windows hook command.

This independent implementation was informed by
[`OthmanAdi/planning-with-files`](https://github.com/OthmanAdi/planning-with-files).
The [architecture note](docs/architecture.md) describes how working notes and thin
recovery adapters fit together. There is no database, per-model-step injector, transcript
scraper, Stop gate, heartbeat, or automatic continuation loop.

Kimi Code 0.41.0 restores through `UserPromptSubmit` before the next user message,
not immediately after autonomous compaction. Returned text from `SessionStart` and
`PostCompact` does not enter model context. Installation honors `KIMI_CODE_HOME`,
defaulting to `~/.kimi-code`; legacy `~/.kimi` data is not migrated or deleted.
Choose the native plugin or user installer to avoid duplicate hooks.
