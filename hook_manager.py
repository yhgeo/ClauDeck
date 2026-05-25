from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


MANAGED_HOOK_ID = "claudeck-plugin-sync-v1"


class HookManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class HookStatus:
    installed: bool
    stale: bool
    settings_path: Path
    command: str | None
    message: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["settings_path"] = str(self.settings_path)
        return payload


@dataclass(frozen=True)
class HookChangeResult:
    changed: bool
    status: HookStatus
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "status": self.status.to_dict(),
            "message": self.message,
        }


def get_project_dir() -> Path:
    return Path(__file__).resolve().parent


def get_user_settings_path(claude_dir: Path | None = None) -> Path:
    base_dir = Path(claude_dir).expanduser() if claude_dir else Path.home() / ".claude"
    return base_dir / "settings.json"


def read_settings(settings_path: Path) -> dict[str, Any]:
    if not settings_path.exists():
        return {}
    try:
        with settings_path.open("r", encoding="utf-8") as handle:
            settings = json.load(handle)
    except json.JSONDecodeError as exc:
        raise HookManagerError(f"Invalid JSON: {settings_path}\n{exc}") from exc
    except OSError as exc:
        raise HookManagerError(f"Failed to read file: {settings_path}\n{exc}") from exc

    if not isinstance(settings, dict):
        raise HookManagerError(f"Unexpected settings structure: {settings_path}")
    return settings


def write_settings(settings_path: Path, settings: dict[str, Any]) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=settings_path.name + ".", suffix=".tmp", dir=settings_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, settings_path)
    except OSError as exc:
        raise HookManagerError(f"Failed to write file: {settings_path}\n{exc}") from exc
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def build_hook_command(
    project_dir: Path | None = None,
    python_executable: str | None = None,
    claude_dir: Path | None = None,
) -> str:
    root = Path(project_dir).resolve() if project_dir else get_project_dir()
    manager_path = root / "hook_manager.py"
    python_path = python_executable or sys.executable
    command = [
        python_path,
        str(manager_path),
        "launch",
        "--managed-hook-id",
        MANAGED_HOOK_ID,
    ]
    if claude_dir is not None:
        command.extend(["--claude-dir", str(Path(claude_dir).expanduser())])
    return subprocess.list2cmdline(command)


def _session_start_entries(settings: dict[str, Any]) -> list[Any]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    entries = hooks.get("SessionStart")
    if not isinstance(entries, list):
        return []
    return entries


def _iter_command_hooks(settings: dict[str, Any]):
    for entry in _session_start_entries(settings):
        if not isinstance(entry, dict):
            continue
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            command = hook.get("command")
            if isinstance(command, str):
                yield hook, command


def get_hook_status(
    claude_dir: Path | None = None,
    project_dir: Path | None = None,
    python_executable: str | None = None,
) -> HookStatus:
    settings_path = get_user_settings_path(claude_dir)
    settings = read_settings(settings_path)
    expected_command = build_hook_command(project_dir, python_executable, claude_dir)

    for _hook, command in _iter_command_hooks(settings):
        if MANAGED_HOOK_ID not in command:
            continue
        stale = command != expected_command
        message = "自动同步 hook 路径已过期" if stale else "自动同步 hook 已安装"
        return HookStatus(
            installed=True,
            stale=stale,
            settings_path=settings_path,
            command=command,
            message=message,
        )

    return HookStatus(
        installed=False,
        stale=False,
        settings_path=settings_path,
        command=None,
        message="自动同步 hook 未安装",
    )


def _new_session_start_entry(command: str) -> dict[str, Any]:
    return {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "shell": "bash",
                "timeout": 10,
                "statusMessage": "启动 ClauDeck 插件同步守护进程",
            }
        ]
    }


def _remove_managed_hooks(settings: dict[str, Any]) -> int:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return 0
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        return 0

    removed = 0
    remaining_entries: list[Any] = []
    for entry in session_start:
        if not isinstance(entry, dict):
            remaining_entries.append(entry)
            continue
        entry_hooks = entry.get("hooks")
        if not isinstance(entry_hooks, list):
            remaining_entries.append(entry)
            continue

        remaining_hooks: list[Any] = []
        for hook in entry_hooks:
            command = hook.get("command") if isinstance(hook, dict) else None
            if isinstance(command, str) and MANAGED_HOOK_ID in command:
                removed += 1
                continue
            remaining_hooks.append(hook)

        if remaining_hooks:
            entry["hooks"] = remaining_hooks
            remaining_entries.append(entry)

    if remaining_entries:
        hooks["SessionStart"] = remaining_entries
    else:
        hooks.pop("SessionStart", None)

    if not hooks:
        settings.pop("hooks", None)
    return removed


def install_session_start_hook(
    claude_dir: Path | None = None,
    project_dir: Path | None = None,
    python_executable: str | None = None,
) -> HookChangeResult:
    root = Path(project_dir).resolve() if project_dir else get_project_dir()
    if not (root / "settings_watcher.py").exists():
        raise HookManagerError(f"settings_watcher.py not found: {root}")

    settings_path = get_user_settings_path(claude_dir)
    settings = read_settings(settings_path)
    command = build_hook_command(root, python_executable, claude_dir)
    before_status = get_hook_status(claude_dir, root, python_executable)

    if before_status.installed and not before_status.stale:
        return HookChangeResult(False, before_status, "自动同步 hook 已经安装")

    _remove_managed_hooks(settings)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        session_start = []
        hooks["SessionStart"] = session_start
    session_start.append(_new_session_start_entry(command))
    write_settings(settings_path, settings)

    status = get_hook_status(claude_dir, root, python_executable)
    return HookChangeResult(True, status, "自动同步 hook 已安装")


def remove_session_start_hook(
    claude_dir: Path | None = None,
    project_dir: Path | None = None,
    python_executable: str | None = None,
) -> HookChangeResult:
    settings_path = get_user_settings_path(claude_dir)
    settings = read_settings(settings_path)
    removed = _remove_managed_hooks(settings)
    if removed:
        write_settings(settings_path, settings)

    status = get_hook_status(claude_dir, project_dir, python_executable)
    message = "自动同步 hook 已移除" if removed else "没有找到 ClauDeck 自动同步 hook"
    return HookChangeResult(bool(removed), status, message)


def launch_watcher(claude_dir: Path | None = None) -> int:
    watcher_path = get_project_dir() / "settings_watcher.py"
    command = [sys.executable, str(watcher_path), "--quiet"]
    if claude_dir is not None:
        command.extend(["--claude-dir", str(Path(claude_dir).expanduser())])

    kwargs: dict[str, Any] = {
        "cwd": str(get_project_dir()),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen(command, **kwargs)
    return 0


def _print_payload(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        message = payload.get("message")
        print(message if isinstance(message, str) else payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage ClauDeck Claude Code SessionStart hook")
    parser.add_argument("--claude-dir", type=Path, default=None, help="Override ~/.claude directory")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show hook status")
    subparsers.add_parser("install", help="Install or update the SessionStart hook")
    subparsers.add_parser("remove", help="Remove the managed SessionStart hook")
    launch_parser = subparsers.add_parser("launch", help="Launch settings watcher and exit")
    launch_parser.add_argument("--managed-hook-id", required=True, help="Managed hook marker")

    args = parser.parse_args()

    try:
        if args.command == "status":
            status = get_hook_status(args.claude_dir)
            _print_payload({"ok": True, "status": status.to_dict(), "message": status.message}, args.json)
        elif args.command == "install":
            result = install_session_start_hook(args.claude_dir)
            _print_payload({"ok": True, **result.to_dict()}, args.json)
        elif args.command == "remove":
            result = remove_session_start_hook(args.claude_dir)
            _print_payload({"ok": True, **result.to_dict()}, args.json)
        elif args.command == "launch":
            if args.managed_hook_id != MANAGED_HOOK_ID:
                raise HookManagerError("Unexpected managed hook id")
            return launch_watcher(args.claude_dir)
    except HookManagerError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
