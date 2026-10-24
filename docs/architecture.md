# Architecture

The package gives an agent a durable working record and a way to find, check and
recover it. Meaning belongs to the agent: what is true, what to record, what to do
next. The package handles only facts and consequences: discovery, containment, file
selection, a post-edit fact check, a last good copy, and bounded recovery. It reports
and never blocks.

## Design principle

Machines handle facts and consequences and only report; the model keeps meaning,
wording and route. Nothing is blocked except irreversible effects, and damage is made
recoverable instead of prevented. This follows two observed failures:

- An agent rewrote a task record eight times with generated string-replacement scripts
  without re-reading it. Stale and duplicated statements accumulated, one empty-string
  replacement inserted a paragraph 7,577 times, nobody noticed for two hours, and no
  copy existed to restore.
- Harnesses that made one mechanical tool the only path, or that re-injected a stale
  recovery instruction, stopped work or drove it in loops while reporting consistent
  internal state.

The package therefore adds no write command for records, no size rejection, no version
token and no required entry types. Agents keep editing markdown with their normal tools.
The check observes, the snapshot restores, and recovery delivers a small block.

## The continuity record

One task has one record with two parts:

- A **current-state block** between `<!-- current-state -->` and `<!-- /current-state -->`:
  only what is true now and steers the next action. It is rewritten in place as facts
  change and kept short enough to be delivered whole.
- **History** after the block: appended entries for user words, decisions, corrections,
  evidence and handoffs. Earlier entries are not rewritten; they describe the past, not
  standing rules.

Separating the two keeps the delivered state small and current while preserving why it
changed. Field names inside the block are free; nothing depends on headings or language.
A borrowed document (for example a Deep Thinking `THOUGHTS.md`) wraps its own
current-state section in the same markers and keeps its structure.

The record is task data, not a private reasoning transcript or another authority
source. The latest user request and live artifacts can invalidate it. Recovery should
identify what changed and revisit dependent work while retaining conclusions whose
premises still hold.

## Code and ownership

- `SKILL.md`, its template, and working-note examples define the agent workflow.
- `task_state.py` creates, binds, locates, reads and checks records. It never writes a
  judgment, edits a record's content or marks a task complete. Initialization never
  overwrites.
- `task_state_runtime.py` owns root discovery, explicit selection, containment, the
  fact check, snapshots and rendering. The CLI and every host adapter use it.
- The Codex hook scripts and the cross-host lifecycle script adapt native event and
  output contracts. They return advisory context and never create task content.
- The user installer handles reversible placement and configuration for supported hosts.
  Installation backups are recovery copies, not task state.

## Task identity and discovery

Named tasks live at `tasks/<task-id>.md`, normally `<YYYY-MM-DD>-<slug>`. Creating the
folder writes `tasks/README.md` with the line `<!-- managed-by: task-state-with-files -->`.
A `tasks/` folder without that line belongs to the project, so `init --task` refuses it
and the agent supplies `--file`. `init --file` creates a record at an explicit path.
Legacy `.tasks/<task-id>.md` records are still resolved when `tasks/<task-id>.md` does
not exist. Completed records move to `tasks/archive/` and remain readable with `--file`.

An explicit `--root` (or `TASK_STATE_ROOT`) pins the exact workspace. Otherwise discovery
walks ancestors from the current directory, stopping at the first task marker
(`work/task-state.md`, `work/task-state.ref`, `.tasks`, `.task-state`), Git boundary, or
user home. A `.git` file is also a boundary. `tasks/` is deliberately not a marker
because projects often have their own folder of that name. If no marker is found, the
starting directory remains the root. The resolver never searches neighboring
repositories or other worktrees.

Deliberate CLI `read` / `resolve` / `check` selection order at that root is:

1. An explicit task ID or relative file, or `TASK_STATE_TASK` / `TASK_STATE_FILE` when
   no CLI selector is supplied. An invalid selection has no fallback.
2. A legacy direct state file or relative `.ref` binding. Both together are invalid.
3. One record among managed `tasks/*.md` (excluding `README.md`) and legacy
   `.tasks/*.md`. Several produce an ambiguity result listing candidates; modification
   time does not decide which task owns the current request.

The resolver rejects absolute bindings, traversal, missing/non-file targets, and symlink
escapes. Resolved absolute paths are internal containment evidence; record identities
and artifact references stay relative.

## Recovery and context limits

Codex, Claude Code, and ZCode use `SessionStart(startup|resume|clear|compact)`. Kimi uses
`UserPromptSubmit`, because its `SessionStart` and `PostCompact` return values do not
enter model context. Grok discards SessionStart output, so its adapter delivers once on
the next `PostToolUse` after startup, resume or compaction. Hermes uses manual reading.

A record with one well-formed block delivers a header and the block. The block is
limited to `CURRENT_STATE_LIMIT` characters so that the whole delivery stays far below
the 10,000-character hook caps of Claude Code and Grok; this package's Codex
`SessionStart` handler sets `additionalContextLimit` to 8,000 tokens, which normal prose
at that size stays within. The path appears once in the header and never displaces a
valid block. A broken or oversized block delivers only the problem and the path.
A legacy record without markers keeps the earlier behavior: whole within 8,000
characters, otherwise a labeled preview of whole sections.

Each delivery labels the content as facts and navigation, requires reconciliation with
the current workspace, names the full-read command, and denies it authority for
continuation or external effects. `TASK_STATE_DISABLED=1` suppresses adapter output.

## Post-edit check and last good copy

After each tool call (on Kimi, before each user message, because Kimi's `PostToolUse`
is observational) the adapters compare the selected record with the version they last
saw. Equal versions produce no writes and no output. A changed record is checked for
three facts: one marker pair outside code fences, a block within the limit, and, for
records under `tasks/` or `.tasks/`, earlier History entries still present in order,
ignoring blank lines, headings and comments.

Two kinds of state are kept apart in `.task-state/snapshots/`. The last-seen version is
the comparison base; it advances when a hook passes or reports a version, so an intended
change is reported at most once and never turns every later edit into a report. The last
three passing versions are the restore copies; a failing version never replaces them, and
rotation means a quiet damaging pass cannot overwrite the only earlier copy: the
pre-damage copy survives that edit and at least one more passing edit. Recovery stores a
passing copy before the first tool runs, but never advances the base past a problem it
cannot report, so damage made outside hooked tool calls is reported by the next check.
Reports are emitted once per distinct state through an exclusive file creation, so
parallel hooks do not duplicate them, and a persisting problem (broken markers, a block
that stays oversize) is identified by its kind and not repeated on every edit. An
unreadable copy is treated as missing and never hides a problem in the record.

The check never blocks, edits, or interprets meaning. Whether a statement is stale is a
semantic question it cannot answer. `task_state.py check` compares the record with the
newest passing copy, reports every current problem, and changes nothing unless it passes.

## Selection and runtime state

Hooks require a launch selection or this native session's explicit binding at
`.task-state/sessions/<session-hash>.ref`, created by `activate` and removed by
`deactivate`. Bindings under the earlier `.tasks/.sessions/` path are still honored.
`.task-state/` holds only local runtime state (bindings and snapshots), contains a
`.gitignore` of `*`, and is never committed. Launch selectors override a binding; task
plus file is invalid. Hooks never use legacy or unique-record discovery without a
selection, and unselected hooks are silent even when old files are ambiguous.

## Handoffs and concurrent work

A receiver needs the task identity, accessible workspace and record, relevant artifacts
and revision, and the next unresolved action. Relative paths help portability but cannot
transfer files. Uncommitted state must be carried using an authorized handoff
mechanism; a `.ref` and a new worktree alone cannot satisfy this requirement.

Use one writer per record. Workers return bounded findings and evidence for that writer
to integrate after reading the latest version. Independent tasks use explicit selectors
or host-launch environment pins. There is no hidden global task registry or automatic
record merge.

## Installation and validation

Each non-Codex host gets an independent copy of the Skill. Kimi configuration uses a
marker-delimited managed TOML block with one `UserPromptSubmit` hook; Claude Code and
ZCode use managed SessionStart and PostToolUse hook groups. The installer retains foreign entries, stages replacement
writes, and backs up existing files. `doctor` compares the installed Skill tree and
expected managed hooks.

The test suite covers legacy compatibility, named tasks, folder ownership, root
boundaries, full reads, the fact check, snapshots, bounded rendering, subprocess hook
contracts, and reversible installation in temporary homes. Fresh-context behavioral
exercises can test whether a receiver uses a record correctly, but they do not
substitute for a real installed-host compaction/resume run.

The package has no Stop hook, heartbeat, semantic completion gate, transcript scraping,
or automatic continuation. A record supports task execution; successful recovery and a
completed checklist do not themselves establish the user's outcome.
