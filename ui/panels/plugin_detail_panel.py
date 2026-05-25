from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, PushButton, StrongBodyLabel, TitleLabel

from plugin_store import PluginView


class PluginDetailPanel(CardWidget):
    toggleRequested = pyqtSignal(str, bool)
    uninstallRequested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.plugin: PluginView | None = None

        self.title_label = TitleLabel("请选择插件", self)
        self.subtitle_label = CaptionLabel("左侧选中一个插件后，这里会显示详细信息。", self)
        self.status_value = BodyLabel("-", self)
        self.publisher_value = BodyLabel("-", self)
        self.version_value = BodyLabel("-", self)
        self.scope_value = BodyLabel("-", self)
        self.id_value = BodyLabel("-", self)
        self.records_text = QTextEdit(self)
        self.toggle_button = PushButton("启用/禁用", self)
        self.uninstall_button = PushButton("删除卸载", self)

        self._build_layout()
        self._connect_signals()
        self.show_empty()

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(12)
        self._add_field(grid, 0, 0, "当前状态", self.status_value)
        self._add_field(grid, 0, 1, "发布方", self.publisher_value)
        self._add_field(grid, 1, 0, "版本", self.version_value)
        self._add_field(grid, 1, 1, "作用域", self.scope_value)
        root.addLayout(grid)

        root.addWidget(StrongBodyLabel("完整标识", self))
        self.id_value.setWordWrap(True)
        root.addWidget(self.id_value)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self.toggle_button)
        action_row.addWidget(self.uninstall_button)
        action_row.addStretch(1)
        root.addLayout(action_row)

        root.addWidget(StrongBodyLabel("安装记录", self))
        self.records_text.setReadOnly(True)
        self.records_text.setObjectName("recordsText")
        self.records_text.setMinimumHeight(260)
        root.addWidget(self.records_text, 1)

        self.setStyleSheet(
            """
            PluginDetailPanel {
                background: #ffffff;
                border: 1px solid #c8d7ea;
                border-radius: 16px;
            }
            TitleLabel {
                color: #101827;
                background: transparent;
            }
            StrongBodyLabel {
                color: #142038;
                background: transparent;
                font-weight: 700;
            }
            BodyLabel {
                color: #1f2d43;
                background: transparent;
            }
            CaptionLabel {
                color: #596a82;
                background: transparent;
            }
            QTextEdit#recordsText {
                background: #f4f8ff;
                border: 1px solid #cfdced;
                border-radius: 10px;
                padding: 8px;
                color: #142038;
                selection-background-color: #2f78d6;
                selection-color: #ffffff;
                font-family: Consolas, Microsoft YaHei UI;
                font-size: 10pt;
            }
            QFrame#fieldBlock {
                background: #f3f8ff;
                border: 1px solid #d7e2f0;
                border-radius: 9px;
            }
            PushButton {
                color: #172033;
            }
            """
        )

    def _add_field(self, layout: QGridLayout, row: int, column: int, title: str, value: BodyLabel) -> None:
        block = QFrame(self)
        block.setObjectName("fieldBlock")
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(10, 8, 10, 8)
        block_layout.setSpacing(4)
        block_layout.addWidget(CaptionLabel(title, block))
        value.setWordWrap(True)
        block_layout.addWidget(value)
        layout.addWidget(block, row, column)

    def _connect_signals(self) -> None:
        self.toggle_button.clicked.connect(self._request_toggle)
        self.uninstall_button.clicked.connect(self._request_uninstall)

    def set_plugin(self, plugin: PluginView | None) -> None:
        self.plugin = plugin
        if plugin is None:
            self.show_empty()
            return

        self.title_label.setText(plugin.name)
        self.subtitle_label.setText("当前选中的插件详情。")
        self.status_value.setText("已启用" if plugin.enabled else "已禁用")
        self.publisher_value.setText(plugin.publisher or "-")
        self.version_value.setText(plugin.display_version)
        self.scope_value.setText("、".join(plugin.scopes) if plugin.scopes else "-")
        self.id_value.setText(plugin.plugin_id)
        self.records_text.setPlainText(self._build_detail_text(plugin))
        self.toggle_button.setText("禁用插件" if plugin.enabled else "启用插件")
        self.toggle_button.setEnabled(True)
        self.uninstall_button.setEnabled(True)

    def show_empty(self) -> None:
        self.title_label.setText("请选择插件")
        self.subtitle_label.setText("左侧选中一个插件后，这里会显示详细信息。")
        self.status_value.setText("-")
        self.publisher_value.setText("-")
        self.version_value.setText("-")
        self.scope_value.setText("-")
        self.id_value.setText("-")
        self.records_text.setPlainText("暂无详细信息。")
        self.toggle_button.setText("启用/禁用")
        self.toggle_button.setEnabled(False)
        self.uninstall_button.setEnabled(False)

    def set_busy(self, busy: bool) -> None:
        has_plugin = self.plugin is not None
        self.toggle_button.setEnabled(has_plugin and not busy)
        self.uninstall_button.setEnabled(has_plugin and not busy)

    def _request_toggle(self) -> None:
        if self.plugin is None:
            return
        self.toggleRequested.emit(self.plugin.plugin_id, not self.plugin.enabled)

    def _request_uninstall(self) -> None:
        if self.plugin is None:
            return
        self.uninstallRequested.emit(self.plugin.plugin_id)

    def _build_detail_text(self, plugin: PluginView) -> str:
        lines = [
            f"插件名称：{plugin.name}",
            f"发布方：{plugin.publisher or '-'}",
            f"启用状态：{'已启用' if plugin.enabled else '已禁用'}",
            f"作用域：{'、'.join(plugin.scopes) if plugin.scopes else '-'}",
            f"版本：{plugin.display_version}",
            "",
            "安装记录：",
        ]

        if not plugin.records:
            lines.append("  - 没有找到安装记录")
        else:
            for index, record in enumerate(plugin.records, start=1):
                lines.extend(
                    [
                        f"  [{index}] 作用域：{record.scope}",
                        f"      版本：{record.version}",
                        f"      安装路径：{record.install_path or '-'}",
                        f"      项目路径：{record.project_path or '-'}",
                        f"      安装时间：{record.installed_at or '-'}",
                        f"      更新时间：{record.last_updated or '-'}",
                        f"      Git 提交：{record.git_commit_sha or '-'}",
                        "",
                    ]
                )

        return "\n".join(lines).strip()
