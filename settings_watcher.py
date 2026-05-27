from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from plugin_store import ClaudePluginStore, StoreError
from plugin_sync import sync_enabled_plugins


WATCHER_VERSION = "desired-state-v2"
WATCHER_STATUS_SCHEMA_VERSION = 1


class SingleInstanceLock:
    def __init__(self, claude_dir: Path) -> None:
        resolved_dir = str(claude_dir.resolve(strict=False)).lower()
        lock_id = hashlib.sha256(resolved_dir.encode("utf-8")).hexdigest()[:16]
        lock_name = f"claude-plugin-sync-{lock_id}.lock"
        self.lock_path = Path(tempfile.gettempdir()) / lock_name
        self.handle: object | None = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.lock_path.open("a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            return False

        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return True

    def read_pid(self) -> int | None:
        if not self.lock_path.exists():
            return None
        try:
            content = self.lock_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not content.isdigit():
            return None
        return int(content)

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.handle.close()
        self.handle = None


class WatcherLogger:
    def __init__(self, claude_dir: Path) -> None:
        self.log_dir = claude_dir / "logs"
        self.log_path = self.log_dir / "plugin_sync_watcher.log"
        self.status_path = self.log_dir / "plugin_sync_watcher_status.json"

    def log(self, event: str, **payload: Any) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **payload,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def write_status(self, **payload: Any) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        status = {
            "schema_version": WATCHER_STATUS_SCHEMA_VERSION,
            "watcher_version": WATCHER_VERSION,
            **payload,
        }
        with self.status_path.open("w", encoding="utf-8") as handle:
            json.dump(status, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

    def read_status(self) -> dict[str, Any] | None:
        if not self.status_path.exists():
            return None
        try:
            with self.status_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


def file_signature(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def emit(message: str, *, quiet: bool) -> None:
    if not quiet:
        print(message)
        sys.stdout.flush()


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
        return False
    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    for _ in range(10):
        if not _process_exists(pid):
            return True
        time.sleep(0.2)
    return not _process_exists(pid)


def _ensure_current_watcher(lock: SingleInstanceLock, logger: WatcherLogger, claude_dir: Path) -> bool:
    if lock.acquire():
        return True

    status = logger.read_status()
    stale_pid = None
    if status:
        pid = status.get("pid")
        version = status.get("watcher_version")
        status_claude_dir = status.get("claude_dir")
        if isinstance(pid, int) and status_claude_dir == str(claude_dir):
            if version != WATCHER_VERSION or not _process_exists(pid):
                stale_pid = pid
    else:
        pid = lock.read_pid()
        if pid is not None:
            stale_pid = pid

    if stale_pid is not None:
        logger.log("stale_watcher_detected", pid=stale_pid)
        _terminate_process(stale_pid)
        time.sleep(0.3)
        return lock.acquire()

    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch Claude settings and keep enabledPlugins in sync")
    parser.add_argument("--claude-dir", type=Path, default=None, help="Override ~/.claude directory")
    parser.add_argument("--project-dir", type=Path, default=None, help="Override current project directory")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Sync once and exit")
    parser.add_argument("--json", action="store_true", help="Emit change events as JSON lines")
    parser.add_argument("--quiet", action="store_true", help="Suppress normal log output")
    args = parser.parse_args()

    store = ClaudePluginStore(args.claude_dir, args.project_dir)
    logger = WatcherLogger(store.claude_dir)
    watched_paths = [store.installed_plugins_path, *store.watch_settings_paths()]
    lock = SingleInstanceLock(store.claude_dir)

    logger.log(
        "startup_requested",
        claude_dir=str(store.claude_dir),
        watched_paths=[str(path) for path in watched_paths],
        interval=args.interval,
        once=args.once,
        quiet=args.quiet,
        watcher_version=WATCHER_VERSION,
    )

    if not _ensure_current_watcher(lock, logger, store.claude_dir):
        logger.log("already_running", claude_dir=str(store.claude_dir))
        emit("Watcher already running.", quiet=args.quiet)
        return 0

    started_at = datetime.now().isoformat(timespec="seconds")
    logger.write_status(
        running=True,
        pid=os.getpid(),
        claude_dir=str(store.claude_dir),
        project_dir=str(store.project_dir) if store.project_dir else None,
        source_dir=str(Path(__file__).resolve().parent),
        python_executable=sys.executable,
        started_at=started_at,
        last_heartbeat_at=started_at,
        watched_paths=[str(path) for path in watched_paths],
        log_path=str(logger.log_path),
        state="starting",
        last_error=None,
    )

    last_heartbeat = time.time()

    try:
        try:
            initial = sync_enabled_plugins(store)
        except StoreError as exc:
            logger.log("startup_failed", error=str(exc))
            logger.write_status(
                running=False,
                pid=os.getpid(),
                claude_dir=str(store.claude_dir),
                project_dir=str(store.project_dir) if store.project_dir else None,
                source_dir=str(Path(__file__).resolve().parent),
                python_executable=sys.executable,
                started_at=started_at,
                last_heartbeat_at=datetime.now().isoformat(timespec="seconds"),
                watched_paths=[str(path) for path in watched_paths],
                log_path=str(logger.log_path),
                state="error",
                last_error=str(exc),
            )
            print(f"Watcher startup failed: {exc}", file=sys.stderr)
            return 1

        logger.log(
            "startup_sync",
            changed=initial.changed,
            mode=initial.state_sync_mode,
            corrected_plugin_ids=initial.corrected_plugin_ids,
            accepted_plugin_ids=initial.accepted_plugin_ids,
            desired_seeded_plugin_ids=initial.desired_seeded_plugin_ids,
            added_plugin_ids=initial.added_plugin_ids,
            restored_disabled_plugin_ids=initial.restored_disabled_plugin_ids,
            disabled_project_plugin_ids=initial.disabled_project_plugin_ids,
            skipped_project_plugin_ids=initial.skipped_project_plugin_ids,
            unknown_scope_plugin_ids=initial.unknown_scope_plugin_ids,
        )
        logger.write_status(
            running=not args.once,
            pid=os.getpid(),
            claude_dir=str(store.claude_dir),
            project_dir=str(store.project_dir) if store.project_dir else None,
            source_dir=str(Path(__file__).resolve().parent),
            python_executable=sys.executable,
            started_at=started_at,
            last_heartbeat_at=datetime.now().isoformat(timespec="seconds"),
            watched_paths=[str(path) for path in watched_paths],
            log_path=str(logger.log_path),
            state="running" if not args.once else "stopped",
            last_error=None,
        )

        if args.json:
            print(json.dumps({
                "event": "startup",
                "changed": initial.changed,
                "mode": initial.state_sync_mode,
                "corrected_plugin_ids": initial.corrected_plugin_ids,
                "accepted_plugin_ids": initial.accepted_plugin_ids,
                "desired_seeded_plugin_ids": initial.desired_seeded_plugin_ids,
                "added_plugin_ids": initial.added_plugin_ids,
                "restored_disabled_plugin_ids": initial.restored_disabled_plugin_ids,
                "disabled_project_plugin_ids": initial.disabled_project_plugin_ids,
                "skipped_project_plugin_ids": initial.skipped_project_plugin_ids,
                "unknown_scope_plugin_ids": initial.unknown_scope_plugin_ids,
            }, ensure_ascii=False))
            sys.stdout.flush()
        else:
            emit(
                "Startup sync "
                f"mode={initial.state_sync_mode} "
                f"changed={initial.changed} "
                f"corrected={len(initial.corrected_plugin_ids)} "
                f"accepted={len(initial.accepted_plugin_ids)} "
                f"added={len(initial.added_plugin_ids)} "
                f"restored_disabled={len(initial.restored_disabled_plugin_ids)} "
                f"disabled_project={len(initial.disabled_project_plugin_ids)} "
                f"skipped_project={len(initial.skipped_project_plugin_ids)}",
                quiet=args.quiet,
            )

        if args.once:
            logger.log("exit_once")
            return 0

        signatures = {path: file_signature(path) for path in watched_paths}

        while True:
            time.sleep(args.interval)
            if time.time() - last_heartbeat >= 10:
                last_heartbeat = time.time()
                logger.write_status(
                    running=True,
                    pid=os.getpid(),
                    claude_dir=str(store.claude_dir),
                    project_dir=str(store.project_dir) if store.project_dir else None,
                    source_dir=str(Path(__file__).resolve().parent),
                    python_executable=sys.executable,
                    started_at=started_at,
                    last_heartbeat_at=datetime.now().isoformat(timespec="seconds"),
                    watched_paths=[str(path) for path in watched_paths],
                    log_path=str(logger.log_path),
                    state="running",
                    last_error=None,
                )

            changed_paths: list[str] = []
            for path in watched_paths:
                current_signature = file_signature(path)
                if current_signature != signatures[path]:
                    signatures[path] = current_signature
                    changed_paths.append(str(path))

            if not changed_paths:
                continue

            logger.log("file_change_detected", changed_paths=changed_paths)

            try:
                result = sync_enabled_plugins(store)
                signatures = {path: file_signature(path) for path in watched_paths}
            except StoreError as exc:
                logger.log("sync_failed", changed_paths=changed_paths, error=str(exc))
                logger.write_status(
                    running=True,
                    pid=os.getpid(),
                    claude_dir=str(store.claude_dir),
                    project_dir=str(store.project_dir) if store.project_dir else None,
                    source_dir=str(Path(__file__).resolve().parent),
                    python_executable=sys.executable,
                    started_at=started_at,
                    last_heartbeat_at=datetime.now().isoformat(timespec="seconds"),
                    watched_paths=[str(path) for path in watched_paths],
                    log_path=str(logger.log_path),
                    state="error",
                    last_error=str(exc),
                )
                print(f"Watcher sync failed: {exc}", file=sys.stderr)
                continue

            logger.log(
                "sync_completed",
                changed_paths=changed_paths,
                changed=result.changed,
                mode=result.state_sync_mode,
                corrected_plugin_ids=result.corrected_plugin_ids,
                accepted_plugin_ids=result.accepted_plugin_ids,
                desired_seeded_plugin_ids=result.desired_seeded_plugin_ids,
                added_plugin_ids=result.added_plugin_ids,
                restored_disabled_plugin_ids=result.restored_disabled_plugin_ids,
                disabled_project_plugin_ids=result.disabled_project_plugin_ids,
                skipped_project_plugin_ids=result.skipped_project_plugin_ids,
                unknown_scope_plugin_ids=result.unknown_scope_plugin_ids,
            )
            logger.write_status(
                running=True,
                pid=os.getpid(),
                claude_dir=str(store.claude_dir),
                project_dir=str(store.project_dir) if store.project_dir else None,
                source_dir=str(Path(__file__).resolve().parent),
                python_executable=sys.executable,
                started_at=started_at,
                last_heartbeat_at=datetime.now().isoformat(timespec="seconds"),
                watched_paths=[str(path) for path in watched_paths],
                log_path=str(logger.log_path),
                state="running",
                last_error=None,
            )

            if args.json:
                print(json.dumps({
                    "event": "sync",
                    "changed_paths": changed_paths,
                    "changed": result.changed,
                    "mode": result.state_sync_mode,
                    "corrected_plugin_ids": result.corrected_plugin_ids,
                    "accepted_plugin_ids": result.accepted_plugin_ids,
                    "desired_seeded_plugin_ids": result.desired_seeded_plugin_ids,
                    "added_plugin_ids": result.added_plugin_ids,
                    "restored_disabled_plugin_ids": result.restored_disabled_plugin_ids,
                    "disabled_project_plugin_ids": result.disabled_project_plugin_ids,
                    "skipped_project_plugin_ids": result.skipped_project_plugin_ids,
                    "unknown_scope_plugin_ids": result.unknown_scope_plugin_ids,
                }, ensure_ascii=False))
                sys.stdout.flush()
            else:
                emit(
                    f"Detected changes in {', '.join(changed_paths)} | "
                    f"mode={result.state_sync_mode} "
                    f"sync changed={result.changed} "
                    f"corrected={len(result.corrected_plugin_ids)} "
                    f"accepted={len(result.accepted_plugin_ids)} "
                    f"added={len(result.added_plugin_ids)} "
                    f"restored_disabled={len(result.restored_disabled_plugin_ids)} "
                    f"disabled_project={len(result.disabled_project_plugin_ids)} "
                    f"skipped_project={len(result.skipped_project_plugin_ids)}",
                    quiet=args.quiet,
                )
    finally:
        logger.log("shutdown")
        logger.write_status(
            running=False,
            pid=os.getpid(),
            claude_dir=str(store.claude_dir),
            project_dir=str(store.project_dir) if store.project_dir else None,
            source_dir=str(Path(__file__).resolve().parent),
            python_executable=sys.executable,
            started_at=started_at,
            last_heartbeat_at=datetime.now().isoformat(timespec="seconds"),
            watched_paths=[str(path) for path in watched_paths],
            log_path=str(logger.log_path),
            state="stopped",
            last_error=None,
        )
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
