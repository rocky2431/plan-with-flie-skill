#!/usr/bin/env python3
"""Restore task state through supported non-blocking host lifecycle hooks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from task_state_runtime import render_recovery_context, resolve_state


SESSION_START_SOURCES = {"startup", "resume", "clear", "compact"}


def _event_is_supported(host: str, event: dict[str, object]) -> bool:
    event_name = event.get("hook_event_name")
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
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))


def _load_context(cwd: str) -> str | None:
    resolution = resolve_state(Path(cwd))
    if resolution.status == "missing":
        return None
    if resolution.status == "invalid":
        return (
            f"Recovery skipped: {resolution.message} "
            "Fix the local state files before relying on recovery."
        )

    assert resolution.path is not None and resolution.relative_path is not None
    state = resolution.path.read_text(encoding="utf-8")
    return render_recovery_context(
        relative_path=resolution.relative_path,
        text=state,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=("kimi", "zcode", "claude"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if os.environ.get("TASK_STATE_DISABLED") == "1":
        return 0

    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        return 0
    if not isinstance(event, dict) or not _event_is_supported(args.host, event):
        return 0

    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return 0

    try:
        context = _load_context(cwd)
    except (OSError, UnicodeError, RuntimeError):
        context = (
            "Recovery skipped: the local task-state file could not be loaded. "
            "Inspect the relative state file before relying on recovery."
        )
    if context:
        _emit(args.host, context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
