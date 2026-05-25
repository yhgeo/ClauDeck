from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QSplitter, QStatusBar, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, TitleLabel

from hook_manager import (
    HookChangeResult,
    HookManagerError,
    HookStatus,
    get_hook_status,
    install_session_start_hook,
    remove_session_start_hook,
)
from plugin_content import PluginContentBundle, discover_plugin_content
from plugin_store import ClaudePluginStore, PluginView, StoreError
from plugin_sync import sync_enabled_plugins
from ui.panels.plugin_detail_panel import PluginDetailPanel
from ui.panels.plugin_list_panel import PluginListPanel
from ui.workers.tasks import FunctionWorker, TaskResult


class PluginManagerWindow(QMainWindow):
    def __init__(self, claude_dir: Path | None = None, claude_bin: str = "claude") -> None:
        super().__init__()
        self.store = ClaudePluginStore(claude_dir)
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
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        self._build_layout()
        self._connect_signals()
        self.refresh_hook_status()
        self.refresh_plugins(sync_first=True, message="正在加载插件...")

    def _build_layout(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(14)

        title = TitleLabel("ClauDeck 插件管理", central)
        subtitle = BodyLabel("管理 Claude Code 插件、同步启用状态，并浏览 README、Skills、Commands 与 Agents。", central)
        root.addWidget(title)
        root.addWidget(subtitle)

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
        self.list_panel.refreshRequested.connect(lambda: self.refresh_plugins(sync_first=False, message="正在刷新插件..."))
        self.list_panel.syncRequested.connect(self.sync_plugins)
        self.list_panel.toggleRequested.connect(self.set_plugin_enabled)
        self.list_panel.uninstallRequested.connect(self.uninstall_plugin)
        self.list_panel.hookInstallRequested.connect(self.install_hook)
        self.list_panel.hookRemoveRequested.connect(self.remove_hook)

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
            status = get_hook_status(self.store.claude_dir)
        except HookManagerError as exc:
            self.list_panel.set_hook_status(f"自动同步：读取失败（{exc}）", False, False, error=True)
            return
        self._apply_hook_status(status)

    def install_hook(self) -> None:
        def task() -> HookChangeResult:
            return install_session_start_hook(self.store.claude_dir)

        self._set_busy(True, "正在安装自动同步 hook...")
        self._run_worker(task, self._on_hook_changed)

    def remove_hook(self) -> None:
        reply = QMessageBox.question(
            self,
            "移除自动同步",
            "确定要移除 ClauDeck 自动同步 hook 吗？\n\n这只会删除 ClauDeck 写入的 SessionStart hook，不会删除其它 Claude Code hooks，也不会停止当前已经运行的 watcher。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def task() -> HookChangeResult:
            return remove_session_start_hook(self.store.claude_dir)

        self._set_busy(True, "正在移除自动同步 hook...")
        self._run_worker(task, self._on_hook_changed)

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
            sync_enabled_plugins(self.store)
            plugins = self.store.build_plugin_views()
            return {"plugins": plugins, "removed_plugin_id": plugin_id}

        self._set_busy(True, f"正在卸载 {plugin_id}...")
        self._run_worker(task, self._on_plugin_uninstalled)

    def _on_plugins_loaded(self, payload: dict[str, Any]) -> None:
        plugins = payload["plugins"]
        sync_result = payload.get("sync_result")
        self._apply_plugins(plugins)
        if sync_result is None:
            self.status_bar.showMessage(f"已加载 {len(plugins)} 个插件。")
        else:
            self.status_bar.showMessage(
                f"同步完成：变更={sync_result.changed}，补回插件={len(sync_result.added_plugin_ids)}。"
            )

    def _on_plugin_uninstalled(self, payload: dict[str, Any]) -> None:
        removed_plugin_id = payload["removed_plugin_id"]
        if self.selected_plugin_id == removed_plugin_id:
            self.selected_plugin_id = None
        self._apply_plugins(payload["plugins"])
        self.status_bar.showMessage(f"插件 {removed_plugin_id} 已卸载。")

    def _on_hook_changed(self, result: HookChangeResult) -> None:
        self._apply_hook_status(result.status)
        self.status_bar.showMessage(result.message)

    def _apply_hook_status(self, status: HookStatus) -> None:
        if status.installed and status.stale:
            text = "自动同步：路径已过期"
        elif status.installed:
            text = "自动同步：已安装"
        else:
            text = "自动同步：未安装"
        self.list_panel.set_hook_status(text, status.installed, status.stale)

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
