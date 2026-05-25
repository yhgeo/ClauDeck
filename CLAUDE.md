# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development commands

Install GUI dependencies:

```bash
python -m pip install -r requirements.txt
```

Run the PyQt6 + Fluent desktop app:

```bash
python app.py
```

Run against a temporary or custom Claude config directory:

```bash
python app.py --claude-dir /path/to/.claude
```

Compile-check the maintained Python modules:

```bash
python -m py_compile app.py hook_manager.py plugin_content.py plugin_manager_ui.py plugin_store.py plugin_sync.py settings_watcher.py sync_plugins.py claude_wrapper.py ui/main_window.py ui/panels/plugin_list_panel.py ui/panels/plugin_detail_panel.py ui/widgets/plugin_card.py ui/widgets/summary_card.py ui/workers/tasks.py
```

Run a one-shot plugin sync:

```bash
python sync_plugins.py --json
```

Check sync health without writing:

```bash
python sync_plugins.py --check --json
```

Run the watcher once or continuously:

```bash
python settings_watcher.py --once --json
python settings_watcher.py
```

Manage the user-level Claude Code SessionStart hook:

```bash
python hook_manager.py status --json
python hook_manager.py install
python hook_manager.py remove
```

Build a Windows executable with PyInstaller:

```bash
python -m PyInstaller --noconfirm --clean --windowed --name ClauDeck --add-data "assets/claudeck.svg;assets" app.py
```

There is no dedicated test suite in this repository yet. Use focused temporary `.claude` directories plus the compile command and CLI smoke checks above when changing sync, watcher, hook, or packaging behavior. For UI work, also launch the GUI and verify the main flow manually when possible.

## Architecture overview

ClauDeck manages Claude Code plugins stored under a Claude config directory, normally `~/.claude`. The two core files are `plugins/installed_plugins.json` for installed plugin records and `settings.json` for `enabledPlugins`.

The GUI entrypoint is `app.py`. It normally starts `PluginManagerWindow`, but also dispatches packaged internal modes:

- `--hook-manager` delegates to `hook_manager.main()`
- `--watcher` delegates to `settings_watcher.main()`

This dispatch is required for PyInstaller builds, where the installed SessionStart hook should call `ClauDeck.exe --hook-manager launch ...` instead of referencing source files inside `_internal`.

`plugin_store.py` is the data access layer. It reads/writes Claude plugin registry and settings, builds `PluginView` objects, toggles plugins, uninstalls plugins, and cleans plugin cache/registry state. Changes to `enabledPlugins` should go through `ClaudePluginStore.update_enabled_plugins()` so unrelated settings such as API keys, base URLs, model/provider configuration, and environment variables are preserved during concurrent writes.

`plugin_sync.py` contains the shared sync logic. It adds installed plugin IDs that are missing from `enabledPlugins` and preserves existing disabled (`false`) plugins. Use this module from GUI, CLI, watcher, and wrapper paths rather than duplicating sync rules.

`settings_watcher.py` is a polling watcher for `settings.json` and `plugins/installed_plugins.json`. It uses a per-Claude-directory single-instance lock and writes logs to `~/.claude/logs/plugin_sync_watcher.log`.

`hook_manager.py` installs, updates, removes, and launches the managed user-level Claude Code `SessionStart` hook. It only manages commands containing the marker `claudeck-plugin-sync-v1`; do not remove or rewrite unrelated hooks. In source mode it generates a Python command for `hook_manager.py`; in frozen mode it generates an executable command for `ClauDeck.exe`.

`plugin_content.py` is a read-only plugin content browser helper. It discovers known plugin package content such as `.claude-plugin/plugin.json`, `README.md`, `skills/*/SKILL.md`, `commands/*.md`, and `agents/*.md`. It should not execute plugin content or read arbitrary paths outside discovered plugin roots.

The PyQt6 UI is split by responsibility:

- `ui/main_window.py` owns the store, selected plugin state, hook actions, sync/uninstall handlers, and background workers.
- `ui/panels/plugin_list_panel.py` renders the left-side search, summary cards, hook status/action, and plugin card list.
- `ui/panels/plugin_detail_panel.py` renders the right-side content browser for README, skills, commands, agents, and install records.
- `ui/widgets/plugin_card.py` renders plugin summary/action cards.
- `ui/widgets/summary_card.py` renders count summary cards.
- `ui/workers/tasks.py` provides `FunctionWorker` for running blocking work off the UI thread.

`plugin_manager_ui.py` is the old Tkinter implementation retained as a reference/fallback. Do not port widget-by-widget from it; keep new UI work in the PyQt6 modules unless specifically asked otherwise.

## Repository-specific notes

The shared project `.claude/settings.json` contains a development hook that compile-checks Python files after edits. `.claude/settings.local.json` is a local permissions file and must remain untracked.

The `.claude/skills/pyqt6-fluent-migration` skill and `.claude/agents` reviewers are intentionally tracked project automation for UI migration work. Use reviewer agents only for significant UI or architecture changes; skip them for small copy, style, or localized bug fixes to keep token usage low.

When changing plugin sync, watcher, or hook behavior, preserve unrelated user settings and hooks. The project exists partly to avoid model/provider switching breaking plugins, so never rewrite full Claude settings from a stale snapshot when an `enabledPlugins`-only update is sufficient.
