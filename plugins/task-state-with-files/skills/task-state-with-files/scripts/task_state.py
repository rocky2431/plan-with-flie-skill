#!/usr/bin/env python3
"""Small CLI for creating and binding file-backed task state."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from task_state_runtime import (
    SESSION_STATE,
    STATE_BINDING,
    resolve_relative_target,
    resolve_state,
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


def _replace_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root)


def command_init(args: argparse.Namespace) -> int:
    root = _root(args)
    objective = args.objective.strip()
    if not objective:
        print("Objective must not be empty.", file=sys.stderr)
        return 2

    resolution = resolve_state(root)
    if resolution.status == "invalid":
        print(f"Cannot initialize task state: {resolution.message}", file=sys.stderr)
        return 2
    if resolution.status == "found":
        print(resolution.relative_path)
        return 0

    try:
        content = TEMPLATE.read_text(encoding="utf-8").replace("{{OBJECTIVE}}", objective)
    except (OSError, UnicodeError) as exc:
        print(f"Cannot read the bundled state template: {exc}", file=sys.stderr)
        return 2

    destination = root.joinpath(*SESSION_STATE.parts)
    if not _write_new(destination, content):
        resolution = resolve_state(root)
        if resolution.status != "found":
            print("Task state appeared concurrently but is not usable.", file=sys.stderr)
            return 2
    print(SESSION_STATE.as_posix())
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

    binding = root.joinpath(*STATE_BINDING.parts)
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

    _replace_atomically(binding, expected)
    print(STATE_BINDING.as_posix())
    return 0


def command_resolve(args: argparse.Namespace) -> int:
    resolution = resolve_state(_root(args))
    payload = {
        "status": resolution.status,
        "relative_path": resolution.relative_path,
        "message": resolution.message,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if resolution.status != "invalid" else 2


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="Current task root (default: current directory)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create session-local task state once")
    init_parser.add_argument("--objective", required=True)
    _add_root(init_parser)
    init_parser.set_defaults(handler=command_init)

    bind_parser = subparsers.add_parser("bind", help="Bind a repository-shared state file")
    bind_parser.add_argument("relative_path")
    _add_root(bind_parser)
    bind_parser.set_defaults(handler=command_bind)

    resolve_parser = subparsers.add_parser("resolve", help="Inspect active task state")
    _add_root(resolve_parser)
    resolve_parser.set_defaults(handler=command_resolve)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
