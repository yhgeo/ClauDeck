from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QSplitter, QStatusBar, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, TitleLabel

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

        self.setWindowTitle("ClauDeck")
        self.resize(1320, 820)
        self.setMinimumSize(1100, 700)

        self.list_panel = PluginListPanel(self)
        self.detail_panel = PluginDetailPanel(self)
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        self._build_layout()
        self._connect_signals()
        self.refresh_plugins(sync_first=True, message="正在加载插件...")

    def _build_layout(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(14)

        title = TitleLabel("Claude 插件总览", central)
        subtitle = BodyLabel("使用 PyQt6 + Fluent 管理插件、同步状态并查看安装详情。", central)
        root.addWidget(title)
        root.addWidget(subtitle)

        splitter = QSplitter(central)
        splitter.addWidget(self.list_panel)
        splitter.addWidget(self.detail_panel)
        splitter.setSizes([760, 520])
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
        self.detail_panel.toggleRequested.connect(self.set_plugin_enabled)
        self.detail_panel.uninstallRequested.connect(self.uninstall_plugin)

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
        self.status_bar.showMessage(f"插件 {plugin_id} {'已启用' if enabled else '已禁用'}。")
        self.refresh_plugins(sync_first=False, message="正在刷新插件状态...")

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

    def _apply_plugins(self, plugins: list[PluginView]) -> None:
        self.plugins = {plugin.plugin_id: plugin for plugin in plugins}
        selected = self.list_panel.set_plugins(plugins, self.selected_plugin_id)
        self.selected_plugin_id = selected
        self.list_panel.set_selected_plugin(selected)
        self._update_detail_panel()

    def _update_detail_panel(self) -> None:
        plugin = self.plugins.get(self.selected_plugin_id) if self.selected_plugin_id else None
        self.detail_panel.set_plugin(plugin)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.list_panel.set_busy(busy)
        self.detail_panel.set_busy(busy)
        if message:
            self.status_bar.showMessage(message)

    def _run_worker(self, function, on_success) -> None:
        worker = FunctionWorker(function)
        self.active_workers.append(worker)

        def succeeded(result: TaskResult) -> None:
            on_success(result.payload)

        def failed(error: str) -> None:
            self._show_error("操作失败", error)
            self.status_bar.showMessage(f"操作失败：{error}")

        def finished() -> None:
            self._set_busy(False)
            if worker in self.active_workers:
                self.active_workers.remove(worker)

        worker.signals.succeeded.connect(succeeded)
        worker.signals.failed.connect(failed)
        worker.signals.finished.connect(finished)
        self.thread_pool.start(worker)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)
