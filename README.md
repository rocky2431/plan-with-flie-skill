# Task State with Files

Task State with Files gives coding agents a durable working record for tasks that
outlive a context window or move to another agent. Each record has a short
current-state block (what is true now and what comes next) and an append-only
history (user words, decisions, corrections, evidence). Work can resume from the
project files instead of relying on chat history.

It runs as a portable Skill with Python scripts. Agents write the record with their
normal editing tools. Codex, Claude Code, Kimi Code, zCode and Grok Build can also load
small hooks that deliver the current-state block after a context boundary and check
the record after each edit, keeping the last three good copies. The hooks report; they never
block. Hermes uses the same Skill with manual reading. The host still provides the
model, tools, and execution; this package only locates, checks and restores task state.

Use it when losing the reasoning behind the current plan would make a task expensive
to reconstruct. A brief answer or one-step edit does not need a task record.

Version: 0.7.0. The implementation uses the Python standard library.

- [Install and start](#install-and-start)
- [Your first task](#your-first-task)
- [How it works](#how-it-works)
- [Files and task selection](#files-and-task-selection)
- [Recovery, checks and handoffs](#recovery-checks-and-handoffs)
- [Current limits](#current-limits)
- [Documentation](#documentation)
- [Development](#development)

## Install and start

You need a coding agent that can load Skills and run Python. Automatic recovery and
checks also require the host to load the package's hooks.

### Codex

```bash
codex plugin marketplace add rocky2431/plan-with-flie-skill
codex plugin add task-state-with-files@rocky-task-state
```

The plugin contains the Skill and the Codex `SessionStart` and `PostToolUse` hooks.
Reload plugins or start a new session after installation, then confirm that
`$task-state-with-files` is available. Review and trust the hooks when Codex asks;
Codex skips untrusted plugin hooks.

### Claude Code, Kimi Code, zCode, Grok Build, and Hermes

Claude Code and zCode install `task-state-with-files@rocky-task-state` from this
repository's native marketplace. Kimi Code installs `plugins/task-state-with-files`
through its plugin manager. Instructions, scripts, and hooks ship together and update
through that same manager. Codex selects `hooks/codex.json`; Claude Code and zCode
discover `hooks/hooks.json`; Kimi uses the hooks in `kimi.plugin.json`. Grok Build
installs the native plugin; see
[Grok recovery](plugins/task-state-with-files/skills/task-state-with-files/references/host-recovery.md#grok-build).

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
> operations team. Keep what is true now, what you learn, the evidence for important
> decisions, completed checks, and the next action as you work.

For a task named `2026-10-24-export-ready`, the agent creates
`tasks/2026-10-24-export-ready.md`, fills the current-state block from the actual
request, works in useful steps, verifies each result, and updates the block and
history when its understanding or progress changes.

The bundled CLI can create, read or check the same record directly. Resolve
`<skill-dir>` from the installed `SKILL.md` path:

```bash
python3 "<skill-dir>/scripts/task_state.py" init \
  --task 2026-10-24-export-ready --objective "Make the CSV export usable by operations"

python3 "<skill-dir>/scripts/task_state.py" read --task 2026-10-24-export-ready
python3 "<skill-dir>/scripts/task_state.py" check --task 2026-10-24-export-ready
python3 "<skill-dir>/scripts/task_state.py" resolve --task 2026-10-24-export-ready
```

`init` creates a record once and refuses to overwrite one that already exists.
`read` returns the complete Markdown record. `check` reports the record's facts.
`resolve` returns JSON location and selection metadata without the record's contents.

## How it works

1. The agent locates and reads the current task record before repeating earlier
   investigation.
2. It chooses a useful next result, does the work, and checks the relevant behavior.
3. It updates the current-state block and appends what happened to the history.
4. After compaction, resume, or handoff, the receiving agent gets the current-state
   block, checks it against the current workspace, reads the full record before
   changing direction, and continues the unfinished work.

| Part | What belongs there |
|---|---|
| Current-state block | Only what is true now: intended outcome, constraints and authority in force, progress, next action, open owner decisions |
| History | Appended entries: the user's exact words, decisions and rejected options, corrections with evidence, verification commands and results, handoffs |

The block is rewritten in place as facts change and stays short enough to be
delivered whole. History is never rewritten; it explains why the current state is
what it is. The record is not a transcript or a reconstruction of private reasoning.

The Skill leaves interpretation and replanning to the agent. Scripts handle only
facts and consequences: record creation, root discovery, path containment, task
selection, full reads, the post-edit check, the last good copy, and bounded recovery.

## Files and task selection

Named records live at `tasks/<task-id>.md`, normally `<YYYY-MM-DD>-<slug>`. IDs contain
1 to 64 lowercase letters, digits, or hyphens and start with a letter or digit. The
first record creates `tasks/` with a README marking it as managed by this Skill. If the
project already has its own `tasks/` folder, `init --task` refuses it; choose a path with
`init --file <relative-path>`. Legacy `.tasks/<task-id>.md` records are still resolved.

Without `--root`, discovery walks upward from the current directory to the nearest
task marker or Git boundary, stopping at the user's home. `--root <project-directory>`
or `TASK_STATE_ROOT` pins an exact workspace.

For deliberate CLI `read` / `resolve` / `check`, selection at the chosen root follows
this order:

1. An explicit `--task` or `--file`. With no CLI selector, use `TASK_STATE_TASK`
   or `TASK_STATE_FILE` from the launch environment; both together are invalid.
2. A legacy `work/task-state.md` file or `work/task-state.ref` binding.
3. The only record among managed `tasks/*.md` and legacy `.tasks/*.md`.

Several records require an explicit selector. An invalid explicit selection never
falls back to another task. Existing project notes can be read by relative path:

```bash
python3 "<skill-dir>/scripts/task_state.py" read --file docs/wip/export-ready.md
```

Bindings must stay inside the selected project. The resolver rejects absolute paths,
parent traversal, missing targets, and symlink escapes.

Move completed records to `tasks/archive/` or follow the project's own archive
convention. Borrowed inquiry and goal documents retain their own structure and
lifecycle; finish their state section without moving the entire document. Archived
records stay readable through `read --file` but are not selected automatically.

## Recovery, checks and handoffs

| Host | Installation | Recovery event | Post-edit check | Context output |
|---|---|---|---|---|
| Codex | Marketplace plugin | `SessionStart(startup\|resume\|clear\|compact)` | `PostToolUse` | `additionalContext` |
| Claude Code | Native plugin | `SessionStart(startup\|resume\|clear\|compact)` | `PostToolUse` | `additionalContext` |
| zCode | Native plugin | `SessionStart(startup\|resume\|clear\|compact)` | `PostToolUse` (unverified) | `additionalContext` |
| Kimi Code | Native plugin or user Skill and hook | `UserPromptSubmit` | Same `UserPromptSubmit` | Plain stdout |
| Grok Build | Native plugin | First `PostToolUse` after a boundary | Later `PostToolUse` (unverified) | `additionalContext` |
| Hermes | User Skill | Manual `read` | Manual `check` | Complete file content |

All adapters use the same resolver, check and renderer. A record with one current-state
block delivers a short header and that block; the header names the record path, says
the block is facts and navigation rather than instructions, and gives the full-read
command. A broken or oversized block delivers only the problem and the path. Records
without the block keep the earlier behavior: the whole note within 8,000 characters,
otherwise a labeled partial preview made from whole sections.

After each tool call (on Kimi, before each user message), the check compares the
selected record with the version it last saw. A changed record is checked for one
marker pair, a block within the delivery limit, and, in `tasks/` or legacy `.tasks/`
records, earlier history entries still present in order (blank lines, headings and
comments ignored). The last three passing versions are kept in `.task-state/snapshots/`.
A problem is reported once, with those copies; if the change was intended, later edits
are compared with it. Nothing is blocked.

Hooks need an explicit launch selection (`TASK_STATE_TASK` or `TASK_STATE_FILE`) or
this native session's saved selection. Existing files alone never activate hooks.
To select the record for a running session, use its actual native session ID:

```bash
python3 "<skill-dir>/scripts/task_state.py" activate \
  --task 2026-10-24-export-ready --session <native-session-id> --root <project-root>
python3 "<skill-dir>/scripts/task_state.py" deactivate \
  --session <native-session-id> --root <project-root>
```

Use `--file` for an existing business record. Selections and snapshots live in
`.task-state/`, which ignores its own contents; bindings from earlier versions under
`.tasks/.sessions/` are still honored. A new session selects its record again. When a
host cannot expose that identity, use the launch environment or manual `read`.
Changing a child shell's environment cannot change its already-running parent host.

Unselected hooks stay silent, including with ambiguous or invalid old files. Invalid
explicit selections return a bounded diagnostic without falling back. Set
`TASK_STATE_DISABLED=1` for an unrelated one-shot invocation that should not load
task state.

A useful handoff names the record's relative path, the actual workspace, the relevant
revision and uncommitted artifacts, and the next action. The receiver must be able to
access both the record and its evidence. A task ID, binding, or new Git worktree does
not transfer ignored or uncommitted files.

The Skill works without companion Skills. For a supplied result or specification,
read and preserve its acceptance IDs and meanings, boundaries, key corrections and
evidence before continuing. Reuse existing documents; a borrowed document wraps its
own current-state section in the same markers. If UltraGoal Carry-over already owns the
current execution state, maintain it instead of creating another record; UltraGoal
recovers its own goal. Use one writer for each record. Other agents return findings and
evidence for that writer to integrate after reading the latest version. See the shipped
[embedded examples](plugins/task-state-with-files/skills/task-state-with-files/references/working-notes.md#maintain-an-existing-document).

## Current limits

Recovery and checks are advisory. They do not start another turn, grant new authority,
check that the task is complete, or synchronize files between workspaces.

The check reports facts only. It cannot tell whether a statement in the current-state
block has become stale; keeping it true remains the agent's job.

Kimi Code restores state and reports check results on the next `UserPromptSubmit`;
its `SessionStart` and `PostCompact` output does not enter model context and its
`PostToolUse` is observational. Whether zCode and Grok deliver `PostToolUse` output to
the model is not yet verified on a real host.

The automated suite covers record selection, full reads, the check, snapshots, bounded
rendering, adapter subprocess contracts, and reversible installation. It does not prove
that every installed host version delivers state to the next model request after a real
compaction.

## Documentation

- [Architecture](docs/architecture.md): design principle, record format, discovery,
  recovery, the post-edit check, handoffs, installation, and validation boundaries.
- [Skill instructions](plugins/task-state-with-files/skills/task-state-with-files/SKILL.md):
  the procedure loaded by the agent.
- [Working-note guide](plugins/task-state-with-files/skills/task-state-with-files/references/working-notes.md):
  examples of useful current state and history.
- [Host recovery](plugins/task-state-with-files/skills/task-state-with-files/references/host-recovery.md):
  adapter behavior, host output limits, manual recovery, and lifecycle test boundaries.

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
