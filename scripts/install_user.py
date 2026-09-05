#!/usr/bin/env python3
"""Install task-state-with-files into supported agent CLIs at user scope."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import tomllib
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_SOURCE = (
    REPO_ROOT
    / "plugins"
    / "task-state-with-files"
    / "skills"
    / "task-state-with-files"
)
SUPPORTED_HOSTS = ("kimi", "zcode", "claude", "hermes")
MANAGED_HOOK_FRAGMENT = "task-state-with-files/scripts/lifecycle_hook.py"
KIMI_BLOCK_BEGIN = "# BEGIN task-state-with-files managed hooks"
KIMI_BLOCK_END = "# END task-state-with-files managed hooks"


def _kimi_root(home: Path) -> Path:
    return Path(os.environ.get("KIMI_CODE_HOME") or home / ".kimi-code").expanduser()


def _skill_destination(home: Path, host: str) -> Path:
    roots = {
        "kimi": _kimi_root(home) / "skills",
        "zcode": home / ".zcode" / "skills",
        "claude": home / ".claude" / "skills",
        "hermes": home / ".hermes" / "skills",
    }
    return roots[host] / "task-state-with-files"


def _config_path(home: Path, host: str) -> Path | None:
    paths = {
        "kimi": _kimi_root(home) / "config.toml",
        "zcode": home / ".zcode" / "cli" / "config.json",
        "claude": home / ".claude" / "settings.json",
        "hermes": None,
    }
    return paths[host]


def _hook_command(host: str) -> str:
    if host == "kimi":
        return ('python3 "${KIMI_CODE_HOME:-$HOME/.kimi-code}/skills/'
                'task-state-with-files/scripts/lifecycle_hook.py" --host kimi')
    roots = {
        "zcode": ".zcode",
        "claude": ".claude",
    }
    return (
        f'python3 "$HOME/{roots[host]}/skills/task-state-with-files/'
        f'scripts/lifecycle_hook.py" --host {host}'
    )


def _parse_hosts(raw: str) -> list[str]:
    hosts: list[str] = []
    for item in raw.split(","):
        host = item.strip().lower()
        if not host or host in hosts:
            continue
        if host not in SUPPORTED_HOSTS:
            raise ValueError(
                f"Unsupported host {host!r}; choose from {', '.join(SUPPORTED_HOSTS)}."
            )
        hosts.append(host)
    if not hosts:
        raise ValueError("At least one host is required.")
    return hosts


def _default_backup_dir(home: Path, operation: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return (
        home
        / ".local"
        / "state"
        / "task-state-with-files"
        / "backups"
        / f"{stamp}-{operation}"
    )


def _copy_backup(source: Path, destination: Path) -> None:
    if not source.exists() and not source.is_symlink():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        return
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination, follow_symlinks=False)


def _backup_host(home: Path, host: str, backup_dir: Path) -> None:
    _copy_backup(_skill_destination(home, host), backup_dir / host / "skill")
    config = _config_path(home, host)
    if config is not None:
        _copy_backup(config, backup_dir / host / config.name)


def _replace_skill(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(
        tempfile.mkdtemp(prefix=".task-state-with-files-", dir=destination.parent)
    )
    staged = staging_parent / destination.name
    retired = staging_parent / "previous"
    try:
        shutil.copytree(SKILL_SOURCE, staged)
        if destination.exists() or destination.is_symlink():
            destination.rename(retired)
        staged.rename(destination)
    except Exception:
        if not destination.exists() and retired.exists():
            retired.rename(destination)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, mode)
        else:
            os.chmod(temporary_path, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _strip_kimi_block(text: str) -> str:
    begin = text.find(KIMI_BLOCK_BEGIN)
    end = text.find(KIMI_BLOCK_END)
    if begin == -1 and end == -1:
        return text
    if begin == -1 or end == -1 or end < begin:
        raise ValueError("The managed Kimi hook block is malformed; restore or remove it first.")
    end += len(KIMI_BLOCK_END)
    return (text[:begin] + text[end:]).strip() + "\n"


def _kimi_block() -> str:
    command = _hook_command("kimi")
    return f'''{KIMI_BLOCK_BEGIN}
[[hooks]]
event = "UserPromptSubmit"
command = '{command}'
timeout = 10
{KIMI_BLOCK_END}
'''


def _prepare_kimi_base(text: str) -> str:
    """Remove the generated empty top-level `hooks = []` before adding AoT hooks."""

    base = _strip_kimi_block(text)
    lines = base.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            break
        if not stripped.startswith("hooks") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() != "hooks":
            continue
        if value.strip() == "[]":
            del lines[index]
            return "".join(lines)
        raise ValueError(
            "Kimi inline hooks must be converted to [[hooks]] tables before this "
            "installer can merge another entry safely."
        )
    return base


def _install_kimi_config(path: Path) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    base = _prepare_kimi_base(current).rstrip()
    updated = (base + "\n\n" if base else "") + _kimi_block()
    tomllib.loads(updated)
    _atomic_write(path, updated)


def _uninstall_kimi_config(path: Path) -> None:
    if not path.exists():
        return
    current = path.read_text(encoding="utf-8")
    updated = _strip_kimi_block(current)
    tomllib.loads(updated)
    _atomic_write(path, updated)


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def _remove_managed_groups(groups: object) -> list[dict[str, Any]]:
    if groups is None:
        return []
    if not isinstance(groups, list):
        raise ValueError("Expected a hook event to contain a list.")

    kept_groups: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("Expected every hook group to be an object.")
        hooks = group.get("hooks", [])
        if not isinstance(hooks, list):
            raise ValueError("Expected a hook group to contain a hooks list.")
        kept_hooks = [
            hook
            for hook in hooks
            if not (
                isinstance(hook, dict)
                and MANAGED_HOOK_FRAGMENT in str(hook.get("command", ""))
            )
        ]
        if kept_hooks:
            copy = dict(group)
            copy["hooks"] = kept_hooks
            kept_groups.append(copy)
    return kept_groups


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _install_zcode_config(path: Path) -> None:
    config = _read_json_object(path)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("ZCode hooks configuration must be an object.")
    hooks["enabled"] = True
    events = hooks.setdefault("events", {})
    if not isinstance(events, dict):
        raise ValueError("ZCode hooks.events configuration must be an object.")
    groups = _remove_managed_groups(events.get("SessionStart"))
    groups.append(
        {
            "matcher": "^(startup|resume|clear|compact)$",
            "hooks": [
                {
                    "type": "command",
                    "command": _hook_command("zcode"),
                    "timeout": 10,
                    "statusMessage": "Restoring local task state",
                }
            ],
        }
    )
    events["SessionStart"] = groups
    _write_json(path, config)


def _uninstall_zcode_config(path: Path) -> None:
    if not path.exists():
        return
    config = _read_json_object(path)
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return
    events = hooks.get("events")
    if not isinstance(events, dict):
        return
    groups = _remove_managed_groups(events.get("SessionStart"))
    if groups:
        events["SessionStart"] = groups
    else:
        events.pop("SessionStart", None)
    _write_json(path, config)


def _install_claude_config(path: Path) -> None:
    config = _read_json_object(path)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("Claude Code hooks configuration must be an object.")
    groups = _remove_managed_groups(hooks.get("SessionStart"))
    groups.append(
        {
            "matcher": "^(startup|resume|clear|compact)$",
            "hooks": [
                {
                    "type": "command",
                    "command": _hook_command("claude"),
                    "timeout": 10,
                    "statusMessage": "Restoring local task state",
                }
            ],
        }
    )
    hooks["SessionStart"] = groups
    _write_json(path, config)


def _uninstall_claude_config(path: Path) -> None:
    if not path.exists():
        return
    config = _read_json_object(path)
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return
    groups = _remove_managed_groups(hooks.get("SessionStart"))
    if groups:
        hooks["SessionStart"] = groups
    else:
        hooks.pop("SessionStart", None)
    _write_json(path, config)


def _install_config(home: Path, host: str) -> None:
    path = _config_path(home, host)
    if host == "kimi" and path is not None:
        _install_kimi_config(path)
    elif host == "zcode" and path is not None:
        _install_zcode_config(path)
    elif host == "claude" and path is not None:
        _install_claude_config(path)


def _uninstall_config(home: Path, host: str) -> None:
    path = _config_path(home, host)
    if host == "kimi" and path is not None:
        _uninstall_kimi_config(path)
    elif host == "zcode" and path is not None:
        _uninstall_zcode_config(path)
    elif host == "claude" and path is not None:
        _uninstall_claude_config(path)


def _preflight_config(home: Path, host: str) -> None:
    path = _config_path(home, host)
    if path is None:
        return
    if host == "kimi":
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        base = _prepare_kimi_base(current).rstrip()
        candidate = (base + "\n\n" if base else "") + _kimi_block()
        parsed = tomllib.loads(candidate)
        hooks = parsed.get("hooks", [])
        if not isinstance(hooks, list) or not all(
            isinstance(item, dict) for item in hooks
        ):
            raise ValueError("Kimi hooks configuration must be an array of tables.")
        return

    config = _read_json_object(path)
    hooks = config.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise ValueError(f"{host} hooks configuration must be an object.")
    if not isinstance(hooks, dict):
        return
    if host == "zcode":
        events = hooks.get("events")
        if events is not None and not isinstance(events, dict):
            raise ValueError("ZCode hooks.events configuration must be an object.")
        if isinstance(events, dict):
            _remove_managed_groups(events.get("SessionStart"))
    else:
        _remove_managed_groups(hooks.get("SessionStart"))


def _tree_digest(root: Path) -> str | None:
    if not root.is_dir():
        return None
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _hook_count(home: Path, host: str) -> int:
    path = _config_path(home, host)
    if path is None or not path.exists():
        return 0
    if host == "kimi":
        config = tomllib.loads(path.read_text(encoding="utf-8"))
        hooks = config.get("hooks", [])
        if not isinstance(hooks, list):
            return 0
        return sum(
            item.get("event") == "UserPromptSubmit"
            and item.get("command") == _hook_command("kimi")
            for item in hooks
            if isinstance(item, dict)
        )
    config = _read_json_object(path)
    if host == "zcode":
        groups = ((config.get("hooks") or {}).get("events") or {}).get(
            "SessionStart", []
        )
    else:
        groups = (config.get("hooks") or {}).get("SessionStart", [])
    count = 0
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []):
                if isinstance(hook, dict) and MANAGED_HOOK_FRAGMENT in str(
                    hook.get("command", "")
                ):
                    count += 1
    return count


def _doctor(home: Path, hosts: list[str]) -> dict[str, object]:
    source_digest = _tree_digest(SKILL_SOURCE)
    results: dict[str, dict[str, str]] = {}
    healthy = True
    for host in hosts:
        destination = _skill_destination(home, host)
        skill_status = "ok" if _tree_digest(destination) == source_digest else "missing-or-drifted"
        if host == "hermes":
            hook_status = "not-applicable"
            recovery = "skill-only"
        else:
            hook_status = "ok" if _hook_count(home, host) == 1 else "missing-or-duplicate"
            recovery = "user-prompt" if host == "kimi" else "native"
        if skill_status != "ok" or hook_status not in {"ok", "not-applicable"}:
            healthy = False
        results[host] = {
            "skill": skill_status,
            "hook": hook_status,
            "recovery": recovery,
        }
    return {"ok": healthy, "hosts": results}


def _install(home: Path, hosts: list[str], backup_dir: Path) -> None:
    if not (SKILL_SOURCE / "SKILL.md").is_file():
        raise ValueError(f"Bundled Skill is missing from {SKILL_SOURCE}.")
    for host in hosts:
        _preflight_config(home, host)
    for host in hosts:
        _backup_host(home, host, backup_dir)
    for host in hosts:
        _replace_skill(_skill_destination(home, host))
        _install_config(home, host)


def _uninstall(home: Path, hosts: list[str], backup_dir: Path) -> None:
    for host in hosts:
        _backup_host(home, host, backup_dir)
        _uninstall_config(home, host)
        destination = _skill_destination(home, host)
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)


def _add_common(parser: argparse.ArgumentParser, *, backup: bool) -> None:
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="User home containing host configuration (default: current user home)",
    )
    parser.add_argument(
        "--hosts",
        default=",".join(SUPPORTED_HOSTS),
        help="Comma-separated hosts: kimi,zcode,claude,hermes",
    )
    if backup:
        parser.add_argument(
            "--backup-dir",
            type=Path,
            help="Exact recovery-copy directory (default: user state directory)",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install", help="Install or update selected user-scope hosts")
    _add_common(install, backup=True)
    uninstall = commands.add_parser(
        "uninstall", help="Remove only this package's Skill copies and managed hooks"
    )
    _add_common(uninstall, backup=True)
    doctor = commands.add_parser("doctor", help="Verify installed Skill copies and hooks")
    _add_common(doctor, backup=False)
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    home = args.home.expanduser().resolve()
    try:
        hosts = _parse_hosts(args.hosts)
        if args.command == "doctor":
            report = _doctor(home, hosts)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                for host, status in report["hosts"].items():
                    print(
                        f"{host}: skill={status['skill']} hook={status['hook']} "
                        f"recovery={status['recovery']}"
                    )
            return 0 if report["ok"] else 1

        backup_dir = (
            args.backup_dir.expanduser().resolve()
            if args.backup_dir
            else _default_backup_dir(home, args.command)
        )
        if args.command == "install":
            _install(home, hosts, backup_dir)
            print(f"Installed for: {', '.join(hosts)}")
        else:
            _uninstall(home, hosts, backup_dir)
            print(f"Uninstalled for: {', '.join(hosts)}")
        print(f"Recovery copies: {backup_dir}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
