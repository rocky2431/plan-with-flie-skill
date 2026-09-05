#!/usr/bin/env python3
"""Restore local task state into Codex SessionStart context without blocking."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


SUPPORTED_SOURCES = {"startup", "resume", "clear", "compact"}


def _runtime():
    plugin_root = Path(os.environ.get("PLUGIN_ROOT", Path(__file__).resolve().parents[1]))
    scripts = plugin_root / "skills" / "task-state-with-files" / "scripts"
    sys.path.insert(0, str(scripts))
    from task_state_runtime import recovery_context_from_root

    return recovery_context_from_root


def _emit(additional_context: str) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    }
    print(json.dumps(payload, ensure_ascii=False))


def main() -> int:
    if os.environ.get("TASK_STATE_DISABLED") == "1":
        return 0

    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        return 0
    if not isinstance(event, dict):
        return 0

    if event.get("hook_event_name") != "SessionStart":
        return 0
    if event.get("source") not in SUPPORTED_SOURCES:
        return 0
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return 0

    try:
        context = _runtime()(Path(cwd), root_pin=os.environ.get("TASK_STATE_ROOT"), task=os.environ.get("TASK_STATE_TASK"))
        if context:
            _emit(context)
    except (OSError, UnicodeError, ImportError, RuntimeError):
        _emit(
            "Recovery skipped: the local task-state file could not be loaded. "
            "Inspect the relative state file before relying on recovery."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
