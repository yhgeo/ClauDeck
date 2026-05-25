from __future__ import annotations

from PyQt6.QtWidgets import QListWidget, QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, CardWidget, TitleLabel

from plugin_content import PluginContentBundle, PluginContentItem
from plugin_store import PluginView


class PluginDetailPanel(CardWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.plugin: PluginView | None = None

        self.title_label = TitleLabel("插件内容与用法", self)
        self.subtitle_label = CaptionLabel("请选择左侧插件", self)
        self.tabs = QTabWidget(self)
        self.overview_text = self._new_text_edit()
        self.skills_list = QListWidget(self)
        self.skills_text = self._new_text_edit()
        self.commands_list = QListWidget(self)
        self.commands_text = self._new_text_edit()
        self.agents_list = QListWidget(self)
        self.agents_text = self._new_text_edit()
        self.install_text = self._new_text_edit()
        self._skills: list[PluginContentItem] = []
        self._commands: list[PluginContentItem] = []
        self._agents: list[PluginContentItem] = []

        self._build_layout()
        self._connect_signals()
        self.show_empty()

    def _new_text_edit(self) -> QTextEdit:
        text_edit = QTextEdit(self)
        text_edit.setReadOnly(True)
        text_edit.setObjectName("contentText")
        return text_edit

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(8)
        root.addWidget(self.title_label)
        root.addWidget(self.subtitle_label)

        self.tabs.addTab(self.overview_text, "概览")
        self.tabs.addTab(self._build_item_tab(self.skills_list, self.skills_text), "Skills")
        self.tabs.addTab(self._build_item_tab(self.commands_list, self.commands_text), "Commands")
        self.tabs.addTab(self._build_item_tab(self.agents_list, self.agents_text), "Agents")
        self.tabs.addTab(self.install_text, "安装记录")
        root.addWidget(self.tabs, 1)

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
            CaptionLabel {
                color: #596a82;
                background: transparent;
            }
            QTabWidget::pane {
                border: 1px solid #cfdced;
                border-radius: 10px;
                background: #f4f8ff;
            }
            QTabBar::tab {
                color: #24324a;
                background: #edf3fa;
                border: 1px solid #cfdced;
                border-bottom: 0;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 7px 12px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                color: #101827;
                background: #ffffff;
                font-weight: 700;
            }
            QListWidget {
                background: #ffffff;
                border: 1px solid #d7e2f0;
                border-radius: 9px;
                color: #172033;
                padding: 4px;
            }
            QListWidget::item {
                padding: 7px 8px;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                color: #ffffff;
                background: #2f78d6;
            }
            QTextEdit#contentText {
                background: #ffffff;
                border: 1px solid #d7e2f0;
                border-radius: 9px;
                padding: 10px;
                color: #142038;
                selection-background-color: #2f78d6;
                selection-color: #ffffff;
                font-family: Consolas, Microsoft YaHei UI;
                font-size: 10pt;
            }
            """
        )

    def _build_item_tab(self, list_widget: QListWidget, text_edit: QTextEdit) -> QSplitter:
        splitter = QSplitter(self)
        splitter.addWidget(list_widget)
        splitter.addWidget(text_edit)
        splitter.setSizes([180, 420])
        return splitter

    def _connect_signals(self) -> None:
        self.skills_list.currentRowChanged.connect(lambda row: self._show_item(self._skills, row, self.skills_text, "未找到 Skills"))
        self.commands_list.currentRowChanged.connect(lambda row: self._show_item(self._commands, row, self.commands_text, "未找到 Commands"))
        self.agents_list.currentRowChanged.connect(lambda row: self._show_item(self._agents, row, self.agents_text, "未找到 Agents"))

    def set_plugin(self, plugin: PluginView | None) -> None:
        self.plugin = plugin
        if plugin is None:
            self.show_empty()
            return
        self.title_label.setText("插件内容与用法")
        self.subtitle_label.setText(plugin.plugin_id)
        self.overview_text.setPlainText("正在读取插件内容...")
        self._set_items(self.skills_list, self.skills_text, [], "正在读取插件内容...")
        self._set_items(self.commands_list, self.commands_text, [], "正在读取插件内容...")
        self._set_items(self.agents_list, self.agents_text, [], "正在读取插件内容...")
        self.install_text.setPlainText(self._build_install_text(plugin))

    def set_content(self, bundle: PluginContentBundle) -> None:
        if self.plugin is None or bundle.plugin_id != self.plugin.plugin_id:
            return
        self.overview_text.setPlainText(self._build_overview_text(bundle))
        self._skills = bundle.skills
        self._commands = bundle.commands
        self._agents = bundle.agents
        self._set_items(self.skills_list, self.skills_text, self._skills, "未找到 Skills")
        self._set_items(self.commands_list, self.commands_text, self._commands, "未找到 Commands")
        self._set_items(self.agents_list, self.agents_text, self._agents, "未找到 Agents")

    def set_content_error(self, plugin_id: str, message: str) -> None:
        if self.plugin is None or plugin_id != self.plugin.plugin_id:
            return
        self.overview_text.setPlainText(f"读取插件内容失败：\n{message}")

    def show_empty(self) -> None:
        self.title_label.setText("插件内容与用法")
        self.subtitle_label.setText("请选择左侧插件")
        self.overview_text.setPlainText("请选择左侧插件。")
        self._set_items(self.skills_list, self.skills_text, [], "请选择左侧插件。")
        self._set_items(self.commands_list, self.commands_text, [], "请选择左侧插件。")
        self._set_items(self.agents_list, self.agents_text, [], "请选择左侧插件。")
        self.install_text.setPlainText("暂无安装记录。")

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)

    def _set_items(self, list_widget: QListWidget, text_edit: QTextEdit, items: list[PluginContentItem], empty_text: str) -> None:
        list_widget.clear()
        for item in items:
            list_widget.addItem(f"{item.title}\n{item.relative_path}")
        if items:
            list_widget.setCurrentRow(0)
        else:
            text_edit.setPlainText(empty_text)

    def _show_item(self, items: list[PluginContentItem], row: int, text_edit: QTextEdit, empty_text: str) -> None:
        if row < 0 or row >= len(items):
            text_edit.setPlainText(empty_text)
            return
        item = items[row]
        header = f"{item.title}\n{item.relative_path}\n\n"
        if item.error:
            text_edit.setPlainText(header + f"读取失败：{item.error}")
        else:
            text_edit.setPlainText(header + item.content)

    def _build_overview_text(self, bundle: PluginContentBundle) -> str:
        lines: list[str] = []
        if bundle.manifest:
            lines.extend(["插件元数据", bundle.manifest.content, ""])
        if bundle.roots:
            lines.append("安装根目录")
            lines.extend(f"- {root}" for root in bundle.roots)
            lines.append("")
        if bundle.errors:
            lines.append("读取提示")
            lines.extend(f"- {error}" for error in bundle.errors)
            lines.append("")
        if bundle.readme:
            lines.extend(["README", bundle.readme.content])
        else:
            lines.append("未找到 README.md")
        return "\n".join(lines).strip()

    def _build_install_text(self, plugin: PluginView) -> str:
        if not plugin.records:
            return "没有找到安装记录。"
        lines: list[str] = []
        for index, record in enumerate(plugin.records, start=1):
            lines.extend(
                [
                    f"[{index}] 作用域：{record.scope}",
                    f"版本：{record.version}",
                    f"安装路径：{record.install_path or '-'}",
                    f"项目路径：{record.project_path or '-'}",
                    f"安装时间：{record.installed_at or '-'}",
                    f"更新时间：{record.last_updated or '-'}",
                    f"Git 提交：{record.git_commit_sha or '-'}",
                    "",
                ]
            )
        return "\n".join(lines).strip()
