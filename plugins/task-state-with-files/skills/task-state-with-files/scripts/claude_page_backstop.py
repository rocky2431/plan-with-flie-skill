"""Request a task page once after compaction without a selected page."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re


def page_backstop(cwd: Path, event: dict) -> str | None:
    name = event.get("hook_event_name")
    if name != "Stop" and not (name == "SessionStart" and event.get("source") == "compact"):
        return None
    session = event.get("session_id")
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if (event.get("stop_hook_active") or "agent_id" in event
            or os.environ.get("TASK_STATE_DISABLED") == "1" or not data
            or not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", session)):
        return None
    try:
        marker = Path(data) / "task-state/compacted" / hashlib.sha256(session.encode()).hexdigest()
        if name == "Stop" and not marker.exists():
            return None
        from task_state_runtime import find_task_root, selected_record_from_root

        pin = os.environ.get("TASK_STATE_ROOT")
        root = Path(pin).resolve(strict=True) if pin is not None else find_task_root(cwd)
        if not root.is_dir():
            return None
        selected = selected_record_from_root(
            root, root_pin=str(root), task=os.environ.get("TASK_STATE_TASK"),
            state_file=os.environ.get("TASK_STATE_FILE"), session_id=session,
        )
        found = selected is not None and selected.status == "found"
        if name == "SessionStart":
            if not found:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.touch()
            return None
        # Serialize before consuming the marker, as ASCII, so a failure leaves it in place
        # and printing the result cannot fail on encoding.
        response = None if found else json.dumps(
            {"decision": "block", "reason": _reason(root, session, event)})
        # Only the process that consumes the marker may request a page.
        marker.unlink()
        return response
    except Exception:
        return None


def _reason(root: Path, session: str, event: dict) -> str:
    from datetime import datetime, timezone
    import shlex

    cli = str(Path(__file__).resolve().with_name("task_state.py"))
    # Keep the existing task ID rule: lowercase letters, digits and hyphens.
    slug = datetime.now(timezone.utc).strftime("%Y-%m-%d") + "-" + re.sub(r"[^a-z0-9-]", "-", session[:8].lower())
    common = [f"--session={session}", "--root", str(root)]
    init = shlex.join(["python3", cli, "init", "--task", slug, "--objective",
                       "[unfilled: the confirmed intent]", *common])
    # deactivate first: no selection resolves here, so it only clears a dangling binding.
    activate = (shlex.join(["python3", cli, "deactivate", *common]) + " && "
                + shlex.join(["python3", cli, "activate", "--file", "path/to/task-page.md", *common]))
    facts = ("This session was compacted while no task page was selected. The settled intent, "
             "conclusions and completed work now exist only in the compaction summary.")
    request = ("\nBefore ending this turn, either create and select a page with:\n" + init
               + "\nand replace every [unfilled] field, Intent included, from the summary and, where "
               "exact wording matters, the transcript; or select this task's existing page with "
               "the command below, substituting its relative path:\n" + activate
               + "\nor, if an UltraGoal goal or another record already holds this task's state, "
               "say so and end the turn. This request does not repeat until the next compaction without a page.")
    transcript = event.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        located = facts + f" The full conversation is at {transcript}."
        # The transcript path is optional context; drop it rather than the request.
        if len(located + request) - len(init) - len(activate) <= 1200:
            facts = located
    return facts + request
