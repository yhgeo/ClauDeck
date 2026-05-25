from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from plugin_store import ClaudePluginStore, StoreError
from plugin_sync import sync_enabled_plugins


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

    def log(self, event: str, **payload: Any) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **payload,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def file_signature(path: Path) -> tuple[int, int] | None:
    if not path.exists():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def emit(message: str, *, quiet: bool) -> None:
    if not quiet:
        print(message)
        sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch Claude settings and keep enabledPlugins in sync")
    parser.add_argument("--claude-dir", type=Path, default=None, help="Override ~/.claude directory")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Sync once and exit")
    parser.add_argument("--json", action="store_true", help="Emit change events as JSON lines")
    parser.add_argument("--quiet", action="store_true", help="Suppress normal log output")
    args = parser.parse_args()

    store = ClaudePluginStore(args.claude_dir)
    logger = WatcherLogger(store.claude_dir)
    watched_paths = [store.settings_path, store.installed_plugins_path]
    lock = SingleInstanceLock(store.claude_dir)

    logger.log(
        "startup_requested",
        claude_dir=str(store.claude_dir),
        watched_paths=[str(path) for path in watched_paths],
        interval=args.interval,
        once=args.once,
        quiet=args.quiet,
    )

    if not lock.acquire():
        logger.log("already_running", claude_dir=str(store.claude_dir))
        emit("Watcher already running.", quiet=args.quiet)
        return 0

    try:
        try:
            initial = sync_enabled_plugins(store)
        except StoreError as exc:
            logger.log("startup_failed", error=str(exc))
            print(f"Watcher startup failed: {exc}", file=sys.stderr)
            return 1

        logger.log(
            "startup_sync",
            changed=initial.changed,
            added_plugin_ids=initial.added_plugin_ids,
        )

        if args.json:
            print(json.dumps({
                "event": "startup",
                "changed": initial.changed,
                "added_plugin_ids": initial.added_plugin_ids,
            }, ensure_ascii=False))
            sys.stdout.flush()
        else:
            emit(f"Startup sync changed={initial.changed} added={len(initial.added_plugin_ids)}", quiet=args.quiet)

        if args.once:
            logger.log("exit_once")
            return 0

        signatures = {path: file_signature(path) for path in watched_paths}

        while True:
            time.sleep(args.interval)
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
                print(f"Watcher sync failed: {exc}", file=sys.stderr)
                continue

            logger.log(
                "sync_completed",
                changed_paths=changed_paths,
                changed=result.changed,
                added_plugin_ids=result.added_plugin_ids,
            )

            if args.json:
                print(json.dumps({
                    "event": "sync",
                    "changed_paths": changed_paths,
                    "changed": result.changed,
                    "added_plugin_ids": result.added_plugin_ids,
                }, ensure_ascii=False))
                sys.stdout.flush()
            else:
                emit(
                    f"Detected changes in {', '.join(changed_paths)} | "
                    f"sync changed={result.changed} added={len(result.added_plugin_ids)}",
                    quiet=args.quiet,
                )
    finally:
        logger.log("shutdown")
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
