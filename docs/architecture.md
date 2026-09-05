# Architecture

This package treats file-backed state as recoverable working data, not as an execution
engine or a semantic completion oracle.

## Surfaces

- The standard Skill owns the reusable workflow: when to create state, what it must
  contain, when to checkpoint it, how to recover, and when to clean it up.
- The Codex Plugin owns Codex distribution and its executable `SessionStart` Hook.
- The user installer owns reviewed, reversible placement in Kimi, ZCode, Claude Code,
  and Hermes. It does not own task semantics.
- Host lifecycle adapters only resolve, bound, label, and inject existing state. They
  never create semantic content, block stopping, or continue a task.
- The state document remains the one canonical working artifact. The `.ref` file is a
  disposable relative pointer; installation backups are recovery copies, not task
  state.

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

Codex, Claude Code, and ZCode restore through
`SessionStart(startup|resume|clear|compact)`. Kimi uses `UserPromptSubmit`; its
`SessionStart` and `PostCompact` return values do not reach model context. Each user
message rereads current state without a persistent deduplication cache, so compaction
cannot strand a previously injected excerpt behind a stale delivery flag. This does
not provide immediate recovery during autonomous compaction. Missing state is silent. Invalid
state produces a bounded advisory diagnostic. Valid state prioritizes `Next action`
and `Not done / do not redo` under a hard character ceiling.

Hermes has no equally narrow post-compaction context-return event. Its Plugin and shell
hook systems can inject at `pre_llm_call`, but that runs every turn. The package installs
the standard Skill and retains manual recovery instead of silently adopting continuous
injection. If Hermes later ships a dedicated, non-blocking post-compaction context
event, it can receive the same adapter without changing state semantics.

Every renderer states that recovery data is lower priority than current instructions,
must be reconciled with the live workspace, and does not authorize automatic
continuation or external effects. `TASK_STATE_DISABLED=1` makes lifecycle adapters
silent for an unrelated one-shot invocation.

## Installation and rollback

Each non-Codex host receives an independent copy of the same Skill at its native user
path. Kimi's TOML gets one marker-delimited managed block. ZCode and Claude Code receive
one managed `SessionStart` hook group identified by its bundled script command. Reruns
replace only those managed entries, so installation is idempotent and foreign hooks
remain intact.

Before changing an existing Skill directory or configuration file, the installer copies
it to a timestamped recovery directory. Writes are staged and atomically replaced.
Uninstall removes only the four managed Skill paths and the package's own hook entries.
The `doctor` command compares installed Skill trees with the reviewed source and checks
the expected Hook registration. For Kimi it checks the actual event and command,
not merely that two obsolete entries still exist. This is installation verification,
not proof of live context delivery.

## Why this is narrower than planning-with-files

The design was reviewed against
[`planning-with-files` v3.11.2](https://github.com/OthmanAdi/planning-with-files/releases/tag/v3.11.2).
That project has accumulated valuable solutions for multi-platform adapters,
three-file planning, per-turn injection, catchup from transcript stores, parallel plan
selection, session attachment, attestation, ledgers, and optional continuation modes.

This package keeps only the mechanisms needed for the accepted outcome:

- durable owner-readable state;
- post-compaction and post-resume recovery where the host exposes a correct event;
- bounded, labeled injection;
- relative locality and containment;
- explicit one-shot opt-out;
- reversible Skill and Hook installation with a host-aware doctor.

It omits injection before every model step, transcript scraping, attestation, phase counters, Stop
gates, heartbeats, and auto-continuation. Those mechanisms add context cost or turn
mechanical observations into semantic control. They should be introduced only for a
named reproduced failure with a clear repair path.
