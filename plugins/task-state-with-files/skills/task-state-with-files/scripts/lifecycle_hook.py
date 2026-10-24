#!/usr/bin/env python3
"""Restore task state through supported non-blocking host lifecycle hooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from task_state_runtime import recovery_context_from_root, sense_selected_record


SESSION_START_SOURCES = {"startup", "resume", "clear", "compact"}


def _event_is_supported(host: str, event: dict[str, object]) -> bool:
    event_name = event.get("hook_event_name")
    if event_name == "PostToolUse":
        return host != "kimi"
    if host == "grok":
        return event_name == "PostToolUse"
    if host == "kimi":
        # Kimi injects prompt output; PostToolUse is fire-and-forget.
        return event_name == "UserPromptSubmit"
    return (
        event_name == "SessionStart"
        and event.get("source") in SESSION_START_SOURCES
    )


def _emit(host: str, context: str, event_name: str) -> None:
    if host == "kimi":
        print(context)
        return
    payload = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
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
            if event.get("hook_event_name") != "SessionEnd":
                cwd = event.get("cwd")
                if isinstance(cwd, str) and cwd:
                    try:
                        _load_context(cwd, session)
                    except (OSError, UnicodeError, RuntimeError):
                        pass
            return 0
    if not _event_is_supported(args.host, event):
        return 0

    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return 0

    session_id = event.get("sessionId" if args.host == "grok" else "session_id")
    event_name = event.get("hook_event_name")
    sensor = None
    if event_name == "PostToolUse" or args.host == "kimi":
        sensor = sense_selected_record(
            Path(cwd), root_pin=os.environ.get("TASK_STATE_ROOT"),
            task=os.environ.get("TASK_STATE_TASK"), state_file=os.environ.get("TASK_STATE_FILE"),
            session_id=session_id,
        )
        if event_name == "PostToolUse" and (args.host != "grok" or marker.exists()):
            if sensor:
                _emit(args.host, sensor, event_name)
            return 0

    try:
        context = _load_context(cwd, session_id)
    except (OSError, UnicodeError, RuntimeError):
        context = (
            "Recovery skipped: the local task-state file could not be loaded. "
            "Inspect the relative state file before relying on recovery."
        )
    if sensor:
        context = sensor + ("\n\n" + context if context else "")
    if context:
        if marker is not None:
            marker.parent.mkdir(parents=True, exist_ok=True)
            try:
                marker.touch(exist_ok=False)
            except FileExistsError:
                # Another hook already delivered recovery; a claimed report is
                # still this process's to deliver.
                if sensor:
                    _emit(args.host, sensor, event_name)
                return 0
        _emit(args.host, context, event_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
