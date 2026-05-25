from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, CardWidget, TitleLabel

from plugin_content import PluginContentBundle, PluginContentItem
from plugin_store import PluginView


class PluginDetailPanel(CardWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.plugin: PluginView | None = None

        self.title_label = TitleLabel("插件详情", self)
        self.subtitle_label = CaptionLabel("选择左侧插件查看内容与安装记录", self)
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

    def _new_text_edit(self) -> QTextBrowser:
        text_edit = QTextBrowser(self)
        text_edit.setReadOnly(True)
        text_edit.setOpenExternalLinks(True)
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
            QTextBrowser#contentText {
                background: #ffffff;
                border: 1px solid #d7e2f0;
                border-radius: 9px;
                padding: 10px;
                color: #142038;
                selection-background-color: #2f78d6;
                selection-color: #ffffff;
                font-family: Microsoft YaHei UI;
                font-size: 10pt;
            }
            """
        )

    def _build_item_tab(self, list_widget: QListWidget, text_edit: QTextBrowser) -> QSplitter:
        list_widget.setMinimumWidth(240)
        list_widget.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        splitter = QSplitter(self)
        splitter.addWidget(list_widget)
        splitter.addWidget(text_edit)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 520])
        return splitter

    def _connect_signals(self) -> None:
        self.skills_list.currentRowChanged.connect(lambda row: self._show_item(self._skills, row, self.skills_text, "未找到 Skills"))
        self.commands_list.currentRowChanged.connect(lambda row: self._show_item(self._commands, row, self.commands_text, "未找到 Commands"))
        self.agents_list.currentRowChanged.connect(lambda row: self._show_item(self._agents, row, self.agents_text, "未找到 Agents"))

    def set_plugin(self, plugin: PluginView | None) -> None:
        self.plugin = plugin
        self._skills = []
        self._commands = []
        self._agents = []
        if plugin is None:
            self.show_empty()
            return
        self.title_label.setText("插件详情")
        self.subtitle_label.setText(plugin.plugin_id)
        self._set_content_text(self.overview_text, "正在读取插件内容...")
        self._set_items(self.skills_list, self.skills_text, [], "正在读取插件内容...")
        self._set_items(self.commands_list, self.commands_text, [], "正在读取插件内容...")
        self._set_items(self.agents_list, self.agents_text, [], "正在读取插件内容...")
        self._set_content_text(self.install_text, self._build_install_text(plugin))

    def set_content(self, bundle: PluginContentBundle) -> None:
        if self.plugin is None or bundle.plugin_id != self.plugin.plugin_id:
            return
        self._set_content_text(self.overview_text, self._build_overview_markdown(bundle), markdown=True)
        self._skills = bundle.skills
        self._commands = bundle.commands
        self._agents = bundle.agents
        self._set_items(self.skills_list, self.skills_text, self._skills, "未找到 Skills")
        self._set_items(self.commands_list, self.commands_text, self._commands, "未找到 Commands")
        self._set_items(self.agents_list, self.agents_text, self._agents, "未找到 Agents")

    def set_content_error(self, plugin_id: str, message: str) -> None:
        if self.plugin is None or plugin_id != self.plugin.plugin_id:
            return
        error_text = f"读取插件内容失败：\n{message}"
        self._skills = []
        self._commands = []
        self._agents = []
        self._set_content_text(self.overview_text, error_text)
        self._set_items(self.skills_list, self.skills_text, [], error_text)
        self._set_items(self.commands_list, self.commands_text, [], error_text)
        self._set_items(self.agents_list, self.agents_text, [], error_text)

    def show_empty(self) -> None:
        self.title_label.setText("插件详情")
        self.subtitle_label.setText("选择左侧插件查看内容与安装记录")
        self._set_content_text(self.overview_text, "请选择左侧插件。")
        self._set_items(self.skills_list, self.skills_text, [], "请选择左侧插件。")
        self._set_items(self.commands_list, self.commands_text, [], "请选择左侧插件。")
        self._set_items(self.agents_list, self.agents_text, [], "请选择左侧插件。")
        self._set_content_text(self.install_text, "暂无安装记录。")

    def set_busy(self, busy: bool) -> None:
        self.setEnabled(not busy)

    def _set_content_text(self, text_edit: QTextBrowser, text: str, *, markdown: bool = False) -> None:
        if markdown:
            text_edit.setMarkdown(text)
        else:
            text_edit.setPlainText(text)
        text_edit.verticalScrollBar().setValue(0)

    def _set_items(self, list_widget: QListWidget, text_edit: QTextBrowser, items: list[PluginContentItem], empty_text: str) -> None:
        list_widget.clear()
        for item in items:
            list_item = QListWidgetItem(f"{item.title}\n{item.relative_path}")
            list_item.setToolTip(f"{item.title}\n{item.relative_path}\n{item.absolute_path}")
            list_widget.addItem(list_item)
        if items:
            list_widget.setCurrentRow(0)
        else:
            self._set_content_text(text_edit, empty_text)

    def _show_item(self, items: list[PluginContentItem], row: int, text_edit: QTextBrowser, empty_text: str) -> None:
        if row < 0 or row >= len(items):
            self._set_content_text(text_edit, empty_text)
            return
        item = items[row]
        header = f"# {item.title}\n\n`{item.relative_path}`\n\n---\n\n"
        if item.error:
            self._set_content_text(text_edit, header + f"读取失败：{item.error}", markdown=True)
        else:
            self._set_content_text(text_edit, header + item.content, markdown=True)

    def _build_overview_markdown(self, bundle: PluginContentBundle) -> str:
        lines: list[str] = []
        if bundle.manifest:
            lines.extend(["## 插件元数据", ""])
            if bundle.manifest.error:
                lines.extend([f"读取失败：{bundle.manifest.error}", ""])
            else:
                lines.extend(["```text", bundle.manifest.content, "```", ""])
        if bundle.roots:
            lines.extend(["## 安装根目录", ""])
            lines.extend(f"- `{root}`" for root in bundle.roots)
            lines.append("")
        if bundle.errors:
            lines.extend(["## 读取提示", ""])
            lines.extend(f"- {error}" for error in bundle.errors)
            lines.append("")
        if bundle.readme:
            lines.extend(["## README", ""])
            if bundle.readme.error:
                lines.append(f"读取失败：{bundle.readme.error}")
            else:
                lines.append(bundle.readme.content)
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
