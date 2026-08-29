# Architecture

This package treats file-backed state as recoverable working data, not as an execution
engine or a semantic completion oracle.

## Surfaces

- The Skill owns the reusable workflow: when to create state, what it must contain,
  when to checkpoint it, how to recover, and when to clean it up.
- The Plugin owns distribution and the executable `SessionStart` lifecycle Hook.
- The Hook only resolves, bounds, labels, and injects existing state. It never creates
  semantic content, blocks stopping, or continues a task.
- The state document remains the only canonical working artifact. The `.ref` file is a
  disposable relative pointer.

## Locality and containment

The event `cwd` is the task root. Session-local state is `work/task-state.md`. A shared
WIP file is selected by `work/task-state.ref`, whose complete content is one portable
relative path.

The resolver rejects absolute paths, parent traversal, symlink escape, missing targets,
non-files, malformed bindings, and two active sources. It canonicalizes paths only in
memory to prove containment; absolute identities are not persisted or sent to the
model.

The locality key is intentionally the task directory. Independent concurrent tasks
must use separate directories or Git worktrees. A hidden per-session registry would add
a second state authority and is deferred until a real same-directory collision proves
it necessary.

## Recovery lifecycle

`SessionStart` runs on `startup`, `resume`, `clear`, and `compact`. Missing state is
silent. Invalid state produces a bounded advisory diagnostic. Valid state is rendered
into labeled `additionalContext`, prioritizing `Next action` and `Not done / do not
redo`, with a hard character ceiling.

The renderer states that recovery data is lower priority than current instructions,
must be reconciled with the live workspace, and does not authorize automatic
continuation or external effects. `TASK_STATE_DISABLED=1` makes the Hook silent for an
unrelated one-shot invocation.

## Why this is narrower than planning-with-files

The design was reviewed against
[`planning-with-files` v3.11.2](https://github.com/OthmanAdi/planning-with-files/releases/tag/v3.11.2).
That project has accumulated valuable solutions for multi-platform adapters,
three-file planning, per-turn injection, catchup from transcript stores, parallel plan
selection, session attachment, attestation, ledgers, and optional continuation modes.

This package keeps the parts required by the accepted Codex outcome:

- durable owner-readable state;
- post-compaction and post-resume recovery;
- bounded, labeled injection;
- relative locality and containment;
- explicit one-shot opt-out;
- Plugin and Skill installation paths with Hook trust review.

It omits per-turn injection, transcript scraping, attestation, phase counters, Stop
gates, heartbeats, and auto-continuation. Those mechanisms add context cost or turn
mechanical observations into semantic control. They should be introduced only for a
named reproduced failure with a clear repair path.
