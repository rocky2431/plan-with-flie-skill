---
name: task-state-with-files
description: "Use for tool-driven execution that is substantive, multi-step, long-running, likely to survive context compaction or resume, or deliberately left unfinished. Keep the task's objective, decisions, evidence, next action, and explicit not-done list in a relative owner-readable file so the active agent can recover without relying on conversation history. Do not use for answer-only questions, simple lookups, or one-step edits that finish in the current turn."
license: MIT
---

# Task State With Files

Keep one compact, current source of working truth for a substantive task. The file is
recovery data, not a second prompt and not an authority to continue automatically.

## Start the task

Before the first mutation or extended investigation:

1. Define observable completion and the current scope.
2. For session-scoped work, initialize `work/task-state.md` relative to the current
   task directory:

   ```bash
   python3 "<skill-dir>/scripts/task_state.py" init \
     --objective "<observable task objective>" --root .
   ```

3. For repository-shared work that must survive another session or worktree, use the
   repository's established WIP location. If none exists, create one short
   `docs/wip/<slug>.md`, then bind it with a relative reference:

   ```bash
   python3 "<skill-dir>/scripts/task_state.py" bind \
     docs/wip/<slug>.md --root .
   ```

Resolve `<skill-dir>` from the loaded `SKILL.md` path exposed by the current host.
Use that absolute installation path only to run bundled code; never persist it in task
state or a binding.

Never persist an absolute task-state path. Never include `..` in a binding. Keep
exactly one of `work/task-state.md` and `work/task-state.ref`.

## Maintain the state

Prune and rewrite the document at meaningful checkpoints; do not append a transcript.
Keep these sections accurate:

- objective and observable done condition;
- constraints, approvals, and authority boundaries;
- current state and durable decisions with evidence;
- actions actually run and their verification results;
- blockers and attempted fixes;
- one concrete next action;
- explicit not-done and do-not-redo items.

Update it after each completed plan step or evidence-changing tool batch, before risky
changes, after a decision changes the plan, after verification, before handing off,
and before intentionally ending unfinished work. If the host reports context pressure
or imminent compaction, checkpoint before doing more work. Do not expect a
post-compaction Hook to reconstruct decisions that were never written. Record relative
artifact identities, commands, and evidence; omit secrets and ephemeral narration.

## Recover safely

When a supported non-blocking host adapter is installed, it restores a bounded excerpt
through `SessionStart` or the host's dedicated post-compaction event. A Skill-only
install has no automatic lifecycle recovery, so read the active state manually:

```bash
python3 "<skill-dir>/scripts/task_state.py" resolve --root .
```

Read [references/host-recovery.md](references/host-recovery.md) only when installing,
auditing, or diagnosing a host adapter.

After recovery, compare the file with the live workspace and current user request.
Re-run cheap checks when facts may have changed. Never treat an incomplete checklist as
permission for external effects, destructive work, or automatic continuation.

For an unrelated one-shot command sharing a directory with active state, disable
recovery only for that invocation:

```bash
TASK_STATE_DISABLED=1 <host one-shot command>
```

Do not run concurrent tasks against one state file. Give each task a separate task
directory or Git worktree; share one bound WIP file only when the sessions truly own
the same task.

## Finish

When the accepted outcome is verified, reconcile durable facts into canonical project
documentation and delete transient session state. For repository-shared work, follow
the repository's WIP cleanup rule and remove `work/task-state.ref`. Leave the state in
place only when work is explicitly deferred, and make the not-done list precise.
