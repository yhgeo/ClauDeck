from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from plugin_store import ClaudePluginStore, StoreError
from plugin_sync import plugin_sync_health, sync_enabled_plugins


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Claude enabledPlugins with installed plugins")
    parser.add_argument("--claude-dir", type=Path, default=None, help="Override ~/.claude directory")
    parser.add_argument("--check", action="store_true", help="Only print sync health without writing")
    parser.add_argument("--json", action="store_true", help="Print result as JSON")
    args = parser.parse_args()

    store = ClaudePluginStore(args.claude_dir)

    try:
        if args.check:
            payload = plugin_sync_health(store)
        else:
            result = sync_enabled_plugins(store)
            payload = {
                "changed": result.changed,
                "added_plugin_ids": result.added_plugin_ids,
                "normalized_enabled_plugins": result.normalized_enabled_plugins,
            }
    except StoreError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
