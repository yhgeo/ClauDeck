from __future__ import annotations

import argparse
import sys
from pathlib import Path

import hook_manager
import settings_watcher
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme

from ui.main_window import PluginManagerWindow


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def load_app_icon() -> QIcon:
    icon_path = resource_path("assets", "claudeck.svg")
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--hook-manager":
        sys.argv.pop(1)
        return hook_manager.main()
    if len(sys.argv) > 1 and sys.argv[1] == "--watcher":
        sys.argv.pop(1)
        return settings_watcher.main()

    parser = argparse.ArgumentParser(description="ClauDeck PyQt6 plugin manager")
    parser.add_argument("--claude-dir", type=Path, default=None, help="Override ~/.claude directory")
    parser.add_argument("--claude-bin", default="claude", help="Claude executable name or path")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("ClauDeck")
    app.setOrganizationName("ClauDeck")
    setTheme(Theme.LIGHT)
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = PluginManagerWindow(claude_dir=args.claude_dir, claude_bin=args.claude_bin)
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
