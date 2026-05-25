from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, SearchLineEdit, StrongBodyLabel

from plugin_store import PluginView
from ui.widgets.plugin_card import PluginCard
from ui.widgets.summary_card import SummaryCard


class PluginListPanel(QWidget):
    pluginSelected = pyqtSignal(str)
    refreshRequested = pyqtSignal()
    syncRequested = pyqtSignal()
    toggleRequested = pyqtSignal(str, bool)
    uninstallRequested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.plugins: list[PluginView] = []
        self.filtered_plugins: list[PluginView] = []
        self.selected_plugin_id: str | None = None
        self.cards: dict[str, PluginCard] = {}

        self.total_card = SummaryCard("插件总数", self)
        self.enabled_card = SummaryCard("已启用", self)
        self.disabled_card = SummaryCard("已禁用", self)
        self.search_edit = SearchLineEdit(self)
        self.refresh_button = PushButton("刷新", self)
        self.sync_button = PrimaryPushButton("同步插件", self)
        self.empty_label = BodyLabel("没有匹配的插件", self)

        self._build_layout()
        self._connect_signals()

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
            PushButton {
                color: #172033;
            }
            PrimaryPushButton {
                color: #ffffff;
                background: #2f78d6;
                border: 1px solid #2367bd;
            }
            """
        )

    def _connect_signals(self) -> None:
        self.search_edit.textChanged.connect(self.apply_filter)
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        self.sync_button.clicked.connect(self.syncRequested.emit)

    def set_plugins(self, plugins: list[PluginView], selected_plugin_id: str | None = None) -> str | None:
        self.plugins = plugins
        self._update_summary()
        self.apply_filter(selected_plugin_id=selected_plugin_id, emit_selection=False)
        return self.selected_plugin_id

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

    def set_busy(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.sync_button.setEnabled(not busy)
        for card in self.cards.values():
            card.toggle_button.setEnabled(not busy)
            card.uninstall_button.setEnabled(not busy)

    def _matches(self, plugin: PluginView, keyword: str) -> bool:
        haystacks = [
            plugin.plugin_id,
            plugin.name,
            plugin.publisher,
            " ".join(plugin.scopes),
            " ".join(plugin.versions),
        ]
        return any(keyword in value.lower() for value in haystacks if value)

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

    def _on_card_selected(self, plugin_id: str) -> None:
        self.set_selected_plugin(plugin_id)
        self.pluginSelected.emit(plugin_id)
