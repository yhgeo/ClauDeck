from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, PushButton, StrongBodyLabel

from plugin_store import PluginView


class PluginCard(CardWidget):
    selected = pyqtSignal(str)
    toggleRequested = pyqtSignal(str, bool)
    uninstallRequested = pyqtSignal(str)

    def __init__(self, plugin: PluginView, parent=None) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("pluginCard")

        self.title_label = StrongBodyLabel(plugin.name, self)
        self.status_badge = QLabel("已启用" if plugin.enabled else "已禁用", self)
        self.status_badge.setObjectName("statusBadge")
        self.id_label = CaptionLabel(plugin.plugin_id, self)
        self.publisher_value = BodyLabel(plugin.publisher or "-", self)
        self.version_value = BodyLabel(plugin.display_version, self)
        self.scope_value = BodyLabel("、".join(plugin.scopes) if plugin.scopes else "-", self)
        self.toggle_button = PushButton("禁用插件" if plugin.enabled else "启用插件", self)
        self.uninstall_button = PushButton("卸载插件", self)
        self.uninstall_button.setObjectName("uninstallButton")

        self._build_layout()
        self._connect_signals()
        self._apply_style()

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(self.title_label, 1)
        title_row.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(title_row)
        root.addWidget(self.id_label)

        meta_grid = QGridLayout()
        meta_grid.setHorizontalSpacing(10)
        meta_grid.setVerticalSpacing(8)
        self._add_meta_block(meta_grid, 0, 0, "发布方", self.publisher_value)
        self._add_meta_block(meta_grid, 0, 1, "版本", self.version_value)
        self._add_meta_block(meta_grid, 0, 2, "作用域", self.scope_value)
        root.addLayout(meta_grid)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self.toggle_button)
        action_row.addWidget(self.uninstall_button)
        action_row.addStretch(1)
        root.addLayout(action_row)

    def _add_meta_block(self, layout: QGridLayout, row: int, column: int, title: str, value_widget: BodyLabel) -> None:
        block = QFrame(self)
        block.setObjectName("metaBlock")
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(10, 8, 10, 8)
        block_layout.setSpacing(4)
        title_label = CaptionLabel(title, block)
        value_widget.setWordWrap(True)
        block_layout.addWidget(title_label)
        block_layout.addWidget(value_widget)
        layout.addWidget(block, row, column)

    def _connect_signals(self) -> None:
        self.toggle_button.clicked.connect(
            lambda: self.toggleRequested.emit(self.plugin.plugin_id, not self.plugin.enabled)
        )
        self.uninstall_button.clicked.connect(
            lambda: self.uninstallRequested.emit(self.plugin.plugin_id)
        )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.plugin.plugin_id)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def set_enabled_state(self, enabled: bool) -> None:
        self.plugin.enabled = enabled
        self.status_badge.setText("已启用" if enabled else "已禁用")
        self.toggle_button.setText("禁用插件" if enabled else "启用插件")
        self._apply_style()

    def _apply_style(self) -> None:
        selected_border = "#2f78d6" if self._selected else "#c8d7ea"
        selected_bg = "#e8f2ff" if self._selected else "#ffffff"
        badge_bg = "#dff5e7" if self.plugin.enabled else "#eef2f7"
        badge_fg = "#0c6b35" if self.plugin.enabled else "#596a82"
        meta_bg = "#f3f8ff" if self.plugin.enabled else "#f6f8fb"

        self.setStyleSheet(
            f"""
            PluginCard {{
                background: {selected_bg};
                border: 1px solid {selected_border};
                border-radius: 14px;
            }}
            PluginCard:hover {{
                border: 1px solid #2f78d6;
                background: #f4f8ff;
            }}
            StrongBodyLabel {{
                color: #111a2d;
                background: transparent;
                font-size: 15px;
                font-weight: 700;
            }}
            BodyLabel {{
                color: #1f2d43;
                background: transparent;
            }}
            CaptionLabel {{
                color: #596a82;
                background: transparent;
            }}
            QLabel {{
                color: #1f2d43;
                background: transparent;
            }}
            QLabel#statusBadge {{
                color: {badge_fg};
                background: {badge_bg};
                border: 1px solid {badge_fg};
                border-radius: 10px;
                padding: 4px 10px;
                font-weight: 700;
            }}
            QFrame#metaBlock {{
                background: {meta_bg};
                border: 1px solid #d7e2f0;
                border-radius: 9px;
            }}
            PushButton {{
                color: #172033;
            }}
            PushButton:disabled {{
                color: #8a98aa;
                background: #eef2f7;
                border: 1px solid #d7e2f0;
            }}
            PushButton#uninstallButton {{
                color: #a73525;
                border: 1px solid #e2b8af;
                background: #fff7f5;
            }}
            PushButton#uninstallButton:hover {{
                color: #8f2b1f;
                border: 1px solid #cf8f83;
                background: #fdebe7;
            }}
            PushButton#uninstallButton:pressed {{
                color: #ffffff;
                border: 1px solid #a73525;
                background: #a73525;
            }}
            PushButton#uninstallButton:disabled {{
                color: #bd8d85;
                border: 1px solid #ead2ce;
                background: #f8f1ef;
            }}
            """
        )
