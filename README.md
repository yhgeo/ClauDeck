# ClauDeck

ClauDeck 是一个用于管理 Claude Code plugins 的桌面工具，当前桌面界面已迁移到 PyQt6 + Fluent 风格。

它解决两个核心问题：
- 可视化查看、启用/禁用、卸载已安装 plugins
- 在切换模型或配置后，自动把 `enabledPlugins` 同步回 `settings.json`，避免 plugins “消失”

## 功能

- PyQt6 + Fluent 风格桌面界面
- 左侧插件卡片列表，右侧常驻详情面板
- 查看已安装插件、发布方、版本、作用域和安装记录
- 一键启用 / 禁用插件
- 一键卸载插件，并清理本地缓存与 JSON 记录
- 自动监听 Claude 配置变化，修复 `enabledPlugins`
- watcher 日志输出到 `~/.claude/logs/plugin_sync_watcher.log`

## 主要文件

- `app.py`：PyQt6 GUI 启动入口
- `ui/`：PyQt6 + Fluent 界面模块
- `plugin_manager_ui.py`：旧 Tkinter 界面参考实现，暂时保留用于回退
- `plugin_store.py`：插件与设置文件读写逻辑
- `plugin_sync.py`：`enabledPlugins` 同步逻辑
- `sync_plugins.py`：单次同步入口
- `settings_watcher.py`：后台监听与自动修复
- `claude_wrapper.py`：启动前同步包装器
- `run_plugin_manager.bat`：Windows 下快速启动 GUI

## 依赖

- Python 3.10+
- PyQt6
- PyQt6-Fluent-Widgets
- 已安装并可调用 `claude`

安装 GUI 依赖：

```bash
python -m pip install -r requirements.txt
```

## 快速开始

### 启动可视化界面

Windows:

```bat
run_plugin_manager.bat
```

或：

```bash
python app.py
```

### 手动执行一次同步

```bash
python sync_plugins.py --json
```

### 手动启动 watcher

```bash
python settings_watcher.py
```

## Claude 配置文件

ClauDeck 主要读取和维护以下文件：

- `~/.claude/plugins/installed_plugins.json`
- `~/.claude/settings.json`

## 自动修复日志

watcher 日志文件位置：

```text
~/.claude/logs/plugin_sync_watcher.log
```

用于记录：
- 启动
- 文件变化检测
- 自动补回插件映射
- 异常与退出

## 说明

当前项目以本地桌面使用为主，重点在于管理 Claude Code 用户级 plugins，并保证不同模型/配置切换时共用同一套 plugins 状态。
