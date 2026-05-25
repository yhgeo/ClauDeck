from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme

from ui.main_window import PluginManagerWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="ClauDeck PyQt6 plugin manager")
    parser.add_argument("--claude-dir", type=Path, default=None, help="Override ~/.claude directory")
    parser.add_argument("--claude-bin", default="claude", help="Claude executable name or path")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("ClauDeck")
    app.setOrganizationName("ClauDeck")
    setTheme(Theme.LIGHT)

    window = PluginManagerWindow(claude_dir=args.claude_dir, claude_bin=args.claude_bin)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
