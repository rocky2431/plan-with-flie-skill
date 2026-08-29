# Task State with Files for Codex

A portable Codex Plugin that keeps substantive task progress in an owner-readable file
below the current task directory and restores a bounded excerpt after session startup,
resume, clear, or context compaction.

The package combines two surfaces:

- a standard `task-state-with-files` Skill that teaches Codex when and how to maintain
  task state;
- a non-blocking `SessionStart` Hook that restores existing state through
  `additionalContext`.

It intentionally has no `Stop` Hook, goal loop, heartbeat, semantic completion gate,
or automatic continuation.

## State locations

Session-scoped state is stored at `work/task-state.md`, relative to the event `cwd`.
Repository-shared WIP may live at an established project path such as
`docs/wip/<slug>.md`; `work/task-state.ref` then contains only that relative path.

Absolute bindings, parent traversal, symlink escape, dual state sources, and missing
shared targets fail closed. Canonical absolute paths are used only inside the resolver
to prove containment and are never injected into model context.

## Install the Plugin

The Plugin install is recommended because it includes both the Skill and recovery Hook:

```bash
codex plugin marketplace add rocky2431/plan-with-flie-skill
codex plugin add task-state-with-files@rocky-task-state
```

Review and trust the bundled Hook when Codex asks. Plugin Hooks are executable code and
should be inspected before enabling.

For local development, add the repository checkout instead:

```bash
codex plugin marketplace add ./plan-with-flie-skill
codex plugin add task-state-with-files@rocky-task-state
```

Restart Codex after installation so the Skill and Hook are discovered in a fresh
session.

## Skill-only use

The directory
`plugins/task-state-with-files/skills/task-state-with-files` is also a valid standalone
Skill. A Skill-only install retains the workflow and CLI but does not install the
`SessionStart` Hook; recovery is then manual.

## CLI

Inside an activated Skill, `${SKILL_ROOT}` points at the Skill directory:

```bash
python3 "${SKILL_ROOT}/scripts/task_state.py" init \
  --objective "Ship the observable outcome" --root .

python3 "${SKILL_ROOT}/scripts/task_state.py" bind \
  docs/wip/example.md --root .

python3 "${SKILL_ROOT}/scripts/task_state.py" resolve --root .
```

`init` is idempotent. `bind` refuses to replace a different binding or coexist with a
session-local state file.

## One-shot and concurrent sessions

An unrelated one-shot command may deliberately ignore active state in the same
directory:

```bash
TASK_STATE_DISABLED=1 codex exec -C . "<one-shot request>"
```

The default locality key is the current `cwd`, not a hidden global session registry.
Two independent tasks must therefore use separate Codex task directories or Git
worktrees. Sessions may share a bound WIP file only when they are collaborating on the
same task. This keeps state ownership visible; a per-session attachment registry should
be added only if a reproduced same-directory collision requires it.

## Design choices

This project was informed by
[`OthmanAdi/planning-with-files`](https://github.com/OthmanAdi/planning-with-files),
including its recovery, path-containment, parallel-task, opt-out, and install-verification
work. It is an independent Codex adaptation, not a vendored copy. It deliberately uses
one pruned state document, one lifecycle Hook, Codex Plugin distribution, and advisory
recovery semantics. See [the architecture note](docs/architecture.md) for the detailed
tradeoffs.

## Development

The implementation uses only the Python standard library.

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

CI runs the same suite on Linux, macOS, and Windows.

See the bundled Skill for the maintenance and cleanup protocol.
