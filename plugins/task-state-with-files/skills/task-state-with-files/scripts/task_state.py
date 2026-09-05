#!/usr/bin/env python3
"""Create, locate, and read file-backed task working notes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from task_state_runtime import (
    SESSION_STATE,
    STATE_BINDING,
    Resolution,
    find_task_root,
    resolve_relative_target,
    resolve_state,
    task_relative_path,
)


SKILL_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL_ROOT / "assets" / "task-state-template.md"


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
    destination = root / relative
    if not destination.resolve().is_relative_to(root):
        raise ValueError("The state destination resolves outside the task root.")
    return destination


def _selection(args: argparse.Namespace) -> Resolution:
    state_file = getattr(args, "file", None)
    task = args.task if args.task is not None else (None if state_file else os.environ.get("TASK_STATE_TASK"))
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

    if args.task is not None:
        relative = task_relative_path(args.task)
        destination = _destination(root, relative)
        if destination.exists() or destination.is_symlink():
            existing = resolve_relative_target(root, relative)
            if existing.status != "found":
                raise ValueError(existing.message)
            print(relative)
            return 0
    else:
        relative = SESSION_STATE.as_posix()
        destination = _destination(root, relative)
        resolution = resolve_state(root, discover=False)
        if resolution.status not in {"found", "missing"}:
            print(f"Cannot initialize task state: {resolution.message}", file=sys.stderr)
            return 2
        if resolution.status == "found":
            print(resolution.relative_path)
            return 0

    try:
        content = (TEMPLATE.read_text(encoding="utf-8")
                   .replace("{{TASK_ID}}", args.task or "session")
                   .replace("{{STATE_PATH}}", relative)
                   .replace("{{OBJECTIVE}}", objective))
    except (OSError, UnicodeError) as exc:
        print(f"Cannot read the bundled state template: {exc}", file=sys.stderr)
        return 2

    if not _write_new(destination, content):
        resolution = resolve_relative_target(root, relative)
        if resolution.status != "found":
            print("Task state appeared concurrently but is not usable.", file=sys.stderr)
            return 2
    print(relative)
    return 0


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


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="Pin the exact task root; default: discover ancestors up to the nearest Git boundary")


def _add_selection(parser: argparse.ArgumentParser) -> None:
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--task", help="Named task ID under .tasks (or TASK_STATE_TASK)")
    selection.add_argument("--file", help="Exact task file relative to the task root")
    _add_root(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a task record once without overwriting existing work")
    init_parser.add_argument("--objective", required=True)
    init_parser.add_argument("--task", help="Create a named .tasks/<id>.md record; omission retains legacy session storage")
    _add_root(init_parser)
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
