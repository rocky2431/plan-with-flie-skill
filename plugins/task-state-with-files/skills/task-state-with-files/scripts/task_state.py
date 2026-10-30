#!/usr/bin/env python3
"""Create, locate, and read file-backed task working notes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import sys

from task_state_runtime import (
    SESSION_STATE,
    STATE_BINDING,
    CURRENT_STATE_LIMIT,
    MANAGED_TASKS_LINE,
    Resolution,
    contained_path,
    ensure_runtime_directory,
    find_task_root,
    format_sensor_report,
    legacy_session_relative_path,
    managed_tasks_directory,
    observe,
    parse_current_state,
    resolve_relative_target,
    resolve_state,
    selected_record_from_root,
    session_relative_path,
    task_record_relative_path,
    task_relative_path,
)


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_ROOT / "assets" / "task-state-template.md"
TASKS_README = f"""{MANAGED_TASKS_LINE}
# tasks/

This folder is managed by the task-state-with-files Skill. Each file is one task's
working record: a short current-state block at the top, followed by append-only
history. Records are owner-readable working state, not product documentation.
Finished records move to `tasks/archive/`. Whether to commit them is the project's
choice; runtime state lives in `.task-state/` and is never committed.
"""


def _write_new(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _root(args: argparse.Namespace) -> Path:
    pin = args.root if args.root is not None else os.environ.get("TASK_STATE_ROOT")
    if pin is not None:
        root = Path(pin).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("The task root must be a directory.")
        return root
    return find_task_root(Path.cwd())


def _destination(root: Path, relative: str) -> Path:
    return contained_path(root, relative)


def _selection(args: argparse.Namespace) -> Resolution:
    state_file = getattr(args, "file", None)
    task = args.task
    if task is None and state_file is None:
        task = os.environ.get("TASK_STATE_TASK")
        state_file = os.environ.get("TASK_STATE_FILE")
    try:
        root = _root(args)
    except (OSError, RuntimeError, ValueError):
        return Resolution(status="invalid", message="The task root is unavailable or is not a directory.")
    return resolve_state(root, task=task, state_file=state_file, discover=False)


def command_init(args: argparse.Namespace) -> int:
    root = _root(args)
    objective = args.objective.strip()
    if not objective:
        print("Objective must not be empty.", file=sys.stderr)
        return 2
    if args.session is not None and not args.session.strip():
        print("Supply the actual non-empty native session ID.", file=sys.stderr)
        return 2

    if args.task is not None:
        relative = task_record_relative_path(root, args.task)
        if relative == task_relative_path(args.task):
            task_dir = _destination(root, "tasks")
            if task_dir.exists() or task_dir.is_symlink():
                if not managed_tasks_directory(root):
                    raise ValueError("tasks/ exists but is not managed by task-state-with-files; choose a location with --file <relative-path>.")
            else:
                task_dir.mkdir()
                _write_new(_destination(root, "tasks/README.md"), TASKS_README)
        destination = _destination(root, relative)
    elif args.file is not None:
        relative = args.file
        destination = _destination(root, relative)
    else:
        relative = SESSION_STATE.as_posix()
        destination = _destination(root, relative)
        resolution = resolve_state(root, discover=False)
        if resolution.status not in {"found", "missing"}:
            print(f"Cannot initialize task state: {resolution.message}", file=sys.stderr)
            return 2
        if resolution.status == "found":
            _select_initialized(args, root, resolution.relative_path)
            print(resolution.relative_path)
            return 0

    if args.task is not None or args.file is not None:
        if destination.exists() or destination.is_symlink():
            existing = resolve_relative_target(root, relative)
            if existing.status != "found":
                raise ValueError(existing.message)
            ensure_runtime_directory(root)
            _select_initialized(args, root, relative)
            print(relative)
            return 0

    try:
        content = (TEMPLATE.read_text(encoding="utf-8")
                   .replace("{{TITLE}}", args.task or (destination.stem if args.file is not None else "session"))
                   .replace("{{OBJECTIVE}}", objective))
    except (OSError, UnicodeError) as exc:
        print(f"Cannot read the bundled state template: {exc}", file=sys.stderr)
        return 2

    if not _write_new(destination, content):
        resolution = resolve_relative_target(root, relative)
        if resolution.status != "found":
            print("Task state appeared concurrently but is not usable.", file=sys.stderr)
            return 2
    ensure_runtime_directory(root)
    _select_initialized(args, root, relative)
    print(relative)
    return 0


def _select_initialized(args: argparse.Namespace, root: Path, relative: str) -> None:
    if args.session is None:
        return
    try:
        selected = selected_record_from_root(root, root_pin=str(root), session_id=args.session)
    except (OSError, UnicodeError, RuntimeError):
        selected = None
    if selected is not None and selected.status == "found":
        if selected.path != resolve_relative_target(root, relative).path:
            common = [f"--session={args.session}", "--root", str(root)]
            cli = ["python3", str(Path(__file__).resolve())]
            deactivate = shlex.join([*cli, "deactivate", *common])
            activate = shlex.join([*cli, "activate", "--file", relative, *common])
            print(f"Session keeps {selected.relative_path}; to switch, run {deactivate} && {activate}", file=sys.stderr)
        return
    # Replace an unresolved binding without following its leaf symlink.
    binding = Path(session_relative_path(args.session))
    (_destination(root, binding.parent.as_posix()) / binding.name).unlink(missing_ok=True)
    try:
        legacy = Path(legacy_session_relative_path(args.session))
        (_destination(root, legacy.parent.as_posix()) / legacy.name).unlink(missing_ok=True)
    except (OSError, RuntimeError, ValueError):
        pass
    command_activate(argparse.Namespace(root=str(root), session=args.session, task=None, file=relative), announce=False)


def command_bind(args: argparse.Namespace) -> int:
    root = _root(args)
    target = resolve_relative_target(root, args.relative_path.strip())
    if target.status != "found" or target.relative_path is None:
        print(f"Cannot bind task state: {target.message}", file=sys.stderr)
        return 2

    direct = root.joinpath(*SESSION_STATE.parts)
    if direct.exists() or direct.is_symlink():
        print("Cannot bind task state while work/task-state.md exists.", file=sys.stderr)
        return 2

    binding = _destination(root, STATE_BINDING.as_posix())
    expected = target.relative_path + "\n"
    if binding.exists() or binding.is_symlink():
        try:
            current = binding.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            print("Existing task-state binding cannot be read.", file=sys.stderr)
            return 2
        if current != expected:
            print("A different task-state binding already exists.", file=sys.stderr)
            return 2
        print(STATE_BINDING.as_posix())
        return 0

    if not _write_new(binding, expected) and binding.read_text(encoding="utf-8") != expected:
        raise ValueError("A different task-state binding appeared concurrently.")
    print(STATE_BINDING.as_posix())
    return 0


def command_activate(args: argparse.Namespace, *, announce: bool = True) -> int:
    if args.task is None and args.file is None:
        raise ValueError("Activation requires --task or --file; automatic discovery is only for read/resolve.")
    selected = _selection(args)
    if selected.status != "found":
        raise ValueError(selected.message)
    relative = session_relative_path(args.session)
    binding = _destination(selected.root, relative)
    expected = selected.relative_path + "\n"
    candidates = [binding]
    try:
        legacy = _destination(selected.root, legacy_session_relative_path(args.session))
        if legacy.exists():
            candidates.append(legacy)
    except (OSError, RuntimeError, ValueError):
        pass
    for existing in candidates:
        if (existing.exists() or existing.is_symlink()) and existing.read_text(encoding="utf-8") != expected:
            raise ValueError("This session selected another record. Deactivate it before switching.")
    ensure_runtime_directory(selected.root)
    if not _write_new(binding, expected) and binding.read_text(encoding="utf-8") != expected:
        raise ValueError("This session selected another record. Deactivate it before switching.")
    if announce:
        print(relative)
    return 0


def command_deactivate(args: argparse.Namespace) -> int:
    root = _root(args)
    _destination(root, session_relative_path(args.session)).unlink(missing_ok=True)
    try:
        legacy = _destination(root, legacy_session_relative_path(args.session))
        legacy.unlink(missing_ok=True)
    except (OSError, RuntimeError, ValueError):
        pass
    return 0


def command_resolve(args: argparse.Namespace) -> int:
    resolution = _selection(args)
    payload = {
        "status": resolution.status,
        "relative_path": resolution.relative_path,
        "message": resolution.message,
        "candidates": list(resolution.candidates),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if resolution.status in {"found", "missing"} else 2


def command_read(args: argparse.Namespace) -> int:
    resolution = _selection(args)
    if resolution.status != "found":
        print(resolution.message or "No task state found. Supply the task ID, file, and project root from the handoff.", file=sys.stderr)
        if resolution.candidates:
            print("Candidates: " + ", ".join(resolution.candidates), file=sys.stderr)
        return 1 if resolution.status == "missing" else 2
    assert resolution.path is not None
    sys.stdout.write(resolution.path.read_text(encoding="utf-8"))
    return 0


def command_check(args: argparse.Namespace) -> int:
    resolution = _selection(args)
    if resolution.status != "found":
        print(resolution.message or "No task state found.", file=sys.stderr)
        if resolution.candidates:
            print("Candidates: " + ", ".join(resolution.candidates), file=sys.stderr)
        return 2
    text = resolution.path.read_text(encoding="utf-8")
    # Compare with the newest passing copy without advancing what hooks have seen,
    # so repeated checks of an unchanged record give the same answer.
    observation = observe(resolution, text, report=True, advance=False)
    if observation.problems:
        print(observation.report or format_sensor_report(resolution, observation.problems, advancing=False))
        return 1
    block = parse_current_state(text)
    detail = (f"current-state block {len(block.content)}/{CURRENT_STATE_LIMIT} characters"
              if block.status == "ok" else "no current-state block")
    print(f"OK: {resolution.relative_path} ({detail})")
    return 0


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="Pin the exact task root; default: discover ancestors up to the nearest Git boundary")


def _add_selection(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--task", help="Named task ID under tasks, with legacy .tasks fallback (or TASK_STATE_TASK)")
    selection.add_argument("--file", help="Exact task file relative to the task root (or TASK_STATE_FILE)")
    _add_root(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a task record once without overwriting existing work")
    init_parser.add_argument("--objective", required=True)
    _add_selection(init_parser)
    init_parser.add_argument("--session", help="Select the initialized record for this native session")
    init_parser.set_defaults(handler=command_init)

    bind_parser = subparsers.add_parser("bind", help="Bind a repository-shared state file")
    bind_parser.add_argument("relative_path")
    _add_root(bind_parser)
    bind_parser.set_defaults(handler=command_bind)

    resolve_parser = subparsers.add_parser("resolve", help="Inspect active task state")
    _add_selection(resolve_parser)
    resolve_parser.set_defaults(handler=command_resolve)

    read_parser = subparsers.add_parser("read", help="Read the complete selected task record without summarizing or truncating")
    _add_selection(read_parser)
    read_parser.set_defaults(handler=command_read)

    check_parser = subparsers.add_parser("check", help="Check factual integrity and keep the last passing copy")
    _add_selection(check_parser)
    check_parser.set_defaults(handler=command_check)

    activate_parser = subparsers.add_parser("activate", help="Select an existing record for one native session")
    _add_selection(activate_parser)
    activate_parser.add_argument("--session", required=True, help="Actual native session ID used in hook events")
    activate_parser.set_defaults(handler=command_activate)

    deactivate_parser = subparsers.add_parser("deactivate", help="Remove only this session's recovery selection")
    _add_root(deactivate_parser)
    deactivate_parser.add_argument("--session", required=True)
    deactivate_parser.set_defaults(handler=command_deactivate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
        print(f"Task-state operation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
