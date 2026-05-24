from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from plugin_store import ClaudePluginStore, StoreError
from plugin_sync import sync_enabled_plugins


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync plugins, then forward to claude")
    parser.add_argument("--claude-dir", type=Path, default=None, help="Override ~/.claude directory")
    parser.add_argument("--claude-bin", default="claude", help="Claude executable name or path")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to claude")
    args = parser.parse_args()

    claude_bin = shutil.which(args.claude_bin) or args.claude_bin
    store = ClaudePluginStore(args.claude_dir)

    try:
        sync_enabled_plugins(store)
    except StoreError as exc:
        print(f"Plugin sync failed: {exc}", file=sys.stderr)
        return 1

    forwarded_args = args.args[1:] if args.args and args.args[0] == "--" else args.args
    command = [claude_bin, *forwarded_args]
    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
