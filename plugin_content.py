from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from plugin_store import PluginView


MAX_CONTENT_BYTES = 100 * 1024


@dataclass(frozen=True)
class PluginContentItem:
    kind: str
    title: str
    relative_path: str
    absolute_path: Path
    content: str
    error: str | None = None


@dataclass(frozen=True)
class PluginContentBundle:
    plugin_id: str
    roots: list[Path] = field(default_factory=list)
    manifest: PluginContentItem | None = None
    readme: PluginContentItem | None = None
    skills: list[PluginContentItem] = field(default_factory=list)
    hooks: list[PluginContentItem] = field(default_factory=list)
    commands: list[PluginContentItem] = field(default_factory=list)
    agents: list[PluginContentItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def discover_plugin_content(plugin: PluginView, cache_root: Path) -> PluginContentBundle:
    roots = _collect_roots(plugin, cache_root)
    errors: list[str] = []
    manifest: PluginContentItem | None = None
    readme: PluginContentItem | None = None
    skills: list[PluginContentItem] = []
    hooks: list[PluginContentItem] = []
    commands: list[PluginContentItem] = []
    agents: list[PluginContentItem] = []

    for root in roots:
        plugin_manifest = _read_item(root / ".claude-plugin" / "plugin.json", "manifest", root)
        if plugin_manifest is not None and manifest is None:
            manifest = _format_manifest(plugin_manifest)
        if plugin_manifest is not None:
            manifest_hooks = _extract_manifest_hooks(plugin_manifest)
            if manifest_hooks is not None:
                hooks.append(manifest_hooks)

        plugin_readme = _read_item(root / "README.md", "readme", root)
        if plugin_readme is not None and readme is None:
            readme = plugin_readme

        skills.extend(_read_globbed_items(root, "skills/*/SKILL.md", "skill"))
        hooks.extend(_read_hook_items(root))
        commands.extend(_read_globbed_items(root, "commands/*.md", "command"))
        agents.extend(_read_globbed_items(root, "agents/*.md", "agent"))

    if not roots:
        errors.append("没有找到可读取的插件安装目录。")

    return PluginContentBundle(
        plugin_id=plugin.plugin_id,
        roots=roots,
        manifest=manifest,
        readme=readme,
        skills=_dedupe_items(skills),
        hooks=_dedupe_items(hooks),
        commands=_dedupe_items(commands),
        agents=_dedupe_items(agents),
        errors=errors,
    )


def _collect_roots(plugin: PluginView, cache_root: Path) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in [*plugin.install_paths, cache_root]:
        resolved = candidate.resolve(strict=False)
        if resolved in seen or not candidate.exists() or not candidate.is_dir():
            continue
        seen.add(resolved)
        roots.append(candidate)
    return roots


def _read_globbed_items(root: Path, pattern: str, kind: str) -> list[PluginContentItem]:
    base = pattern.split("/", 1)[0]
    if base.startswith("."):
        return []
    items: list[PluginContentItem] = []
    for path in sorted(root.glob(pattern), key=lambda item: str(item).lower()):
        if ".in_use" in path.parts:
            continue
        item = _read_item(path, kind, root)
        if item is not None:
            items.append(item)
    return items


def _read_hook_items(root: Path) -> list[PluginContentItem]:
    items: list[PluginContentItem] = []
    for pattern in ("hooks/*.md", "hooks/*.json", "hooks/*.toml", "hooks/*.yaml", "hooks/*.yml"):
        items.extend(_read_globbed_items(root, pattern, "hook"))
    return items


def _read_item(path: Path, kind: str, root: Path) -> PluginContentItem | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        relative_path = str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return None

    title = _title_for(path, kind)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return PluginContentItem(kind, title, relative_path, path, "", str(exc))

    truncated = len(raw) > MAX_CONTENT_BYTES
    content = raw[:MAX_CONTENT_BYTES].decode("utf-8", errors="replace")
    if truncated:
        content += "\n\n... 内容过长，已截断显示。"
    return PluginContentItem(kind, title, relative_path, path, content)


def _title_for(path: Path, kind: str) -> str:
    if kind == "skill" and path.parent.name:
        return path.parent.name
    if kind in {"hook", "command", "agent"}:
        return path.stem
    if kind == "manifest":
        return "plugin.json"
    if kind == "readme":
        return "README"
    return path.name


def _extract_manifest_hooks(item: PluginContentItem) -> PluginContentItem | None:
    try:
        payload = json.loads(item.content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "hooks" not in payload:
        return None

    return PluginContentItem(
        kind="hook",
        title="plugin.json hooks",
        relative_path=item.relative_path,
        absolute_path=item.absolute_path,
        content=json.dumps(payload["hooks"], ensure_ascii=False, indent=2),
        error=item.error,
    )


def _format_manifest(item: PluginContentItem) -> PluginContentItem:
    try:
        payload = json.loads(item.content)
    except json.JSONDecodeError:
        return item
    if not isinstance(payload, dict):
        return item

    lines: list[str] = []
    for key in ("name", "description", "author", "version"):
        value = payload.get(key)
        if value:
            lines.append(f"{key}: {value}")
    if not lines:
        lines.append(item.content)
    return PluginContentItem(
        kind=item.kind,
        title=str(payload.get("name") or item.title),
        relative_path=item.relative_path,
        absolute_path=item.absolute_path,
        content="\n".join(lines),
        error=item.error,
    )


def _dedupe_items(items: list[PluginContentItem]) -> list[PluginContentItem]:
    deduped: list[PluginContentItem] = []
    seen: set[Path] = set()
    for item in items:
        resolved = item.absolute_path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(item)
    return deduped
