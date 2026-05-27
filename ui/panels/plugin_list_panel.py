from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    BodyLabel,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SearchLineEdit,
    StrongBodyLabel,
)

from plugin_store import PluginView
from ui.widgets.plugin_card import PluginCard
from ui.widgets.summary_card import SummaryCard


class PluginListPanel(QWidget):
    pluginSelected = pyqtSignal(str)
    refreshRequested = pyqtSignal()
    syncRequested = pyqtSignal()
    toggleRequested = pyqtSignal(str, bool)
    uninstallRequested = pyqtSignal(str)
    hookInstallRequested = pyqtSignal()
    hookRemoveRequested = pyqtSignal()
    watcherStopRequested = pyqtSignal()
    syncPluginCountChanged = pyqtSignal(bool)
    syncPluginEnabledStateChanged = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.plugins: list[PluginView] = []
        self.filtered_plugins: list[PluginView] = []
        self.selected_plugin_id: str | None = None
        self.cards: dict[str, PluginCard] = {}
        self._hook_installed = False
        self._hook_stale = False
        self._watcher_running = False
        self._sync_plugin_count = True
        self._sync_plugin_enabled_state = True

        self.total_card = SummaryCard("插件总数", self)
        self.enabled_card = SummaryCard("已启用", self)
        self.disabled_card = SummaryCard("已禁用", self)
        self.search_edit = SearchLineEdit(self)
        self.refresh_button = PushButton("刷新", self)
        self.sync_button = PrimaryPushButton("同步插件", self)
        self.hook_status_label = BodyLabel("会话启动 hook：检查中...", self)
        self.watcher_status_label = BodyLabel("后台 watcher：检查中...", self)
        self.hook_button = PushButton("安装会话启动 hook", self)
        self.watcher_stop_button = PushButton("停止 watcher", self)
        self.hook_info_label = self._new_info_label(
            "SessionStart hook 是写入 Claude Code settings.json 的启动钩子。安装后，新会话启动时会先同步插件并启动后台 watcher。"
        )
        self.watcher_info_label = self._new_info_label(
            "watcher 是 ClauDeck 的后台监听进程，会监视插件记录和 settings.json，在插件状态丢失时自动修复 enabledPlugins。"
        )
        self.empty_label = BodyLabel("没有匹配的插件", self)
        self.sync_button.setToolTip("立即按当前同步策略检查并修复 enabledPlugins。")
        self.hook_button.setToolTip("安装、更新或移除 ClauDeck 管理的 Claude Code SessionStart hook。")
        self.watcher_stop_button.setToolTip("停止当前正在运行的后台 watcher；不会移除 SessionStart hook。")

        self._build_layout()
        self._build_settings_menu()
        self._connect_signals()
        self._update_settings_actions()

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        metrics.addWidget(self.total_card)
        metrics.addWidget(self.enabled_card)
        metrics.addWidget(self.disabled_card)
        metrics.addStretch(1)
        root.addLayout(metrics)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search_edit.setPlaceholderText("搜索插件名称、发布方、版本或作用域")
        toolbar.addWidget(self.search_edit, 1)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.sync_button)
        root.addLayout(toolbar)

        hook_row = QVBoxLayout()
        hook_row.setSpacing(8)
        self.hook_status_label.setObjectName("hookStatusLabel")
        self.watcher_status_label.setObjectName("watcherStatusLabel")
        hook_header = QHBoxLayout()
        hook_header.setSpacing(8)
        hook_header.addWidget(self.hook_status_label, 1)
        hook_header.addWidget(self.hook_info_label)
        hook_header.addWidget(self.hook_button)
        hook_row.addLayout(hook_header)
        watcher_header = QHBoxLayout()
        watcher_header.setSpacing(8)
        watcher_header.addWidget(self.watcher_status_label, 1)
        watcher_header.addWidget(self.watcher_info_label)
        watcher_header.addWidget(self.watcher_stop_button)
        hook_row.addLayout(watcher_header)
        root.addLayout(hook_row)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setObjectName("pluginScrollArea")

        self.cards_host = QWidget(self.scroll_area)
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 8, 0)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch(1)
        self.scroll_area.setWidget(self.cards_host)
        root.addWidget(self.scroll_area, 1)

        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        root.addWidget(self.empty_label)

        self.setStyleSheet(
            """
            PluginListPanel {
                background: #edf3fa;
            }
            QScrollArea#pluginScrollArea {
                background: #edf3fa;
                border: 0;
            }
            QScrollArea#pluginScrollArea > QWidget > QWidget {
                background: #edf3fa;
            }
            SearchLineEdit {
                color: #172033;
            }
            BodyLabel {
                color: #24324a;
                background: transparent;
            }
            QLabel#infoBadge {
                color: #2f78d6;
                background: #eef6ff;
                border: 1px solid #8bb8f0;
                border-radius: 9px;
                font-weight: 700;
            }
            BodyLabel#hookStatusLabel,
            BodyLabel#watcherStatusLabel {
                padding: 6px 10px;
                border: 1px solid #cbd8ea;
                border-radius: 9px;
                background: #ffffff;
            }
            PushButton {
                color: #172033;
            }
            PushButton:disabled {
                color: #8a98aa;
                background: #eef2f7;
                border: 1px solid #d7e2f0;
            }
            PrimaryPushButton {
                color: #ffffff;
                background: #2f78d6;
                border: 1px solid #2367bd;
            }
            PrimaryPushButton:disabled {
                color: #e7eef8;
                background: #9fb8d6;
                border: 1px solid #8ca9cb;
            }
            """
        )

    def _new_info_label(self, tooltip: str) -> QLabel:
        label = QLabel("!", self)
        label.setObjectName("infoBadge")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFixedSize(18, 18)
        label.setToolTip(tooltip)
        return label

    def _build_settings_menu(self) -> None:
        self._settings_menu = RoundMenu(parent=self)
        self._count_action = Action(FluentIcon.INFO, "", self._settings_menu)
        self._count_action.setToolTip("开启后，已安装但缺失于 enabledPlugins 的插件会被自动补回。")
        self._count_action.triggered.connect(self._on_sync_plugin_count_triggered)
        self._settings_menu.addAction(self._count_action)

        self._state_action = Action(FluentIcon.INFO, "", self._settings_menu)
        self._state_action.setToolTip("单向模式按 ClauDeck 记录修复启用状态；双向模式会接受外部对启用状态的修改。")
        self._state_action.triggered.connect(self._on_sync_plugin_enabled_state_triggered)
        self._settings_menu.addAction(self._state_action)

    def _connect_signals(self) -> None:
        self.search_edit.textChanged.connect(self.apply_filter)
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        self.sync_button.clicked.connect(self.syncRequested.emit)
        self.hook_button.clicked.connect(self._on_hook_button_clicked)
        self.watcher_stop_button.clicked.connect(self.watcherStopRequested.emit)

    def set_plugins(self, plugins: list[PluginView], selected_plugin_id: str | None = None) -> str | None:
        scroll_value = self.scroll_area.verticalScrollBar().value()
        self.plugins = self._sort_plugins(plugins)
        self._update_summary()
        self.apply_filter(selected_plugin_id=selected_plugin_id, emit_selection=False)
        self._restore_scroll_position(scroll_value)
        return self.selected_plugin_id

    def set_sync_preferences(self, *, sync_plugin_count: bool, sync_plugin_enabled_state: bool) -> None:
        self._sync_plugin_count = sync_plugin_count
        self._sync_plugin_enabled_state = sync_plugin_enabled_state
        self._update_settings_actions()

    def apply_filter(self, _text: str | None = None, *, selected_plugin_id: str | None = None, emit_selection: bool = True) -> None:
        keyword = self.search_edit.text().strip().lower()
        previous_selection = selected_plugin_id if selected_plugin_id is not None else self.selected_plugin_id

        if keyword:
            self.filtered_plugins = [plugin for plugin in self.plugins if self._matches(plugin, keyword)]
        else:
            self.filtered_plugins = list(self.plugins)

        visible_ids = {plugin.plugin_id for plugin in self.filtered_plugins}
        if previous_selection in visible_ids:
            self.selected_plugin_id = previous_selection
        elif self.filtered_plugins:
            self.selected_plugin_id = self.filtered_plugins[0].plugin_id
        else:
            self.selected_plugin_id = None

        self._render_cards()
        if emit_selection:
            self.pluginSelected.emit(self.selected_plugin_id or "")

    def set_selected_plugin(self, plugin_id: str | None) -> None:
        self.selected_plugin_id = plugin_id
        for card_id, card in self.cards.items():
            card.set_selected(card_id == plugin_id)

    def update_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        for plugin in self.plugins:
            if plugin.plugin_id == plugin_id:
                plugin.enabled = enabled
                break
        for plugin in self.filtered_plugins:
            if plugin.plugin_id == plugin_id:
                plugin.enabled = enabled
                break
        self.plugins = self._sort_plugins(self.plugins)
        self._update_summary()
        self.apply_filter(selected_plugin_id=plugin_id, emit_selection=False)

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.sync_button.setEnabled(not busy)
        self.hook_button.setEnabled(not busy)
        self._update_watcher_stop_button(not busy)
        for card in self.cards.values():
            card.toggle_button.setEnabled(not busy)
            card.uninstall_button.setEnabled(not busy)

    def set_hook_status(
        self,
        hook_text: str,
        watcher_text: str,
        installed: bool,
        stale: bool,
        watcher_running: bool = False,
        error: bool = False,
    ) -> None:
        self._hook_installed = installed
        self._hook_stale = stale
        self._watcher_running = watcher_running
        self.hook_status_label.setText(hook_text)
        self.watcher_status_label.setText(watcher_text)
        if error:
            self.hook_status_label.setStyleSheet("color: #a73525; font-weight: 600;")
            self.watcher_status_label.setStyleSheet("color: #a73525; font-weight: 600;")
        elif installed and not stale:
            self.hook_status_label.setStyleSheet("color: #0c6b35; font-weight: 600;")
            self.watcher_status_label.setStyleSheet("color: #596a82; font-weight: 600;")
        elif stale:
            self.hook_status_label.setStyleSheet("color: #9a6500; font-weight: 600;")
            self.watcher_status_label.setStyleSheet("color: #596a82; font-weight: 600;")
        else:
            self.hook_status_label.setStyleSheet("color: #596a82; font-weight: 600;")
            self.watcher_status_label.setStyleSheet("color: #596a82; font-weight: 600;")
        if installed and not stale:
            button_text = "移除会话启动 hook"
        elif stale:
            button_text = "更新会话启动 hook"
        else:
            button_text = "安装会话启动 hook"
        self.hook_button.setText(button_text)
        self._update_watcher_stop_button(True)

    def _update_watcher_stop_button(self, controls_enabled: bool) -> None:
        self.watcher_stop_button.setEnabled(controls_enabled and self._watcher_running)

    def _on_hook_button_clicked(self) -> None:
        if self._hook_installed and not self._hook_stale:
            self.hookRemoveRequested.emit()
        else:
            self.hookInstallRequested.emit()

    def show_settings_menu(self, global_pos) -> None:
        self._update_settings_actions()
        self._settings_menu.exec(global_pos)

    def _on_sync_plugin_count_triggered(self) -> None:
        new_value = not self._sync_plugin_count
        self._sync_plugin_count = new_value
        self._update_settings_actions()
        self.syncPluginCountChanged.emit(new_value)

    def _on_sync_plugin_enabled_state_triggered(self) -> None:
        new_value = not self._sync_plugin_enabled_state
        self._sync_plugin_enabled_state = new_value
        self._update_settings_actions()
        self.syncPluginEnabledStateChanged.emit(new_value)

    def _update_settings_actions(self) -> None:
        self._count_action.setText(
            f"自动补齐新增插件（{'已开启' if self._sync_plugin_count else '已关闭'}）"
        )
        self._state_action.setText(
            f"插件状态同步模式（{'单向' if self._sync_plugin_enabled_state else '双向'}）"
        )

    def _matches(self, plugin: PluginView, keyword: str) -> bool:
        haystacks = [
            plugin.plugin_id,
            plugin.name,
            plugin.publisher,
            " ".join(plugin.scopes),
            " ".join(plugin.versions),
        ]
        return any(keyword in value.lower() for value in haystacks if value)

    def _sort_plugins(self, plugins: list[PluginView]) -> list[PluginView]:
        return sorted(
            plugins,
            key=lambda plugin: (
                not plugin.enabled,
                plugin.name.lower(),
                plugin.publisher.lower(),
                plugin.plugin_id.lower(),
            ),
        )

    def _update_summary(self) -> None:
        enabled_count = sum(1 for plugin in self.plugins if plugin.enabled)
        self.total_card.set_value(len(self.plugins))
        self.enabled_card.set_value(enabled_count)
        self.disabled_card.set_value(len(self.plugins) - enabled_count)

    def _render_cards(self) -> None:
        while self.cards_layout.count() > 0:
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.cards.clear()
        self.empty_label.setVisible(not self.filtered_plugins)
        self.scroll_area.setVisible(bool(self.filtered_plugins))

        for plugin in self.filtered_plugins:
            card = PluginCard(plugin, self.cards_host)
            card.set_selected(plugin.plugin_id == self.selected_plugin_id)
            card.selected.connect(self._on_card_selected)
            card.toggleRequested.connect(self.toggleRequested.emit)
            card.uninstallRequested.connect(self.uninstallRequested.emit)
            self.cards[plugin.plugin_id] = card
            self.cards_layout.addWidget(card)
        self.cards_layout.addStretch(1)

    def _restore_scroll_position(self, value: int) -> None:
        def restore() -> None:
            bar = self.scroll_area.verticalScrollBar()
            bar.setValue(min(value, bar.maximum()))

        QTimer.singleShot(0, restore)

    def _on_card_selected(self, plugin_id: str) -> None:
        self.set_selected_plugin(plugin_id)
        self.pluginSelected.emit(plugin_id)
