---
name: pyqt6-fluent-migration
description: Migrate the ClauDeck desktop UI from Tkinter to PyQt6 + Fluent while preserving the existing plugin business logic.
---

You are working on **ClauDeck**, a Python desktop tool for managing Claude Code plugins.

Your job is to help migrate the UI from **Tkinter/ttk** to **PyQt6 + Fluent** in a controlled way.

## Repository context

Current key files:
- `plugin_manager_ui.py` — existing Tkinter UI, currently the main migration source
- `plugin_store.py` — plugin data access, JSON read/write, uninstall, cache cleanup
- `plugin_sync.py` — `enabledPlugins` synchronization logic
- `settings_watcher.py` — watcher and auto-repair logic
- `sync_plugins.py` — one-shot sync entry
- `claude_wrapper.py` — startup wrapper

## Migration goals

- Replace the current Tkinter UI with a **PyQt6 + Fluent** desktop UI
- Keep **business logic unchanged whenever possible**
- Improve maintainability by separating:
  - app bootstrap
  - main window shell
  - left-side plugin list
  - right-side detail panel
  - action handlers / background tasks
- Preserve current behaviors:
  - load plugins
  - search/filter plugins
  - selection → detail sync
  - enable / disable
  - uninstall
  - one-shot sync

## Migration rules

1. **Preserve domain logic first**
   - Reuse `plugin_store.py` and `plugin_sync.py` unless a change is truly required.
   - Do not casually move UI concerns into these files.

2. **Treat `plugin_manager_ui.py` as the old UI only**
   - Do not port widget-by-widget blindly.
   - Extract UI concepts, then rebuild them using Qt idioms.

3. **Prefer Qt-native structure**
   - Prefer `QMainWindow`/Fluent window shell
   - Prefer `QSplitter` for left list + right detail
   - Prefer model/view for plugin lists when practical
   - Avoid recreating Tkinter-style manual widget bookkeeping if Qt has a better pattern

4. **Keep long-running actions off the UI thread**
   - Sync, uninstall, and other blocking work should move into workers / threads when implementing the Qt UI.

5. **Do not expand scope unnecessarily**
   - The migration is about replacing the UI layer, not rewriting watcher/sync systems.

## Recommended output style

When asked to plan or implement, structure your response around:
1. Reusable business logic
2. New Qt module layout
3. UI component mapping
4. Action / threading model
5. Incremental migration steps
6. Verification steps

## Strong defaults for this repo

If you need to recommend a structure, start from something like:
- `app.py`
- `ui/main_window.py`
- `ui/plugin_list_page.py`
- `ui/widgets/plugin_detail_panel.py`
- `ui/widgets/summary_cards.py`
- `viewmodels/plugin_list_model.py`
- `viewmodels/plugin_filter_proxy.py`
- `services/plugin_service.py`
- `services/tasks.py`

Use this as a migration guide, not a rigid rule, and keep the implementation as small as possible for the current task.
