from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from plugin_store import ClaudePluginStore, StoreError
from plugin_sync import sync_enabled_plugins
from settings_watcher import WATCHER_STATUS_SCHEMA_VERSION, WATCHER_VERSION


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
class WatcherRuntimeStatus:
    running: bool
    stale: bool
    pid: int | None
    watcher_version: str | None
    status_path: Path
    log_path: Path
    last_heartbeat_at: str | None
    message: str

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["status_path"] = str(self.status_path)
        payload["log_path"] = str(self.log_path)
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


@dataclass(frozen=True)
class WatcherStopResult:
    changed: bool
    status: WatcherRuntimeStatus
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "status": self.status.to_dict(),
            "message": self.message,
        }


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_project_dir() -> Path:
    return Path(sys.executable).resolve().parent if is_frozen() else Path(__file__).resolve().parent


def get_user_settings_path(claude_dir: Path | None = None) -> Path:
    base_dir = Path(claude_dir).expanduser() if claude_dir else Path.home() / ".claude"
    return base_dir / "settings.json"


def get_watcher_status_path(claude_dir: Path | None = None) -> Path:
    base_dir = Path(claude_dir).expanduser() if claude_dir else Path.home() / ".claude"
    return base_dir / "logs" / "plugin_sync_watcher_status.json"


def get_watcher_log_path(claude_dir: Path | None = None) -> Path:
    base_dir = Path(claude_dir).expanduser() if claude_dir else Path.home() / ".claude"
    return base_dir / "logs" / "plugin_sync_watcher.log"


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


def _bash_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _to_bash_path(path: str | Path) -> str:
    raw = str(Path(path))
    if os.name != "nt":
        return raw
    normalized = raw.replace("\\", "/")
    if len(normalized) >= 2 and normalized[1] == ":":
        drive = normalized[0].lower()
        remainder = normalized[2:]
        return f"/{drive}{remainder}"
    return normalized


def build_hook_command(
    project_dir: Path | None = None,
    python_executable: str | None = None,
    claude_dir: Path | None = None,
    session_project_dir: Path | None = None,
) -> str:
    root = Path(project_dir).resolve() if project_dir else get_project_dir()
    if is_frozen():
        command = [
            _to_bash_path(root / Path(sys.executable).name),
            "--hook-manager",
            "launch",
            "--managed-hook-id",
            MANAGED_HOOK_ID,
        ]
    else:
        manager_path = root / "hook_manager.py"
        python_path = python_executable or sys.executable
        command = [
            _to_bash_path(python_path),
            _to_bash_path(manager_path),
            "launch",
            "--managed-hook-id",
            MANAGED_HOOK_ID,
        ]
    if claude_dir is not None:
        command.extend(["--claude-dir", _to_bash_path(Path(claude_dir).expanduser())])
    if session_project_dir is not None:
        command.extend(["--project-dir", _to_bash_path(Path(session_project_dir).expanduser())])
    return " ".join(_bash_quote(part) for part in command)


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
    session_project_dir: Path | None = None,
) -> HookStatus:
    settings_path = get_user_settings_path(claude_dir)
    settings = read_settings(settings_path)
    expected_command = build_hook_command(project_dir, python_executable, claude_dir, session_project_dir)

    for _hook, command in _iter_command_hooks(settings):
        if MANAGED_HOOK_ID not in command:
            continue
        stale = command != expected_command
        message = "会话启动 hook 路径已过期" if stale else "会话启动 hook 已安装"
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
        message="会话启动 hook 未安装",
    )


def get_watcher_status(claude_dir: Path | None = None) -> WatcherRuntimeStatus:
    status_path = get_watcher_status_path(claude_dir)
    log_path = get_watcher_log_path(claude_dir)
    if not status_path.exists():
        return WatcherRuntimeStatus(
            running=False,
            stale=False,
            pid=None,
            watcher_version=None,
            status_path=status_path,
            log_path=log_path,
            last_heartbeat_at=None,
            message="后台 watcher 未运行",
        )

    try:
        with status_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HookManagerError(f"Invalid watcher status: {status_path}\n{exc}") from exc

    if not isinstance(payload, dict):
        raise HookManagerError(f"Unexpected watcher status structure: {status_path}")

    pid = payload.get("pid") if isinstance(payload.get("pid"), int) else None
    running = bool(payload.get("running")) and pid is not None and _process_exists(pid)
    watcher_version = payload.get("watcher_version") if isinstance(payload.get("watcher_version"), str) else None
    last_heartbeat_at = payload.get("last_heartbeat_at") if isinstance(payload.get("last_heartbeat_at"), str) else None
    stale = watcher_version not in {None, WATCHER_VERSION}
    if running and stale:
        message = f"后台 watcher 运行中（PID {pid}，版本过旧）"
    elif running:
        message = f"后台 watcher 运行中（PID {pid}，版本 {watcher_version or 'unknown'}）"
    elif stale:
        message = "后台 watcher 未运行（上次记录版本过旧）"
    else:
        message = "后台 watcher 未运行"

    return WatcherRuntimeStatus(
        running=running,
        stale=stale,
        pid=pid,
        watcher_version=watcher_version,
        status_path=status_path,
        log_path=log_path,
        last_heartbeat_at=last_heartbeat_at,
        message=message,
    )


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return bool(ok) and exit_code.value == STILL_ACTIVE
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_process(pid: int) -> bool:
    if not _process_exists(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False

    for _ in range(10):
        if not _process_exists(pid):
            return True
        time.sleep(0.2)
    return not _process_exists(pid)


def _write_watcher_stopped_status(claude_dir: Path | None, previous_status: WatcherRuntimeStatus) -> None:
    status_path = previous_status.status_path
    log_path = previous_status.log_path
    payload: dict[str, Any] = {}
    if status_path.exists():
        try:
            with status_path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, json.JSONDecodeError):
            payload = {}

    now = datetime.now().isoformat(timespec="seconds")
    base_dir = Path(claude_dir).expanduser() if claude_dir else Path.home() / ".claude"
    payload.update(
        {
            "schema_version": WATCHER_STATUS_SCHEMA_VERSION,
            "watcher_version": WATCHER_VERSION,
            "running": False,
            "pid": previous_status.pid,
            "claude_dir": str(base_dir),
            "last_heartbeat_at": now,
            "log_path": str(log_path),
            "state": "stopped_by_user",
            "stopped_at": now,
            "last_error": None,
        }
    )

    try:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with status_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError:
        pass


def stop_watcher(claude_dir: Path | None = None) -> WatcherStopResult:
    status = get_watcher_status(claude_dir)
    if not status.running or status.pid is None:
        return WatcherStopResult(False, status, "后台 watcher 未运行")

    if not _terminate_process(status.pid):
        raise HookManagerError(f"无法停止后台 watcher（PID {status.pid}）")

    _write_watcher_stopped_status(claude_dir, status)
    return WatcherStopResult(True, get_watcher_status(claude_dir), f"后台 watcher 已停止（PID {status.pid}）")


def _new_session_start_entry(command: str) -> dict[str, Any]:
    return {
        "hooks": [
            {
                "type": "command",
                "command": command,
                "shell": "bash",
                "timeout": 10,
                "statusMessage": "同步 ClauDeck 插件并启动监听",
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
    session_project_dir: Path | None = None,
) -> HookChangeResult:
    root = Path(project_dir).resolve() if project_dir else get_project_dir()
    if not is_frozen() and not (root / "settings_watcher.py").exists():
        raise HookManagerError(f"settings_watcher.py not found: {root}")

    settings_path = get_user_settings_path(claude_dir)
    settings = read_settings(settings_path)
    command = build_hook_command(root, python_executable, claude_dir, session_project_dir)
    before_status = get_hook_status(claude_dir, root, python_executable, session_project_dir)

    if before_status.installed and not before_status.stale:
        return HookChangeResult(False, before_status, "会话启动 hook 已经安装")

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

    status = get_hook_status(claude_dir, root, python_executable, session_project_dir)
    return HookChangeResult(True, status, "会话启动 hook 已安装")


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
    message = "会话启动 hook 已移除" if removed else "没有找到 ClauDeck 会话启动 hook"
    return HookChangeResult(bool(removed), status, message)


def launch_watcher(claude_dir: Path | None = None, project_dir: Path | None = None) -> int:
    if is_frozen():
        command = [sys.executable, "--watcher", "--quiet"]
        cwd = str(get_project_dir())
    else:
        watcher_path = get_project_dir() / "settings_watcher.py"
        command = [sys.executable, str(watcher_path), "--quiet"]
        cwd = str(get_project_dir())
    if claude_dir is not None:
        command.extend(["--claude-dir", str(Path(claude_dir).expanduser())])
    if project_dir is not None:
        command.extend(["--project-dir", str(Path(project_dir).expanduser())])

    kwargs: dict[str, Any] = {
        "cwd": cwd,
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


def run_session_start_sync(claude_dir: Path | None = None, project_dir: Path | None = None) -> int:
    try:
        sync_enabled_plugins(ClaudePluginStore(claude_dir, project_dir))
    except StoreError as exc:
        raise HookManagerError(f"Plugin sync failed: {exc}") from exc
    try:
        launch_watcher(claude_dir, project_dir)
    except OSError:
        return 0
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
    parser.add_argument("--project-dir", type=Path, default=None, help="Override current project directory")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show hook status")
    subparsers.add_parser("install", help="Install or update the SessionStart hook")
    subparsers.add_parser("remove", help="Remove the managed SessionStart hook")
    subparsers.add_parser("stop-watcher", help="Stop the running settings watcher")
    launch_parser = subparsers.add_parser("launch", help="Launch settings watcher and exit")
    launch_parser.add_argument("--managed-hook-id", required=True, help="Managed hook marker")

    args = parser.parse_args()

    try:
        if args.command == "status":
            hook_status = get_hook_status(args.claude_dir, session_project_dir=args.project_dir)
            watcher_status = get_watcher_status(args.claude_dir)
            _print_payload(
                {
                    "ok": True,
                    "hook": hook_status.to_dict(),
                    "watcher": watcher_status.to_dict(),
                    "message": f"{hook_status.message}；{watcher_status.message}",
                },
                args.json,
            )
        elif args.command == "install":
            result = install_session_start_hook(args.claude_dir, session_project_dir=args.project_dir)
            _print_payload({"ok": True, **result.to_dict()}, args.json)
        elif args.command == "remove":
            result = remove_session_start_hook(args.claude_dir)
            _print_payload({"ok": True, **result.to_dict()}, args.json)
        elif args.command == "stop-watcher":
            result = stop_watcher(args.claude_dir)
            _print_payload({"ok": True, **result.to_dict()}, args.json)
        elif args.command == "launch":
            if args.managed_hook_id != MANAGED_HOOK_ID:
                raise HookManagerError("Unexpected managed hook id")
            return run_session_start_sync(args.claude_dir, args.project_dir)
    except HookManagerError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
