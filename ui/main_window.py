from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QSplitter, QStatusBar, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, TitleLabel, TransparentToolButton

from hook_manager import (
    HookChangeResult,
    HookManagerError,
    HookStatus,
    WatcherRuntimeStatus,
    WatcherStopResult,
    get_hook_status,
    get_watcher_status,
    install_session_start_hook,
    remove_session_start_hook,
    run_session_start_sync,
    stop_watcher as stop_running_watcher,
)
from plugin_content import PluginContentBundle, discover_plugin_content
from plugin_store import ClaudePluginStore, PluginView, StoreError
from plugin_sync import sync_enabled_plugins
from ui.panels.plugin_detail_panel import PluginDetailPanel
from ui.panels.plugin_list_panel import PluginListPanel
from ui.workers.tasks import FunctionWorker, TaskResult


class PluginManagerWindow(QMainWindow):
    def __init__(self, claude_dir: Path | None = None, project_dir: Path | None = None, claude_bin: str = "claude") -> None:
        super().__init__()
        self.store = ClaudePluginStore(claude_dir, project_dir)
        self.claude_bin = claude_bin
        self.plugins: dict[str, PluginView] = {}
        self.selected_plugin_id: str | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self.active_workers: list[FunctionWorker] = []

        self.setWindowTitle("ClauDeck 插件管理器")
        self.resize(1320, 820)
        self.setMinimumSize(1100, 700)

        self.list_panel = PluginListPanel(self)
        self.detail_panel = PluginDetailPanel(self)
        self.settings_button = TransparentToolButton(FluentIcon.SETTING, self)
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        self._build_layout()
        self._connect_signals()
        self._apply_sync_preferences()
        self.refresh_hook_status()
        self.refresh_plugins(sync_first=True, message="正在加载插件...")

    def _build_layout(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_column = QVBoxLayout()
        title_column.setSpacing(4)
        title = TitleLabel("ClauDeck 插件管理", central)
        subtitle = BodyLabel("管理 Claude Code 插件、同步启用状态，并浏览 README、Skills、Commands 与 Agents。", central)
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        title_row.addLayout(title_column, 1)
        self.settings_button.setToolTip("同步设置")
        title_row.addWidget(self.settings_button)
        root.addLayout(title_row)

        splitter = QSplitter(central)
        splitter.addWidget(self.list_panel)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([560, 760])
        root.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #edf3fa;
                color: #172033;
                font-family: Microsoft YaHei UI;
            }
            TitleLabel {
                color: #101827;
                background: transparent;
            }
            BodyLabel, StrongBodyLabel, CaptionLabel, QLabel {
                color: #24324a;
                background: transparent;
            }
            QSplitter {
                background: #edf3fa;
            }
            QSplitter::handle {
                background: #c7d6ea;
                width: 2px;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: #a9bdd6;
                border-radius: 5px;
                min-height: 36px;
            }
            QScrollBar::handle:vertical:hover {
                background: #7fa1c7;
            }
            QScrollBar::handle:vertical:pressed {
                background: #5f87b5;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
                border: 0;
                height: 0;
            }
            QScrollBar:horizontal {
                background: transparent;
                height: 10px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background: #a9bdd6;
                border-radius: 5px;
                min-width: 36px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #7fa1c7;
            }
            QScrollBar::handle:horizontal:pressed {
                background: #5f87b5;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal,
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {
                background: transparent;
                border: 0;
                width: 0;
            }
            QStatusBar {
                background: #e7eef8;
                color: #172033;
                border-top: 1px solid #ccd9ea;
            }
            """
        )

    def _connect_signals(self) -> None:
        self.list_panel.pluginSelected.connect(self.select_plugin)
        self.list_panel.refreshRequested.connect(lambda: self.refresh_plugins(sync_first=True, message="正在刷新并同步插件..."))
        self.list_panel.syncRequested.connect(self.sync_plugins)
        self.list_panel.toggleRequested.connect(self.set_plugin_enabled)
        self.list_panel.uninstallRequested.connect(self.uninstall_plugin)
        self.list_panel.hookInstallRequested.connect(self.install_hook)
        self.list_panel.hookRemoveRequested.connect(self.remove_hook)
        self.list_panel.watcherStopRequested.connect(self.stop_watcher)
        self.list_panel.syncPluginCountChanged.connect(self.set_sync_plugin_count)
        self.list_panel.syncPluginEnabledStateChanged.connect(self.set_sync_plugin_enabled_state)
        self.settings_button.clicked.connect(self._show_settings_menu)

    def _show_settings_menu(self) -> None:
        self.list_panel.show_settings_menu(self.settings_button.mapToGlobal(self.settings_button.rect().bottomLeft()))

    def _apply_sync_preferences(self) -> None:
        preferences = self.store.load_sync_preferences()
        self.list_panel.set_sync_preferences(
            sync_plugin_count=preferences.sync_plugin_count,
            sync_plugin_enabled_state=preferences.sync_plugin_enabled_state,
        )

    def set_sync_plugin_count(self, enabled: bool) -> None:
        try:
            self.store.update_sync_preferences(sync_plugin_count=enabled)
        except StoreError as exc:
            self._apply_sync_preferences()
            self._show_error("更新失败", str(exc))
            self.status_bar.showMessage(f"更新失败：{exc}")
            return
        self._apply_sync_preferences()
        self.status_bar.showMessage(f"自动补齐新增插件已{'开启' if enabled else '关闭'}。")

    def set_sync_plugin_enabled_state(self, enabled: bool) -> None:
        try:
            self.store.update_sync_preferences(sync_plugin_enabled_state=enabled)
        except StoreError as exc:
            self._apply_sync_preferences()
            self._show_error("更新失败", str(exc))
            self.status_bar.showMessage(f"更新失败：{exc}")
            return
        self._apply_sync_preferences()
        mode_text = "单向" if self.store.load_sync_preferences().sync_plugin_enabled_state else "双向"
        self.status_bar.showMessage(f"插件状态同步模式（{mode_text}）。")

    def refresh_plugins(self, *, sync_first: bool, message: str) -> None:
        def task() -> dict[str, Any]:
            sync_result = sync_enabled_plugins(self.store) if sync_first else None
            plugins = self.store.build_plugin_views()
            return {"plugins": plugins, "sync_result": sync_result}

        self._set_busy(True, message)
        self._run_worker(task, self._on_plugins_loaded)

    def sync_plugins(self) -> None:
        def task() -> dict[str, Any]:
            sync_result = sync_enabled_plugins(self.store)
            plugins = self.store.build_plugin_views()
            return {"plugins": plugins, "sync_result": sync_result}

        self._set_busy(True, "正在同步插件...")
        self._run_worker(task, self._on_plugins_loaded)

    def refresh_hook_status(self) -> None:
        try:
            hook_status = get_hook_status(self.store.claude_dir, session_project_dir=self.store.project_dir)
            watcher_status = get_watcher_status(self.store.claude_dir)
        except HookManagerError as exc:
            self.list_panel.set_hook_status(f"会话启动 hook：读取失败（{exc}）", "后台 watcher：读取失败", False, False, error=True)
            return
        self._apply_hook_status(hook_status, watcher_status)

    def install_hook(self) -> None:
        def task() -> dict[str, Any]:
            result = install_session_start_hook(self.store.claude_dir, session_project_dir=self.store.project_dir)
            run_session_start_sync(self.store.claude_dir, self.store.project_dir)
            plugins = self.store.build_plugin_views()
            return {"result": result, "plugins": plugins}

        self._set_busy(True, "正在安装会话启动 hook...")
        self._run_worker(task, self._on_hook_installed)

    def remove_hook(self) -> None:
        reply = QMessageBox.question(
            self,
            "移除会话启动 hook",
            "确定要移除 ClauDeck 会话启动 hook 吗？\n\n这只会删除 ClauDeck 写入的 SessionStart hook，不会删除其它 Claude Code hooks，也不会停止当前已经运行的 watcher。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def task() -> HookChangeResult:
            return remove_session_start_hook(self.store.claude_dir)

        self._set_busy(True, "正在移除会话启动 hook...")
        self._run_worker(task, self._on_hook_changed)

    def stop_watcher(self) -> None:
        reply = QMessageBox.question(
            self,
            "停止后台 watcher",
            "确定要停止当前正在运行的 watcher 吗？\n\n这不会移除 SessionStart hook；如果 hook 仍安装，下次会话启动时 watcher 可能会重新启动。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def task() -> WatcherStopResult:
            return stop_running_watcher(self.store.claude_dir)

        self._set_busy(True, "正在停止后台 watcher...")
        self._run_worker(task, self._on_watcher_stopped)

    def select_plugin(self, plugin_id: str) -> None:
        self.selected_plugin_id = plugin_id or None
        self.list_panel.set_selected_plugin(self.selected_plugin_id)
        self._update_detail_panel()

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        try:
            self.store.set_plugin_enabled(plugin_id, enabled)
        except StoreError as exc:
            self._show_error("更新失败", str(exc))
            self.status_bar.showMessage(f"更新失败：{exc}")
            return

        self.selected_plugin_id = plugin_id
        self.list_panel.set_selected_plugin(plugin_id)
        self.list_panel.update_plugin_enabled(plugin_id, enabled)
        self._update_detail_panel()
        self.status_bar.showMessage(f"插件 {plugin_id} {'已启用' if enabled else '已禁用'}。")

    def uninstall_plugin(self, plugin_id: str) -> None:
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            return

        reply = QMessageBox.question(
            self,
            "确认卸载",
            f"确定要卸载插件 {plugin_id} 吗？\n\n这会调用 `claude plugin uninstall`，同时清理缓存残留并删除 JSON 中的插件记录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def task() -> dict[str, Any]:
            self.store.uninstall_plugin(plugin_id, claude_bin=self.claude_bin)
            sync_result = sync_enabled_plugins(self.store)
            plugins = self.store.build_plugin_views()
            return {"plugins": plugins, "removed_plugin_id": plugin_id, "sync_result": sync_result}

        self._set_busy(True, f"正在卸载 {plugin_id}...")
        self._run_worker(task, self._on_plugin_uninstalled)

    def _on_plugins_loaded(self, payload: dict[str, Any]) -> None:
        plugins = payload["plugins"]
        sync_result = payload.get("sync_result")
        self._apply_plugins(plugins)
        self.refresh_hook_status()
        if sync_result is None:
            self.status_bar.showMessage(f"已加载 {len(plugins)} 个插件。")
        else:
            if sync_result.state_sync_mode == "one_way":
                self.status_bar.showMessage(
                    "同步完成："
                    f"补齐新增={'开' if sync_result.count_sync_applied else '关'}，"
                    f"同步启用状态=单向，"
                    f"修正插件={len(sync_result.corrected_plugin_ids)}，"
                    f"修复层数={sync_result.updated_layers_count}。"
                )
            else:
                self.status_bar.showMessage(
                    "同步完成："
                    f"补齐新增={'开' if sync_result.count_sync_applied else '关'}，"
                    f"同步启用状态=双向，"
                    f"接受外部变化={len(sync_result.accepted_plugin_ids)}，"
                    f"修复层数={sync_result.updated_layers_count}。"
                )

    def _on_plugin_uninstalled(self, payload: dict[str, Any]) -> None:
        removed_plugin_id = payload["removed_plugin_id"]
        if self.selected_plugin_id == removed_plugin_id:
            self.selected_plugin_id = None
        self._apply_plugins(payload["plugins"])
        self.refresh_hook_status()
        self.status_bar.showMessage(f"插件 {removed_plugin_id} 已卸载。")

    def _on_hook_installed(self, payload: dict[str, Any]) -> None:
        result = payload["result"]
        self.refresh_hook_status()
        self._apply_plugins(payload["plugins"])
        self.status_bar.showMessage(f"{result.message}，已立即同步并启动监听。")

    def _on_hook_changed(self, result: HookChangeResult) -> None:
        self.refresh_hook_status()
        self.status_bar.showMessage(result.message)

    def _on_watcher_stopped(self, result: WatcherStopResult) -> None:
        self.refresh_hook_status()
        self.status_bar.showMessage(result.message)

    def _apply_hook_status(self, hook_status: HookStatus, watcher_status: WatcherRuntimeStatus) -> None:
        if hook_status.installed and hook_status.stale:
            hook_text = "会话启动 hook：需更新"
        elif hook_status.installed:
            hook_text = "会话启动 hook：已安装"
        else:
            hook_text = "会话启动 hook：未安装"
        self.list_panel.set_hook_status(
            hook_text,
            watcher_status.message,
            hook_status.installed,
            hook_status.stale,
            watcher_status.running,
        )

    def _apply_plugins(self, plugins: list[PluginView]) -> None:
        self.plugins = {plugin.plugin_id: plugin for plugin in plugins}
        selected = self.list_panel.set_plugins(plugins, self.selected_plugin_id)
        self.selected_plugin_id = selected
        self.list_panel.set_selected_plugin(selected)
        self._update_detail_panel()

    def _update_detail_panel(self) -> None:
        plugin = self.plugins.get(self.selected_plugin_id) if self.selected_plugin_id else None
        self.detail_panel.set_plugin(plugin)
        if plugin is None:
            return

        def task() -> PluginContentBundle:
            return discover_plugin_content(plugin, self.store.plugin_cache_root(plugin.plugin_id))

        self._run_worker(task, self._on_plugin_content_loaded, show_busy=False)

    def _on_plugin_content_loaded(self, bundle: PluginContentBundle) -> None:
        if bundle.plugin_id != self.selected_plugin_id:
            return
        self.detail_panel.set_content(bundle)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.list_panel.set_busy(busy)
        self.detail_panel.set_busy(busy)
        self.settings_button.setEnabled(not busy)
        if message:
            self.status_bar.showMessage(message)

    def _run_worker(self, function, on_success, *, show_busy: bool = True) -> None:
        worker = FunctionWorker(function)
        self.active_workers.append(worker)

        def succeeded(result: TaskResult) -> None:
            on_success(result.payload)

        def failed(error: str) -> None:
            selected_plugin_id = self.selected_plugin_id
            if not show_busy and selected_plugin_id:
                self.detail_panel.set_content_error(selected_plugin_id, error)
            else:
                self._show_error("操作失败", error)
            self.status_bar.showMessage(f"操作失败：{error}")

        def finished() -> None:
            if show_busy:
                self._set_busy(False)
            if worker in self.active_workers:
                self.active_workers.remove(worker)

        worker.signals.succeeded.connect(succeeded)
        worker.signals.failed.connect(failed)
        worker.signals.finished.connect(finished)
        self.thread_pool.start(worker)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)
