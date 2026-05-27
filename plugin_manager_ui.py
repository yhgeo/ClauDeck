from __future__ import annotations

import argparse
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from plugin_store import ClaudePluginStore, PluginView, StoreError
from plugin_sync import sync_enabled_plugins


class PluginManagerApp:
    CARD_WIDTH = 620

    def __init__(self, root: tk.Tk, claude_dir: Path | None = None, project_dir: Path | None = None, claude_bin: str = "claude") -> None:
        self.root = root
        self.store = ClaudePluginStore(claude_dir, project_dir)
        self.claude_bin = claude_bin
        self.plugins: dict[str, PluginView] = {}
        self.filtered_plugin_ids: list[str] = []
        self.card_widgets: dict[str, dict[str, object]] = {}

        self.status_var = tk.StringVar(value="准备就绪")
        self.summary_total_var = tk.StringVar(value="0")
        self.summary_enabled_var = tk.StringVar(value="0")
        self.summary_disabled_var = tk.StringVar(value="0")
        self.search_var = tk.StringVar()
        self.selected_plugin_id: str | None = None

        self.detail_title_var = tk.StringVar(value="请选择插件")
        self.detail_subtitle_var = tk.StringVar(value="左侧选中一个插件后，这里会显示详细信息。")
        self.detail_status_var = tk.StringVar(value="-")
        self.detail_publisher_var = tk.StringVar(value="-")
        self.detail_version_var = tk.StringVar(value="-")
        self.detail_scopes_var = tk.StringVar(value="-")
        self.detail_id_var = tk.StringVar(value="-")

        self.root.title("Claude 插件管理器")
        self.root.geometry("1340x820")
        self.root.minsize(1180, 720)
        self.root.configure(bg="#eef3f9")

        self._configure_styles()
        self._build_layout()
        self.refresh_plugins(initial=True)

    def _configure_styles(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("Page.TFrame", background="#eef3f9")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("Metric.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("Toolbar.TFrame", background="#eef3f9")
        style.configure("MetricTitle.TLabel", background="#ffffff", foreground="#5e6b7f", font=("Microsoft YaHei UI", 10))
        style.configure("MetricValue.TLabel", background="#ffffff", foreground="#122033", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Title.TLabel", background="#eef3f9", foreground="#122033", font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("Subtitle.TLabel", background="#eef3f9", foreground="#617287", font=("Microsoft YaHei UI", 10))
        style.configure("SectionTitle.TLabel", background="#eef3f9", foreground="#122033", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("PanelTitle.TLabel", background="#ffffff", foreground="#122033", font=("Microsoft YaHei UI", 14, "bold"))
        style.configure("PanelSubTitle.TLabel", background="#ffffff", foreground="#617287", font=("Microsoft YaHei UI", 10))
        style.configure("DetailTitle.TLabel", background="#ffffff", foreground="#122033", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("DetailSubTitle.TLabel", background="#ffffff", foreground="#617287", font=("Microsoft YaHei UI", 10))
        style.configure("FieldLabel.TLabel", background="#ffffff", foreground="#728196", font=("Microsoft YaHei UI", 9))
        style.configure("FieldValue.TLabel", background="#ffffff", foreground="#233247", font=("Microsoft YaHei UI", 10))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#617287", font=("Microsoft YaHei UI", 9))
        style.configure("StatusBar.TLabel", background="#eef3f9", foreground="#39485c", font=("Microsoft YaHei UI", 10))
        style.configure("CardButton.TButton", font=("Microsoft YaHei UI", 9), padding=(10, 6))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 9, "bold"), padding=(12, 7))

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        page = ttk.Frame(self.root, style="Page.TFrame", padding=(18, 16, 18, 14))
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)

        self._build_header(page)
        self._build_toolbar(page)
        self._build_content(page)

        status_bar = ttk.Label(page, textvariable=self.status_var, style="StatusBar.TLabel", anchor="w")
        status_bar.grid(row=3, column=0, sticky="ew", pady=(12, 0))

    def _build_header(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent, style="Page.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Claude 插件总览", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="左侧查看插件卡片，右侧实时查看详情，并可直接启用、禁用或卸载。",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_toolbar(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent, style="Toolbar.TFrame", padding=(0, 12, 0, 10))
        toolbar.grid(row=1, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)

        summary_row = ttk.Frame(toolbar, style="Toolbar.TFrame")
        summary_row.grid(row=0, column=0, sticky="w")
        self._create_metric_card(summary_row, "插件总数", self.summary_total_var).pack(side="left")
        self._create_metric_card(summary_row, "已启用", self.summary_enabled_var).pack(side="left", padx=(10, 0))
        self._create_metric_card(summary_row, "已禁用", self.summary_disabled_var).pack(side="left", padx=(10, 0))

        action_row = ttk.Frame(toolbar, style="Toolbar.TFrame")
        action_row.grid(row=0, column=1, sticky="e")

        ttk.Label(action_row, text="搜索：", style="Subtitle.TLabel").pack(side="left", padx=(0, 6))
        search_entry = ttk.Entry(action_row, textvariable=self.search_var, width=28)
        search_entry.pack(side="left")
        search_entry.bind("<KeyRelease>", lambda _event: self.on_search_change())
        ttk.Button(action_row, text="刷新", command=self.refresh_plugins, style="CardButton.TButton").pack(side="left", padx=(10, 0))
        ttk.Button(action_row, text="同步插件", command=self.sync_plugins, style="Primary.TButton").pack(side="left", padx=(8, 0))

    def _build_content(self, parent: ttk.Frame) -> None:
        content = ttk.Frame(parent, style="Page.TFrame")
        content.grid(row=2, column=0, sticky="nsew")
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(1, weight=1)

        ttk.Label(content, text="插件列表", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(content, text="当前详情", style="SectionTitle.TLabel").grid(row=0, column=1, sticky="w", padx=(14, 0), pady=(0, 8))

        list_panel = ttk.Frame(content, style="Panel.TFrame", padding=(0, 0, 0, 0))
        list_panel.grid(row=1, column=0, sticky="nsew")
        list_panel.columnconfigure(0, weight=1)
        list_panel.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(list_panel, background="#ffffff", highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(list_panel, orient="vertical", command=self.canvas.yview)
        self.cards_host = tk.Frame(self.canvas, bg="#ffffff")
        self.cards_host.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_frame = self.canvas.create_window((0, 0), window=self.cards_host, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", self._resize_canvas_window)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        detail_panel = ttk.Frame(content, style="Panel.TFrame", padding=(18, 16))
        detail_panel.grid(row=1, column=1, sticky="nsew", padx=(14, 0))
        detail_panel.columnconfigure(0, weight=1)
        detail_panel.rowconfigure(3, weight=1)

        ttk.Label(detail_panel, textvariable=self.detail_title_var, style="DetailTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(detail_panel, textvariable=self.detail_subtitle_var, style="DetailSubTitle.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        summary_box = ttk.Frame(detail_panel, style="Panel.TFrame")
        summary_box.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        summary_box.columnconfigure((0, 1), weight=1)

        self._create_detail_field(summary_box, 0, 0, "当前状态", self.detail_status_var)
        self._create_detail_field(summary_box, 0, 1, "发布方", self.detail_publisher_var, pad_left=12)
        self._create_detail_field(summary_box, 1, 0, "版本", self.detail_version_var, top=12)
        self._create_detail_field(summary_box, 1, 1, "作用域", self.detail_scopes_var, pad_left=12, top=12)

        detail_body = ttk.Frame(detail_panel, style="Panel.TFrame")
        detail_body.grid(row=3, column=0, sticky="nsew", pady=(18, 0))
        detail_body.columnconfigure(0, weight=1)
        detail_body.rowconfigure(2, weight=1)

        id_group = ttk.Frame(detail_body, style="Panel.TFrame")
        id_group.grid(row=0, column=0, sticky="ew")
        ttk.Label(id_group, text="完整标识", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(id_group, textvariable=self.detail_id_var, style="FieldValue.TLabel", wraplength=420, justify="left").pack(anchor="w", pady=(8, 0))

        record_group = ttk.Frame(detail_body, style="Panel.TFrame")
        record_group.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        ttk.Label(record_group, text="安装记录", style="PanelTitle.TLabel").pack(anchor="w")
        ttk.Label(record_group, text="包含路径、时间、项目作用域与 Git 提交信息。", style="PanelSubTitle.TLabel").pack(anchor="w", pady=(4, 0))

        text_wrap = ttk.Frame(detail_body, style="Panel.TFrame")
        text_wrap.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        text_wrap.columnconfigure(0, weight=1)
        text_wrap.rowconfigure(0, weight=1)

        self.detail_text = tk.Text(
            text_wrap,
            wrap="word",
            bg="#f8fbff",
            fg="#213042",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=("Consolas", 10),
            padx=12,
            pady=12,
        )
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(text_wrap, orient="vertical", command=self.detail_text.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.detail_text.configure(yscrollcommand=detail_scroll.set, state="disabled")

    def _create_metric_card(self, parent: ttk.Frame, title: str, value_var: tk.StringVar) -> ttk.Frame:
        card = ttk.Frame(parent, style="Metric.TFrame", padding=(16, 10))
        ttk.Label(card, text=title, style="MetricTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=value_var, style="MetricValue.TLabel").pack(anchor="w", pady=(6, 0))
        return card

    def _create_detail_field(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        *,
        pad_left: int = 0,
        top: int = 0,
    ) -> None:
        frame = ttk.Frame(parent, style="Panel.TFrame")
        frame.grid(row=row, column=column, sticky="ew", padx=(pad_left, 0), pady=(top, 0))
        ttk.Label(frame, text=label, style="FieldLabel.TLabel").pack(anchor="w")
        ttk.Label(frame, textvariable=variable, style="FieldValue.TLabel", wraplength=180, justify="left").pack(anchor="w", pady=(6, 0))

    def _resize_canvas_window(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.canvas_frame, width=event.width)

    def _on_mousewheel(self, event: tk.Event[tk.Misc]) -> None:
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def on_search_change(self) -> None:
        previous_selection = self.selected_plugin_id
        self.render_cards()
        self._ensure_valid_selection_after_filter()
        if self.selected_plugin_id != previous_selection:
            self.render_cards()
        self.update_detail_panel()

    def sync_plugins(self) -> None:
        try:
            result = sync_enabled_plugins(self.store)
        except StoreError as exc:
            messagebox.showerror("同步失败", str(exc))
            self.status_var.set(f"同步失败：{exc}")
            return

        self.refresh_plugins()
        self.status_var.set(
            "同步完成："
            f"变更={result.changed}，"
            f"新增启用={len(result.added_plugin_ids)}，"
            f"恢复禁用={len(result.restored_disabled_plugin_ids)}，"
            f"禁用项目范围={len(result.disabled_project_plugin_ids)}，"
            f"跳过项目范围={len(result.skipped_project_plugin_ids)}"
        )

    def refresh_plugins(self, initial: bool = False) -> None:
        try:
            if initial:
                sync_enabled_plugins(self.store)
            plugins = self.store.build_plugin_views()
        except StoreError as exc:
            messagebox.showerror("加载失败", str(exc))
            self.status_var.set(f"加载失败：{exc}")
            return

        self.plugins = {plugin.plugin_id: plugin for plugin in plugins}
        self._update_summary(plugins)
        self.render_cards()
        self._ensure_valid_selection_after_filter(default_to_first=True)
        self.update_detail_panel()
        self.status_var.set(f"已加载 {len(plugins)} 个插件。")

    def _update_summary(self, plugins: list[PluginView]) -> None:
        enabled_count = sum(1 for plugin in plugins if plugin.enabled)
        disabled_count = len(plugins) - enabled_count
        self.summary_total_var.set(str(len(plugins)))
        self.summary_enabled_var.set(str(enabled_count))
        self.summary_disabled_var.set(str(disabled_count))

    def render_cards(self) -> None:
        for child in self.cards_host.winfo_children():
            child.destroy()
        self.card_widgets.clear()

        filtered_plugins = self.filtered_plugins()
        self.filtered_plugin_ids = [plugin.plugin_id for plugin in filtered_plugins]

        if not filtered_plugins:
            empty = tk.Frame(self.cards_host, bg="#ffffff", padx=24, pady=24, highlightbackground="#d7dfeb", highlightthickness=1)
            empty.pack(fill="x", padx=14, pady=14)
            tk.Label(empty, text="没有匹配的插件", bg="#ffffff", fg="#142033", font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
            tk.Label(empty, text="请调整搜索关键词，或点击“同步插件”重新读取状态。", bg="#ffffff", fg="#617287", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(8, 0))
            return

        for plugin in filtered_plugins:
            self._create_plugin_card(plugin)

    def filtered_plugins(self) -> list[PluginView]:
        keyword = self.search_var.get().strip().lower()
        plugins = list(self.plugins.values())
        if not keyword:
            return plugins

        def matches(plugin: PluginView) -> bool:
            haystacks = [
                plugin.plugin_id,
                plugin.name,
                plugin.publisher,
                " ".join(plugin.scopes),
                " ".join(plugin.versions),
            ]
            return any(keyword in value.lower() for value in haystacks if value)

        return [plugin for plugin in plugins if matches(plugin)]

    def _create_plugin_card(self, plugin: PluginView) -> None:
        palette = self._palette(plugin.plugin_id, plugin.enabled)
        outer = tk.Frame(
            self.cards_host,
            bg=palette["border"],
            padx=1,
            pady=1,
            highlightthickness=0,
            cursor="hand2",
        )
        outer.pack(fill="x", padx=14, pady=(0, 12))

        inner = tk.Frame(outer, bg=palette["surface"], padx=16, pady=14, cursor="hand2")
        inner.pack(fill="both", expand=True)

        header = tk.Frame(inner, bg=palette["surface"], cursor="hand2")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        title_wrap = tk.Frame(header, bg=palette["surface"], cursor="hand2")
        title_wrap.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_wrap,
            text=plugin.name,
            bg=palette["surface"],
            fg="#142033",
            font=("Microsoft YaHei UI", 13, "bold"),
            cursor="hand2",
        ).pack(side="left")
        tk.Label(
            title_wrap,
            text="已启用" if plugin.enabled else "已禁用",
            bg=palette["badge_bg"],
            fg=palette["badge_fg"],
            padx=10,
            pady=4,
            font=("Microsoft YaHei UI", 9, "bold"),
            cursor="hand2",
        ).pack(side="left", padx=(10, 0))

        tk.Label(
            header,
            text=plugin.plugin_id,
            bg=palette["surface"],
            fg="#607086",
            font=("Consolas", 9),
            anchor="w",
            cursor="hand2",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))

        meta = tk.Frame(inner, bg=palette["surface"], cursor="hand2")
        meta.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        meta.grid_columnconfigure((0, 1, 2), weight=1)

        self._create_meta_block(meta, 0, "发布方", plugin.publisher or "-", palette)
        self._create_meta_block(meta, 1, "版本", plugin.display_version, palette)
        self._create_meta_block(meta, 2, "作用域", "、".join(plugin.scopes) if plugin.scopes else "-", palette)

        action_row = tk.Frame(inner, bg=palette["surface"])
        action_row.grid(row=2, column=0, sticky="w", pady=(16, 0))

        toggle_text = "禁用插件" if plugin.enabled else "启用插件"
        ttk.Button(
            action_row,
            text=toggle_text,
            style="CardButton.TButton",
            command=lambda pid=plugin.plugin_id, enabled=not plugin.enabled: self.set_plugin_enabled(pid, enabled),
        ).pack(side="left")
        ttk.Button(
            action_row,
            text="删除卸载",
            style="CardButton.TButton",
            command=lambda pid=plugin.plugin_id: self.uninstall_plugin(pid),
        ).pack(side="left", padx=(8, 0))

        widgets_to_bind = [outer, inner, header, title_wrap, meta, action_row]
        for widget in widgets_to_bind:
            widget.bind("<Button-1>", lambda _event, pid=plugin.plugin_id: self.select_plugin(pid))
            widget.bind("<Enter>", lambda _event, pid=plugin.plugin_id: self.on_card_hover(pid, True))
            widget.bind("<Leave>", lambda _event, pid=plugin.plugin_id: self.on_card_hover(pid, False))
        self._bind_descendants_for_selection(inner, plugin.plugin_id)

        self.card_widgets[plugin.plugin_id] = {
            "outer": outer,
            "inner": inner,
            "header": header,
            "title_wrap": title_wrap,
            "meta": meta,
            "palette": palette,
        }

    def _create_meta_block(self, parent: tk.Frame, column: int, title: str, value: str, palette: dict[str, str]) -> None:
        block = tk.Frame(parent, bg=palette["group_bg"], padx=12, pady=10, cursor="hand2")
        block.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0))
        tk.Label(block, text=title, bg=palette["group_bg"], fg="#718096", font=("Microsoft YaHei UI", 9), cursor="hand2").pack(anchor="w")
        tk.Label(
            block,
            text=value,
            bg=palette["group_bg"],
            fg="#223247",
            font=("Microsoft YaHei UI", 10),
            wraplength=150,
            justify="left",
            cursor="hand2",
        ).pack(anchor="w", pady=(6, 0))

    def _bind_descendants_for_selection(self, widget: tk.Misc, plugin_id: str) -> None:
        for child in widget.winfo_children():
            if isinstance(child, (tk.Frame, tk.Label)):
                child.bind("<Button-1>", lambda _event, pid=plugin_id: self.select_plugin(pid))
                child.bind("<Enter>", lambda _event, pid=plugin_id: self.on_card_hover(pid, True))
                child.bind("<Leave>", lambda _event, pid=plugin_id: self.on_card_hover(pid, False))
                self._bind_descendants_for_selection(child, plugin_id)

    def _palette(self, plugin_id: str, enabled: bool, hovered: bool = False) -> dict[str, str]:
        selected = plugin_id == self.selected_plugin_id
        if selected:
            return {
                "border": "#4e89f5",
                "surface": "#edf5ff",
                "group_bg": "#dfeeff",
                "badge_bg": "#d9f0df" if enabled else "#f4dfdb",
                "badge_fg": "#1f6a41" if enabled else "#9b4a3b",
            }
        if hovered:
            return {
                "border": "#8fb5ff" if enabled else "#d6c5bf",
                "surface": "#f7fbff" if enabled else "#fbf9f8",
                "group_bg": "#edf5ff" if enabled else "#f4efed",
                "badge_bg": "#e3f5e8" if enabled else "#f7e8e4",
                "badge_fg": "#1f6a41" if enabled else "#9b4a3b",
            }
        return {
            "border": "#cfe0d8" if enabled else "#e0d7d4",
            "surface": "#ffffff",
            "group_bg": "#f4fbf6" if enabled else "#faf7f6",
            "badge_bg": "#e6f6eb" if enabled else "#f6e9e5",
            "badge_fg": "#247a49" if enabled else "#9a4b3c",
        }

    def on_card_hover(self, plugin_id: str, hovered: bool) -> None:
        widget_set = self.card_widgets.get(plugin_id)
        plugin = self.plugins.get(plugin_id)
        if widget_set is None or plugin is None or plugin_id == self.selected_plugin_id:
            return
        self._apply_palette(widget_set, self._palette(plugin_id, plugin.enabled, hovered=hovered))

    def _apply_palette(self, widget_set: dict[str, object], palette: dict[str, str]) -> None:
        outer = widget_set["outer"]
        inner = widget_set["inner"]
        header = widget_set["header"]
        title_wrap = widget_set["title_wrap"]
        meta = widget_set["meta"]
        outer.configure(bg=palette["border"])
        inner.configure(bg=palette["surface"])
        header.configure(bg=palette["surface"])
        title_wrap.configure(bg=palette["surface"])
        meta.configure(bg=palette["surface"])
        self._recolor_children(inner, palette)
        widget_set["palette"] = palette

    def _recolor_children(self, widget: tk.Misc, palette: dict[str, str]) -> None:
        for child in widget.winfo_children():
            if isinstance(child, tk.Label):
                current_text = child.cget("text")
                if current_text in {"已启用", "已禁用"}:
                    child.configure(bg=palette["badge_bg"], fg=palette["badge_fg"])
                else:
                    parent_bg = child.master.cget("bg")
                    if child.cget("font") == ("Consolas", 9):
                        child.configure(bg=parent_bg, fg="#607086")
                    else:
                        child.configure(bg=parent_bg)
            elif isinstance(child, tk.Frame):
                name = str(child)
                if child.master == widget and child.cget("bg") not in {palette["group_bg"], palette["surface"]}:
                    child.configure(bg=palette["surface"])
                elif child.master != widget:
                    child.configure(bg=palette["group_bg"])
                self._recolor_children(child, palette)

    def _ensure_valid_selection_after_filter(self, default_to_first: bool = False) -> None:
        if self.selected_plugin_id in self.filtered_plugin_ids:
            return
        if default_to_first and self.filtered_plugin_ids:
            self.selected_plugin_id = self.filtered_plugin_ids[0]
            self.render_cards()
            return
        self.selected_plugin_id = self.filtered_plugin_ids[0] if self.filtered_plugin_ids else None

    def select_plugin(self, plugin_id: str) -> None:
        if plugin_id == self.selected_plugin_id:
            return
        self.selected_plugin_id = plugin_id
        self.render_cards()
        self.update_detail_panel()

    def update_detail_panel(self) -> None:
        plugin = self.plugins.get(self.selected_plugin_id) if self.selected_plugin_id else None
        if plugin is None:
            self.detail_title_var.set("请选择插件")
            self.detail_subtitle_var.set("左侧选中一个插件后，这里会显示详细信息。")
            self.detail_status_var.set("-")
            self.detail_publisher_var.set("-")
            self.detail_version_var.set("-")
            self.detail_scopes_var.set("-")
            self.detail_id_var.set("-")
            self._set_detail_text("暂无详细信息。")
            return

        self.detail_title_var.set(plugin.name)
        self.detail_subtitle_var.set("左侧列表中当前选中的插件详情。")
        self.detail_status_var.set("已启用" if plugin.enabled else "已禁用")
        self.detail_publisher_var.set(plugin.publisher or "-")
        self.detail_version_var.set(plugin.display_version)
        self.detail_scopes_var.set("、".join(plugin.scopes) if plugin.scopes else "-")
        self.detail_id_var.set(plugin.plugin_id)
        self._set_detail_text(self._build_detail_text(plugin))

    def _set_detail_text(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", text)
        self.detail_text.configure(state="disabled")

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            messagebox.showinfo("未找到插件", "请先选择一个插件。")
            return
        try:
            self.store.set_plugin_enabled(plugin.plugin_id, enabled)
        except StoreError as exc:
            messagebox.showerror("更新失败", str(exc))
            self.status_var.set(f"更新失败：{exc}")
            return

        self.selected_plugin_id = plugin_id
        self.refresh_plugins()
        self.status_var.set(f"插件 {plugin.plugin_id} {'已启用' if enabled else '已禁用'}。")

    def uninstall_plugin(self, plugin_id: str) -> None:
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            messagebox.showinfo("未找到插件", "请先选择一个插件。")
            return

        confirmed = messagebox.askyesno(
            "确认卸载",
            f"确定要卸载插件 {plugin.plugin_id} 吗？\n\n"
            "这会调用 `claude plugin uninstall`，同时清理缓存残留并删除 JSON 中的插件记录。",
        )
        if not confirmed:
            return

        try:
            self.store.uninstall_plugin(plugin.plugin_id, claude_bin=self.claude_bin)
            sync_enabled_plugins(self.store)
        except StoreError as exc:
            messagebox.showerror("卸载失败", str(exc))
            self.status_var.set(f"卸载失败：{exc}")
            return

        if self.selected_plugin_id == plugin_id:
            self.selected_plugin_id = None
        self.refresh_plugins()
        self.status_var.set(f"插件 {plugin.plugin_id} 已卸载。")

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


def main() -> int:
    parser = argparse.ArgumentParser(description="可视化 Claude 插件管理器")
    parser.add_argument("--claude-dir", type=Path, default=None, help="覆盖默认的 ~/.claude 目录")
    parser.add_argument("--project-dir", type=Path, default=None, help="覆盖当前项目目录")
    parser.add_argument("--claude-bin", default="claude", help="Claude 可执行文件名或路径")
    args = parser.parse_args()

    root = tk.Tk()
    PluginManagerApp(root, claude_dir=args.claude_dir, project_dir=args.project_dir, claude_bin=args.claude_bin)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
