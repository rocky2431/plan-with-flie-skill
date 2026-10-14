#!/usr/bin/env python3
"""Restore task state through supported non-blocking host lifecycle hooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from task_state_runtime import recovery_context_from_root


SESSION_START_SOURCES = {"startup", "resume", "clear", "compact"}


def _event_is_supported(host: str, event: dict[str, object]) -> bool:
    event_name = event.get("hook_event_name")
    if host == "grok":
        return event_name == "PostToolUse"
    if host == "kimi":
        # Kimi discards SessionStart/PostCompact output. Only this event
        # appends recovery text before the next user-origin model request.
        return event_name == "UserPromptSubmit"
    return (
        event_name == "SessionStart"
        and event.get("source") in SESSION_START_SOURCES
    )


def _emit(host: str, context: str) -> None:
    if host == "kimi":
        print(context)
        return
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse" if host == "grok" else "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))


def _load_context(cwd: str, session_id: str | None) -> str | None:
    return recovery_context_from_root(
        Path(cwd), root_pin=os.environ.get("TASK_STATE_ROOT"),
        task=os.environ.get("TASK_STATE_TASK"), state_file=os.environ.get("TASK_STATE_FILE"),
        session_id=session_id,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=("kimi", "zcode", "claude", "grok"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if os.environ.get("TASK_STATE_DISABLED") == "1":
        return 0

    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        return 0
    if not isinstance(event, dict):
        return 0

    marker = None
    if args.host == "grok":
        session, data = event.get("sessionId"), os.environ.get("GROK_PLUGIN_DATA")
        if not isinstance(session, str) or not session or not data:
            return 0
        key = hashlib.sha256((str(event.get("cwd")) + "\0" + session).encode()).hexdigest()
        marker = Path(data) / "recovery" / (key + ".sent")
        if event.get("hook_event_name") in {"SessionStart", "PostCompact", "SessionEnd"}:
            marker.unlink(missing_ok=True)
            return 0
        if marker.exists():
            return 0
    if not _event_is_supported(args.host, event):
        return 0

    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return 0

    try:
        context = _load_context(cwd, event.get("sessionId" if args.host == "grok" else "session_id"))
    except (OSError, UnicodeError, RuntimeError):
        context = (
            "Recovery skipped: the local task-state file could not be loaded. "
            "Inspect the relative state file before relying on recovery."
        )
    if context:
        if marker is not None:
            marker.parent.mkdir(parents=True, exist_ok=True)
            try:
                marker.touch(exist_ok=False)
            except FileExistsError:
                return 0
        _emit(args.host, context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
