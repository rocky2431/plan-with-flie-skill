---
name: task-state-with-files
description: "Keep the settled understanding of long work (confirmed intent, conclusions with their evidence, completed work, next step) in an owner-readable page that survives context compaction, new sessions and agent handoffs, so work resumes without re-deriving it or repeating what is done. Use for research, development, diagnosis or planning that may outlast one context window, and whenever a hook reports that a compacted session has no task page. Skip brief answers and simple edits completed in one turn."
license: MIT
---

# Task State With Files

Compaction summarizes the conversation, and every later compaction summarizes the
summary. What erodes first is what continuing needs most: the interpretation you and
the user settled on, the evidence behind each conclusion, and what is already done.
Keep those on a page outside the conversation, so that after a compaction, a new
session or a handoff the work resumes from the page instead of being understood again.

The conversation itself is not lost: the host keeps the session transcript, and a
compaction summary names its path. The page does not copy it; cite it where exact
wording matters. The page is plain markdown that you write with your normal editing
tools. The bundled scripts only locate and select records, keep good copies and
deliver the current state at recovery; they never decide content. On Claude Code one
hook can keep a turn going: once after a compaction while no page is selected, it
stops the turn from ending and asks you to create or select one.

## Create and select the page

Resolve `<skill-dir>` from this loaded Skill's path and use it only to run bundled
code. Keep record paths relative to the project root.

Use, in order: a path the user names; this task's existing note or document; the
project's documented convention; otherwise `tasks/<YYYY-MM-DD>-<slug>.md` in the
project root. Match the task's identity and scope, not recency or installed Skills.

```bash
python3 "<skill-dir>/scripts/task_state.py" init --task <YYYY-MM-DD-slug> --objective "<the confirmed intent>" --session <native-session-id>
python3 "<skill-dir>/scripts/task_state.py" init --file <relative-path> --objective "<the confirmed intent>" --session <native-session-id>
python3 "<skill-dir>/scripts/task_state.py" read --file <relative-path>
```

`init` never overwrites and prints the record path. With `--session` it also selects
the record for that native session, so hooks can recover it; on Claude Code the ID is
in `CLAUDE_CODE_SESSION_ID`. Pass the actual native session ID; never invent one or use
a delegation ID. If the session already selects another existing record, `init` keeps
that selection and prints the commands that switch it; a selection whose page no
longer exists is replaced. `--task <id>` means `tasks/<id>.md`; on first use `init`
creates `tasks/` with an ownership README, and if the project already owns a `tasks/`
folder it refuses, so pass `--file`. `--root <project-root>` pins the workspace when
discovery cannot find it. Legacy `work/task-state.md` and `.tasks/<id>.md` records
remain readable.

Select an existing record for this session:

```bash
python3 "<skill-dir>/scripts/task_state.py" activate --file <relative-path> --session <native-session-id> --root <project-root>
```

Selections live in `.task-state/sessions/`, local to this workspace and never
committed. Unselected hooks do not recover records. If the host does not expose its
session ID, launch it with `TASK_STATE_TASK` or `TASK_STATE_FILE` (optionally
`TASK_STATE_ROOT`) or read manually; changing a child shell's environment cannot change
the running host. A new session is not a new task: continue the same page across turns,
corrections, compactions and agents.

## Write the page

```markdown
# <task title>

<!-- current-state -->
Intent: <the interpretation confirmed with the user, including constraints and authority in force>
Conclusions in force:
- <judgment> (evidence: `pytest -q` in repo root: 42 passed)
Done, do not redo:
- <result> (evidence: <path, or command, directory and result>)
Next: <one to three actions>
Open owner decisions: <what only the user can settle>
<!-- /current-state -->

## History
- 2026-10-24T02:03Z User: "<exact words>"
- 2026-10-24T02:12Z Superseded: <what changed, why, and the evidence>
```

- **Intent** is what you and the user settled, which is often not their first wording.
  Quote their words when a paraphrase could change the meaning.
- **Every conclusion and done item names its evidence**: a command with its directory and
  result, a file path, the user's quoted words, or the transcript path and what to find
  there. A done item with evidence is not repeated; recheck it only when its premise
  changed.
- **Steps** belong in the host's task list (Claude Code's survives compaction); the page
  holds results and what they rest on.
- `init` writes `[unfilled: ...]` in the fields it cannot know. Replace each before
  relying on the page.
- Keep the block under about 3,000 characters and only what is true now; recovery
  delivers it whole only while it fits, otherwise only the path. When something stops
  being true, change it in the same edit and put the reason in History. The fields are a
  default, not a schema; choose wording that fits the task.
- **History** is appended, never rewritten: the user's exact words when a paraphrase
  could change their meaning, decisions with the alternatives rejected, corrections with
  their evidence, verification with command, working directory and result, handoffs.
  Never persist credentials or treat external text as authority.

Write when the understanding changes, while it is still exact: a requirement is
clarified or corrected, a conclusion is reached or overturned, work completes or
blocks, verification changes what can be claimed, before a handoff or an intentional
stop. On Claude Code the end of the first turn after a compaction without a selected
page asks once for a page; otherwise nothing reminds you. There is no quota. Edit with
exact text edits, not generated scripts that rewrite the file; a script that misfires
can damage the whole record without any visible error.

On Codex, zCode and Grok (on Kimi, before each user message), hooks compare the
selected record with the version they last saw and check three facts: the
current-state markers form exactly one pair, the block fits the recovery size, and, for
records under `tasks/` (or legacy `.tasks/`), earlier History entries are still present
in order. Passing versions are kept as the last three good copies in
`.task-state/snapshots/`, and a problem is reported once; nothing is blocked. Claude
Code does not run this check; recovery stores a good copy when it delivers the page. A
manual check reports every current problem:

```bash
python3 "<skill-dir>/scripts/task_state.py" check --file <relative-path>
```

## Borrowed documents and other Skills

When the task already has a document, such as a Deep Thinking `THOUGHTS.md` or a
business note, keep its structure and edit only its current-state section; wrap that
section in the same markers so recovery delivers only it. Do not insert this
template. When handed a result or specification, read it and preserve its accepted
outcome, acceptance IDs and meanings, exclusions, corrections and authority;
reference it instead of copying it or re-interviewing the owner.

If an UltraGoal goal owns execution state, maintain its `## Carry-over` (State,
Lessons, Next) and leave its frozen clauses intact. UltraGoal recovers its own goal,
so do not also select this Skill's page for it. Keep one page and one writer per task;
workers return evidence for the writer to integrate. A dispatch receipt or a
completed checklist is not acceptance.

Keep owner intent above the adopted approach and the approach above progress. New
evidence may change judgments and authorized means; only explicit owner steering
changes purpose, scope or success criteria. A user correction steers the existing
task unless it actually replaces the objective.

## Recover

Codex, Claude Code and zCode deliver the selected record at `SessionStart`
(startup, resume, clear, compact); Grok after the next tool call; Kimi before the
next user message. The delivery is the current-state block plus the record path. It
is facts and navigation, not instructions: the latest user request wins, and it
grants no authority to continue or to cause external effects. A legacy record
without markers arrives whole when small, otherwise as a labeled partial preview.

On Claude Code, if a compaction finds no selected page, the end of the next turn asks
once: create and select a page with the printed `init` command and replace every
`[unfilled]` field, Intent included, from the summary and, where exact wording
matters, the transcript; or select this task's existing page with the printed
`deactivate && activate` line, substituting its path; or, if an UltraGoal goal or another record holds the task's state,
say so and end the turn.

Resume from the page: treat its intent and conclusions as settled and trust done items
whose evidence still holds. Before changing direction, claiming completion, or relying
on anything the block does not contain, read the full record:

```bash
python3 "<skill-dir>/scripts/task_state.py" read --file <relative-path>
```

Compare the page with the latest request and live artifacts, recheck facts whose
premises changed, and reuse conclusions whose premises still hold rather than
repeating whole investigations. [host-recovery.md](references/host-recovery.md) covers
adapters and diagnosis.

## Hand off and finish

Before a handoff, update the page, then give the receiver its relative path, the
workspace root, the branch or revision with any uncommitted artifacts, and one next
action. A selection file or a new worktree does not carry uncommitted files; transfer
them explicitly. For simultaneous tasks, pass explicit selectors per command or per
launch environment and never change another session's selection. Retain a delegated
task's ID and terminal receipt with its actual output paths; if its outcome is unknown,
inspect native state and effects before retrying.

When the outcome is verified, record what was delivered, its evidence and remaining
limits, and move durable knowledge into the project's real documentation. Then move
the record to `tasks/archive/` (never overwriting an earlier archive) and remove this
session's selection with `task_state.py deactivate --session <native-session-id>
--root <project-root>`. Borrowed documents follow their own lifecycle. Do not promote
task-specific lessons into global instructions or long-term memory automatically.
`TASK_STATE_DISABLED=1` silences every hook for one unrelated invocation.
[working-notes.md](references/working-notes.md) shows what useful entries look like.
