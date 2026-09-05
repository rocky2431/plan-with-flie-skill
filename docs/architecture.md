# Architecture

The package gives an agent a durable working record and a way to find and read it.
Semantic understanding, judgment, reflection, and replanning belong to the agent.
Discovery, containment, file selection, and bounded recovery are mechanical concerns.

## The continuity record

One task has one canonical note with three connected parts: current understanding,
judgments and corrections, and evidence and artifacts. It records both changes in
understanding and changes in the work product. The current view is updated locally;
significant reversals retain a short evidence-backed explanation. Observations,
hypotheses, decisions, verified progress, and unfinished work remain distinguishable.

The note is task data, not a private reasoning transcript or another authority source.
The latest user request and live artifacts can invalidate old assumptions. Recovery
should identify what changed and revisit dependent work while retaining conclusions
whose supporting premises still hold.

The Skill provides a short execution rhythm: select a meaningful next result, act and
observe, verify at the relevant boundary, update affected parts, and continue within
the user's request. It uses descriptive step states without a workflow engine. It
checkpoints at meaningful learning/progress changes and before interrupted work needs
to be resumed; no tool-count quota determines semantic progress.

## Code and ownership

- `SKILL.md`, its template, and working-note examples define the agent workflow.
- `task_state.py` creates, binds, locates, and reads records. It never writes a judgment
  or marks a task complete. Existing records are not overwritten by initialization.
- `task_state_runtime.py` owns root discovery, explicit selection, containment, and
  rendering. Both the CLI and host adapters use it.
- The Codex Plugin and cross-host lifecycle script adapt native event/output contracts.
  They read existing state and return advisory context without creating task content.
- The user installer handles reversible placement and configuration for supported hosts.
  Installation backups are recovery copies, not task state.

## Task identity and discovery

Named tasks live at `.tasks/<task-id>.md`. A stable ID allows several tasks in a repository
without repeatedly overwriting one shared selector. A session change does not create a
new task identity. Completed named notes move outside active discovery, normally into
`.tasks/archive/`, and remain readable with an explicit relative file path.

An explicit `--root` (or `TASK_STATE_ROOT`) pins the exact workspace. Otherwise discovery
walks ancestors from the current directory, stopping at the first task marker
(`work/task-state.md`, `work/task-state.ref`, or `.tasks`), Git boundary, or user home.
A `.git` file is also a boundary. If no marker is found, the starting directory remains
the root. The resolver never searches neighboring repositories or other worktrees.

Selection order at that root is:

1. An explicit task ID or relative file. `read`/`resolve` also accept a task ID from
   `TASK_STATE_TASK` when no CLI selector is supplied. An invalid selection has no fallback.
2. A legacy direct state file or relative `.ref` binding, preserving existing installations.
   Both legacy sources together are invalid.
3. One `.tasks/*.md` file. Multiple files produce an ambiguity result listing candidates;
   modification time does not decide which task owns the current request.

The resolver rejects absolute bindings, traversal, missing/non-file targets, and symlink
escapes. Resolved absolute paths are internal containment evidence; record identities
and artifact references stay relative. An explicit root locator belongs in the handoff
or invocation rather than being hardcoded into a portable task note.

`resolve` returns JSON metadata for inspection. `read` returns the complete selected
UTF-8 file and is the manual recovery path. This keeps the existing metadata interface
compatible while making recovery an actual content read.

## Recovery and context limits

Codex, Claude Code, and ZCode use `SessionStart(startup|resume|clear|compact)`. Kimi uses
`UserPromptSubmit` to inject state before user-origin requests. Its `SessionStart` and
`PostCompact` return values do not enter model context, so autonomous compaction does
not trigger immediate injection. Hermes receives the portable Skill and
uses manual reading. All bundled adapters delegate to the same resolver and renderer.

If the header and complete record fit within 8,000 characters, the original record is
included without per-section shortening. Otherwise the output is prominently labeled
as a partial preview and directs the agent to read the full file before deciding what
to do. It prioritizes current understanding and legacy next-action/not-done sections,
including only whole sections that fit. An oversized section is omitted in full. This
is mechanical selection, not a claim that the omitted information is unimportant.

Missing state produces no context. Invalid or ambiguous state produces a bounded
advisory diagnostic. Each recovery message labels task content as working data, requires
reconciliation with the current workspace, and denies it independent authority for
continuation or external effects. `TASK_STATE_DISABLED=1` suppresses adapter output.

## Handoffs and concurrent work

A receiver needs the task identity, accessible workspace and record, relevant artifacts
and revision, and the next unresolved action. Relative paths help portability but cannot
transfer files. Ignored or uncommitted state must be carried using an authorized handoff
mechanism. A `.ref` and a new worktree alone cannot satisfy this requirement.

Use one writer per task note. Workers return bounded findings and evidence for that
writer to integrate after reading the latest version. Independent tasks use explicit
selectors or host-launch environment pins. A shell tool cannot retroactively change its
parent host's environment. There is no hidden global task registry or automatic note merge.

## Installation and validation

Each non-Codex host gets an independent copy of the Skill. Kimi configuration uses a
marker-delimited managed TOML block; Claude Code and ZCode use managed SessionStart hook
groups. The installer retains foreign entries, stages replacement writes, and backs up
existing files. `doctor` compares the installed Skill tree and expected managed hooks.

The test suite covers legacy compatibility, named tasks, root boundaries, full reads,
bounded previews, subprocess hook contracts, and reversible installation in temporary
homes. Fresh-context behavioral exercises can test whether a receiver uses a record
correctly, but they do not substitute for a real installed-host compaction/resume run.

The package has no Stop hook, heartbeat, semantic completion gate, transcript scraping,
or automatic continuation. A state file supports task execution; successful recovery
and a completed checklist do not themselves establish the user's outcome.
