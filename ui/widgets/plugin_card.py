from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, CardWidget, PushButton, StrongBodyLabel

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
        self.publisher_line = CaptionLabel(f"发布方：{plugin.publisher or '-'}", self)
        self.version_scope_line = CaptionLabel(
            f"版本：{plugin.display_version}    作用域：{'、'.join(plugin.scopes) if plugin.scopes else '-'}",
            self,
        )
        self.toggle_button = PushButton("禁用" if plugin.enabled else "启用", self)
        self.uninstall_button = PushButton("卸载", self)
        self.uninstall_button.setObjectName("uninstallButton")
        self.toggle_button.setFixedWidth(82)
        self.uninstall_button.setFixedWidth(82)

        self._build_layout()
        self._connect_signals()
        self._apply_style()

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(5)
        title_row.addWidget(self.title_label, 1)
        title_row.addWidget(self.status_badge, 0, Qt.AlignmentFlag.AlignRight)
        root.addLayout(title_row)
        self.publisher_line.setWordWrap(True)
        self.version_scope_line.setWordWrap(True)
        root.addWidget(self.publisher_line)
        root.addWidget(self.version_scope_line)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        action_row.addWidget(self.toggle_button)
        action_row.addWidget(self.uninstall_button)
        root.addLayout(action_row)

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
        self.toggle_button.setText("禁用" if enabled else "启用")
        self._apply_style()

    def _apply_style(self) -> None:
        selected_border = "#2f78d6" if self._selected else "#c8d7ea"
        selected_bg = "#e8f2ff" if self._selected else "#ffffff"
        badge_bg = "#dff5e7" if self.plugin.enabled else "#fff1f0"
        badge_fg = "#0c6b35" if self.plugin.enabled else "#b42318"
        badge_border = "#0c6b35" if self.plugin.enabled else "#f1a6a0"

        self.setStyleSheet(
            f"""
            PluginCard {{
                background: {selected_bg};
                border: 1px solid {selected_border};
                border-radius: 10px;
            }}
            PluginCard:hover {{
                border: 1px solid #2f78d6;
                background: #f4f8ff;
            }}
            StrongBodyLabel {{
                color: #111a2d;
                background: transparent;
                font-size: 13px;
                font-weight: 700;
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
                border: 1px solid {badge_border};
                border-radius: 8px;
                padding: 2px 6px;
                font-weight: 700;
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
