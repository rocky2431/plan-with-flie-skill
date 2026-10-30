"""Advisory Claude Code PostToolUse reminders; never edit a task record."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

from task_state_runtime import (
    atomic_write, contained_path, find_task_root, parse_current_state,
    resolve_relative_target, selected_record_from_root,
)


# ~3 reminders per 400K cycle limit summary-only unrecorded work to ~100K; make configurable only if a real need appears.
CONTEXT_GROWTH_THRESHOLD = 100_000
TRANSCRIPT_TAIL_BYTES = 1024 * 1024


def transcript_context_size(path: Path) -> int | None:
    """Read at most one bounded tail, never search backward through a transcript."""
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        start = max(0, handle.tell() - TRANSCRIPT_TAIL_BYTES)
        handle.seek(start)
        tail = handle.read(TRANSCRIPT_TAIL_BYTES)
    if start:
        # The first line can be a truncated JSON object (or UTF-8 character).
        tail = tail.partition(b"\n")[2]
    for line in reversed(tail.splitlines()):
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if isinstance(message, dict) and message.get("model") == "<synthetic>":
            continue
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict) or "input_tokens" not in usage:
            return None
        counts = [usage.get(key, 0) for key in
                  ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
        if any(type(count) is not int or count < 0 for count in counts):
            return None
        total = sum(counts)
        if total == 0:
            continue
        return total
    return None


def _growth_report(result, session: str, transcript: str) -> str | None:
    size = transcript_context_size(Path(transcript))
    if size is None:
        return None
    text = result.path.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode()).hexdigest()
    if not contained_path(result.root, ".task-state").is_dir():
        return None
    directory = contained_path(result.root, ".task-state/context-growth")
    directory.mkdir(exist_ok=True)
    key = hashlib.sha256(session.encode()).hexdigest()
    state_path = contained_path(result.root, f".task-state/context-growth/{key}.json")
    lock = contained_path(result.root, f".task-state/context-growth/{key}.lock")
    # Non-blocking OS locks also release if the host terminates a hook early.
    with lock.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if not handle.tell():
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
        if (not isinstance(state, dict) or state.get("digest") != digest
                or state.get("record") != result.relative_path
                or type(state.get("baseline")) is not int
                or state["baseline"] < 0 or size < state["baseline"]):
            atomic_write(state_path, json.dumps({"record": result.relative_path,
                         "digest": digest, "baseline": size, "reported": False}))
            return None
        growth = size - state["baseline"]
        if growth < CONTEXT_GROWTH_THRESHOLD or state.get("reported") is not False:
            return None
        identity = result.relative_path
        if len(identity) > 150:
            identity = identity[:147] + "..."
        report = (
            f"Task-state context growth: {identity}\n"
            f"Context has grown by approximately {growth:,} tokens since this record last changed or "
            "context last shrank (for example at compaction), whichever came later. "
            "Compaction may happen at any time. If anything changed since then (the owner's wording, "
            "decisions, corrections, evidence, progress or next step), update the current-state block "
            "and History where the Skill requires it. Nothing was blocked."
        )
        state["reported"] = True
        atomic_write(state_path, json.dumps(state))
        return report


def _unselected_report(cwd: Path, event: dict, session: str, root_pin: str | None) -> str | None:
    if event.get("tool_name") not in {"Write", "Edit", "MultiEdit"}:
        return None
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    tool_input = event.get("tool_input")
    filename = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not data or not isinstance(filename, str) or not filename:
        return None
    root = Path(root_pin).resolve(strict=True) if root_pin is not None else find_task_root(cwd)
    path = Path(filename)
    path = (cwd / path).resolve(strict=True) if not path.is_absolute() else path.resolve(strict=True)
    relative = path.relative_to(root).as_posix()
    if (resolve_relative_target(root, relative).status != "found"
            or parse_current_state(path.read_text(encoding="utf-8")).status != "ok"):
        return None
    # `--opt=value` keeps a value that starts with "-" from being read as an option.
    command = shlex.join([sys.executable, str(Path(__file__).with_name("task_state.py").resolve()),
                          "activate", f"--file={relative}", f"--session={session}", "--root", str(root)])
    identity = relative
    if len(identity) > 150:
        identity = identity[:147] + "..."
    report = (
        f"Task-state selection: {identity}\n"
        "Compaction recovery will not deliver this file because this session has no selected record. "
        f"To select it, run:\n{command}\n"
        "Ignore this report if the file belongs to a different task. Nothing was blocked."
    )
    data_root = Path(data).resolve(strict=True)
    claim_key = hashlib.sha256((session + "\0" + str(path)).encode()).hexdigest()
    claim = contained_path(data_root, f"task-state/unselected/{claim_key}.sent")
    claim.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return None
    os.close(descriptor)
    return report


def sense_claude_post_tool(cwd: Path, event: dict) -> str | None:
    """Report once per growth episode or unselected file, and fail silently."""
    if os.environ.get("TASK_STATE_DISABLED") == "1" or "agent_id" in event:
        return None
    session = event.get("session_id")
    if not isinstance(session, str) or not session.strip():
        return None
    try:
        root_pin = os.environ.get("TASK_STATE_ROOT")
        selected = selected_record_from_root(
            cwd, root_pin=root_pin, task=os.environ.get("TASK_STATE_TASK"),
            state_file=os.environ.get("TASK_STATE_FILE"), session_id=session,
        )
        if selected is None:
            return _unselected_report(cwd, event, session, root_pin)
        transcript = event.get("transcript_path")
        if selected.status == "found" and isinstance(transcript, str) and transcript:
            return _growth_report(selected, session, transcript)
    except Exception:
        pass
    return None
