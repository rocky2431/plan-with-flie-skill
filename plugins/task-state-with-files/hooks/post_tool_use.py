#!/usr/bin/env python3
"""Report selected-record damage through Codex's PostToolUse context channel."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main() -> int:
    if os.environ.get("TASK_STATE_DISABLED") == "1":
        return 0
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or event.get("hook_event_name") != "PostToolUse":
            return 0
        cwd = event.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return 0
        plugin_root = Path(os.environ.get("PLUGIN_ROOT", Path(__file__).resolve().parents[1]))
        sys.path.insert(0, str(plugin_root / "skills/task-state-with-files/scripts"))
        from task_state_runtime import sense_selected_record

        message = sense_selected_record(
            Path(cwd), root_pin=os.environ.get("TASK_STATE_ROOT"),
            task=os.environ.get("TASK_STATE_TASK"), state_file=os.environ.get("TASK_STATE_FILE"),
            session_id=event.get("session_id"),
        )
        if message:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PostToolUse", "additionalContext": message,
            }}, ensure_ascii=False))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
