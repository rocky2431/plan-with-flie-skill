# Task State with Files

Task State with Files gives coding agents a durable working note for tasks that
outlive a context window or move to another agent. The note keeps the intended
outcome, current understanding, evidence, decisions, corrections, completed work,
and the next useful action together. Work can resume from the project files instead
of relying on chat history.

It runs as a portable Skill with Python scripts. Codex, Claude Code, Kimi Code,
and zCode can also load a small recovery hook that returns an existing note to the
agent. Hermes uses the same Skill with manual recovery. The host still provides the
model, tools, and execution; this package only maintains and restores task state.

Use it when losing the reasoning behind the current plan would make a task expensive
to reconstruct. A brief answer or one-step edit does not need a task record.

Version: 0.6.0. The implementation uses the Python standard library.

Grok Build has a native plugin adapter: its first tool result after startup, resume
or compaction carries the explicitly selected record. See
[Grok recovery](plugins/task-state-with-files/skills/task-state-with-files/references/host-recovery.md#grok-build)
for installation and the observed native lifecycle checks.

- [Install and start](#install-and-start)
- [Your first task](#your-first-task)
- [How it works](#how-it-works)
- [Files and task selection](#files-and-task-selection)
- [Recovery and handoffs](#recovery-and-handoffs)
- [Current limits](#current-limits)
- [Documentation](#documentation)
- [Development](#development)

## Install and start

You need a coding agent that can load Skills and run Python. Automatic recovery
also requires the host to load the package's hook.

### Codex

```bash
codex plugin marketplace add rocky2431/plan-with-flie-skill
codex plugin add task-state-with-files@rocky-task-state
```

The plugin contains the Skill and Codex `SessionStart` hook. Reload plugins or
start a new session after installation, then confirm that `$task-state-with-files`
is available. Review and trust the hook when Codex asks.

### Claude Code, Kimi Code, zCode, and Hermes

Claude Code and zCode install `task-state-with-files@rocky-task-state` from this
repository's native marketplace. Kimi Code installs `plugins/task-state-with-files`
through its plugin manager. Instructions, scripts, and recovery hooks ship together
and update through that same manager. Codex selects `hooks/codex.json`; Claude Code
and zCode discover `hooks/hooks.json`; Kimi uses the hook in `kimi.plugin.json`.

For Hermes, use the portable installer:

```bash
python3 scripts/install_user.py install --hosts hermes
python3 scripts/install_user.py doctor --hosts hermes
```

The installer backs up existing files before replacement. It refuses a second user
Skill when the selected host already owns this plugin. Portable-only installations
on older hosts remain available through explicit `--hosts` selection.

To migrate an old user installation, remove its Skill and managed hooks with the
uninstaller, then install through the host's plugin manager:

```bash
python3 scripts/install_user.py uninstall --hosts kimi,zcode,claude
```

Uninstall creates recovery copies and preserves unrelated hook entries. Start a new
session after migration. Hermes has no lifecycle hook and reads task state on demand.

## Your first task

Open your coding agent in the project where the work will happen. Ask it to use the
Skill in plain language, or use the native Skill entry when the host provides one:

> Use Task State with Files for this work. Make the CSV export usable by our
> operations team. Preserve the intended outcome, what you learn, the evidence for
> important decisions, completed checks, and the next action as you work.

For a task named `export-ready`, the agent creates `.tasks/export-ready.md`. It
fills the note from the actual request, works in useful steps, verifies each result,
and updates the affected parts of the note when its understanding or progress changes.

The bundled CLI can create or read the same record directly. Resolve `<skill-dir>`
from the installed `SKILL.md` path:

```bash
python3 "<skill-dir>/scripts/task_state.py" init \
  --task export-ready --objective "Make the CSV export usable by operations"

python3 "<skill-dir>/scripts/task_state.py" read --task export-ready
python3 "<skill-dir>/scripts/task_state.py" resolve --task export-ready
```

`init` creates a record once and refuses to overwrite one that already exists.
`read` returns the complete Markdown note. `resolve` returns JSON location and
selection metadata without restoring the note's contents.

## How it works

1. The agent locates and reads the current task record before repeating earlier
   investigation.
2. It chooses a useful next result, does the work, and checks the relevant behavior.
3. It updates the facts, affected judgment, step status, evidence, and next action.
4. After compaction, resume, or handoff, the receiving agent reads the same record,
   checks it against the current workspace, and continues the unfinished work.

One note connects three kinds of information:

| Section | What belongs there |
|---|---|
| Current understanding | Intended outcome, constraints, established facts, assumptions, progress, open questions, and next action |
| Judgments and corrections | Decisions supported by evidence, rejected approaches, user corrections, and conditions for revisiting a conclusion |
| Evidence and artifacts | Relevant files, exact identifiers, commands and observed results, revisions, and verification conditions |

The record contains concise, verifiable summaries. It is not a transcript or a
reconstruction of private internal reasoning. An observation that rules out a bad
approach counts as progress. A code change awaiting its required check remains in
progress.

The Skill leaves interpretation and replanning to the agent. Scripts handle the
mechanical parts: record creation, root discovery, path containment, task selection,
full reads, and bounded recovery output.

## Files and task selection

Named records live at `.tasks/<task-id>.md`. Keep the same ID across sessions and
agents. IDs contain 1 to 64 lowercase letters, digits, or hyphens and start with a
letter or digit.

Without `--root`, discovery walks upward from the current directory to the nearest
task marker or Git boundary, stopping at the user's home. This lets work started in a
subdirectory find the project record. `--root <project-directory>` or
`TASK_STATE_ROOT` pins an exact workspace.

For deliberate CLI `read` / `resolve`, selection at the chosen root follows this order:

1. An explicit `--task` or `--file`. With no CLI selector, use `TASK_STATE_TASK`
   or `TASK_STATE_FILE` from the launch environment; both together are invalid.
2. A legacy `work/task-state.md` file or `work/task-state.ref` binding.
3. The only active `.tasks/*.md` record.

Several active named records require an explicit selector. An invalid explicit
selection never falls back to another task. Existing project notes can be read by
relative path:

```bash
python3 "<skill-dir>/scripts/task_state.py" read \
  --file docs/wip/export-ready.md
```

Legacy session records and bindings remain supported:

```bash
python3 "<skill-dir>/scripts/task_state.py" init \
  --objective "Legacy session task"
python3 "<skill-dir>/scripts/task_state.py" bind docs/wip/export-ready.md
```

Bindings must stay inside the selected project. The resolver rejects absolute paths,
parent traversal, missing targets, and symlink escapes.

Move completed Skill-created `.tasks/<task-id>.md` records to `.tasks/archive/<task-id>.md`
or follow the project's own archive convention. Borrowed inquiry and goal documents
retain their own structure and lifecycle; finish their state section without moving
the entire document into the task archive. Archived records stay readable through `read --file` but are
not selected automatically. Remove disposable session files and bindings only after
no unfinished work depends on them.

## Recovery and handoffs

| Host | Installation | Recovery event | Context output |
|---|---|---|---|
| Codex | Marketplace plugin | `SessionStart(startup\|resume\|clear\|compact)` | `additionalContext` |
| Claude Code | Native plugin | `SessionStart(startup\|resume\|clear\|compact)` | `additionalContext` |
| zCode | Native plugin | `SessionStart(startup\|resume\|clear\|compact)` | `additionalContext` |
| Kimi Code | Native plugin or user Skill and hook | `UserPromptSubmit` | Plain stdout in model context and UI |
| Hermes | User Skill | Manual `read` | Complete file content |

All adapters use the same resolver and renderer. If the header and record fit within
the 8,000-character recovery budget, the agent receives the complete note. Larger
records produce a labeled partial preview made from whole sections, followed by an
instruction to read the complete file. The preview is mechanical selection, not a
semantic summary.

Hooks need an explicit launch selection (`TASK_STATE_TASK` or `TASK_STATE_FILE`) or
this native session's saved selection. Existing files alone never activate recovery.
To select the record for a running session, use its actual native session ID:

```bash
python3 "<skill-dir>/scripts/task_state.py" activate \
  --task export-ready --session <native-session-id> --root <project-root>
python3 "<skill-dir>/scripts/task_state.py" deactivate \
  --session <native-session-id> --root <project-root>
```

Use `--file` for an existing business record. The per-session reference lives in
`.tasks/.sessions/`; keep it out of commits. A new session selects its record again.
When a host cannot expose that identity, use the launch environment or manual `read`.
Changing a child shell's environment cannot change its already-running parent host.

Unselected hooks stay silent, including with ambiguous or invalid old files. Invalid
explicit selections return a bounded diagnostic without falling back. This replaces
the pre-0.4 implicit single-file hook recovery; manual discovery remains compatible.
Set `TASK_STATE_DISABLED=1` for an unrelated one-shot invocation that should not load
task state.

A useful handoff names the task ID or relative record path, the actual workspace, the
relevant revision and uncommitted artifacts, and the next action. The receiver must be
able to access both the note and its evidence. A task ID, binding, or new Git worktree
does not transfer ignored or uncommitted files.

The Skill works without companion Skills. For a supplied result/specification,
read and preserve its acceptance IDs and meanings, boundaries, key corrections and
evidence before continuing. Reuse existing business documents; for new deliverables,
follow the project's `docs/` or `documents/` convention, defaulting to
`documents/<work-id>/` only when none exists. `.tasks/` records remain supported.
If UltraGoal Carry-over already owns the current execution state, read it instead of
creating another note; if a Task note owns it, Carry-over points there. Accepted goal
terms remain in the goal contract.

Keep the explicitly selected record, then reuse a fitting existing document or section,
then use the standalone default. Arming a goal does not transfer state ownership.
Maintain an inquiry's Current position or a goal's Carry-over without adding a parallel
ledger. Choose one recovery provider for the same task through existing session bindings;
state location does not choose it. See the shipped [embedded examples](plugins/task-state-with-files/skills/task-state-with-files/references/working-notes.md#maintain-an-existing-document).

Use one writer for each task note. Other agents can return findings and evidence for
that writer to integrate after reading the latest record.

## Current limits

Recovery is advisory. It does not start another turn, grant new authority, check that
the task is complete, or synchronize files between workspaces.

Kimi Code restores state on the next `UserPromptSubmit`. Its `SessionStart` and
`PostCompact` output does not enter model context, so autonomous compaction does not
cause immediate recovery. A manual `read` remains available.

The automated suite covers record selection, full reads, bounded previews, adapter
subprocess contracts, and reversible installation. It does not prove that every
installed host version will deliver state to the next model request after a real
compaction.

Active notes are edited in place and completed notes can be archived. The package does
not automatically segment a note's history or index a large collection of tasks, so
very long records still need deliberate maintenance.

## Documentation

- [Architecture](docs/architecture.md): record ownership, discovery, recovery,
  handoffs, installation, and validation boundaries.
- [Skill instructions](plugins/task-state-with-files/skills/task-state-with-files/SKILL.md):
  the procedure loaded by the agent.
- [Working-note guide](plugins/task-state-with-files/skills/task-state-with-files/references/working-notes.md):
  examples and guidance for preserving useful evidence and decisions.
- [Host recovery](plugins/task-state-with-files/skills/task-state-with-files/references/host-recovery.md):
  adapter behavior, manual recovery, and lifecycle test boundaries.

## Development

Run the test suite from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

CI runs the suite on Linux, macOS, and Windows. Non-Codex hook installation targets
local POSIX CLI environments; Codex has a separate Windows hook command.

This project is an independent implementation informed by
[`OthmanAdi/planning-with-files`](https://github.com/OthmanAdi/planning-with-files).

## License

[MIT](LICENSE).
