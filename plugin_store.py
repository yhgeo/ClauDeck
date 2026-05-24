from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class StoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class PluginInstallRecord:
    scope: str
    install_path: Path | None
    version: str
    installed_at: str | None = None
    last_updated: str | None = None
    git_commit_sha: str | None = None
    project_path: Path | None = None


@dataclass
class PluginView:
    plugin_id: str
    name: str
    publisher: str
    enabled: bool
    scopes: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    records: list[PluginInstallRecord] = field(default_factory=list)

    @property
    def display_version(self) -> str:
        return ", ".join(self.versions) if self.versions else "-"

    @property
    def install_paths(self) -> list[Path]:
        return [record.install_path for record in self.records if record.install_path is not None]


class ClaudePluginStore:
    def __init__(self, claude_dir: str | Path | None = None) -> None:
        self.claude_dir = Path(claude_dir).expanduser() if claude_dir else Path.home() / ".claude"
        self.plugins_dir = self.claude_dir / "plugins"
        self.plugins_cache_dir = self.plugins_dir / "cache"
        self.installed_plugins_path = self.plugins_dir / "installed_plugins.json"
        self.settings_path = self.claude_dir / "settings.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except json.JSONDecodeError as exc:
            raise StoreError(f"Invalid JSON: {path}\n{exc}") from exc
        except OSError as exc:
            raise StoreError(f"Failed to read file: {path}\n{exc}") from exc

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(temp_name, path)
        except OSError as exc:
            raise StoreError(f"Failed to write file: {path}\n{exc}") from exc
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load_installed_registry(self) -> dict[str, Any]:
        registry = self._read_json(self.installed_plugins_path, {"version": 2, "plugins": {}})
        if not isinstance(registry, dict):
            raise StoreError(f"Unexpected registry structure: {self.installed_plugins_path}")
        plugins = registry.get("plugins")
        if plugins is None:
            registry["plugins"] = {}
        elif not isinstance(plugins, dict):
            raise StoreError(f"Unexpected plugins structure: {self.installed_plugins_path}")
        return registry

    def save_installed_registry(self, registry: dict[str, Any]) -> None:
        self._write_json(self.installed_plugins_path, registry)

    def load_settings(self) -> dict[str, Any]:
        settings = self._read_json(self.settings_path, {})
        if not isinstance(settings, dict):
            raise StoreError(f"Unexpected settings structure: {self.settings_path}")
        return settings

    def save_settings(self, settings: dict[str, Any]) -> None:
        self._write_json(self.settings_path, settings)

    def normalize_enabled_plugins(self, settings: dict[str, Any]) -> tuple[dict[str, bool], bool]:
        changed = False
        raw_enabled = settings.get("enabledPlugins")
        if not isinstance(raw_enabled, dict):
            settings["enabledPlugins"] = {}
            return settings["enabledPlugins"], True

        normalized: dict[str, bool] = {}
        for key, value in raw_enabled.items():
            normalized_key = str(key)
            normalized_value = value if isinstance(value, bool) else bool(value)
            normalized[normalized_key] = normalized_value
            if normalized_key != key or normalized_value != value:
                changed = True

        if changed:
            settings["enabledPlugins"] = normalized
            return normalized, True

        return raw_enabled, False

    def list_plugin_ids(self) -> list[str]:
        registry = self.load_installed_registry()
        return sorted(registry.get("plugins", {}).keys(), key=str.lower)

    def build_plugin_views(self) -> list[PluginView]:
        registry = self.load_installed_registry()
        settings = self.load_settings()
        enabled_plugins, _ = self.normalize_enabled_plugins(settings)
        views: list[PluginView] = []

        for plugin_id, raw_records in registry.get("plugins", {}).items():
            if not isinstance(plugin_id, str) or not isinstance(raw_records, list):
                continue

            name, publisher = split_plugin_id(plugin_id)
            records: list[PluginInstallRecord] = []
            scopes: list[str] = []
            versions: list[str] = []

            for raw_record in raw_records:
                if not isinstance(raw_record, dict):
                    continue
                scope = str(raw_record.get("scope", "unknown"))
                version = str(raw_record.get("version", "-"))
                install_path = _maybe_path(raw_record.get("installPath"))
                project_path = _maybe_path(raw_record.get("projectPath"))
                record = PluginInstallRecord(
                    scope=scope,
                    install_path=install_path,
                    version=version,
                    installed_at=_maybe_string(raw_record.get("installedAt")),
                    last_updated=_maybe_string(raw_record.get("lastUpdated")),
                    git_commit_sha=_maybe_string(raw_record.get("gitCommitSha")),
                    project_path=project_path,
                )
                records.append(record)
                if scope not in scopes:
                    scopes.append(scope)
                if version not in versions:
                    versions.append(version)

            views.append(
                PluginView(
                    plugin_id=plugin_id,
                    name=name,
                    publisher=publisher,
                    enabled=bool(enabled_plugins.get(plugin_id, False)),
                    scopes=scopes,
                    versions=versions,
                    records=records,
                )
            )

        return sorted(views, key=lambda view: (view.name.lower(), view.publisher.lower(), view.plugin_id.lower()))

    def get_plugin_view(self, plugin_id: str) -> PluginView:
        for plugin in self.build_plugin_views():
            if plugin.plugin_id == plugin_id:
                return plugin
        raise StoreError(f"Plugin not found: {plugin_id}")

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        settings = self.load_settings()
        enabled_plugins, _ = self.normalize_enabled_plugins(settings)
        enabled_plugins[plugin_id] = enabled
        self.save_settings(settings)

    def remove_plugin_from_registry(self, plugin_id: str) -> bool:
        registry = self.load_installed_registry()
        plugins = registry.get("plugins", {})
        if plugin_id not in plugins:
            return False
        del plugins[plugin_id]
        self.save_installed_registry(registry)
        return True

    def remove_plugin_from_settings(self, plugin_id: str) -> bool:
        settings = self.load_settings()
        enabled_plugins, changed = self.normalize_enabled_plugins(settings)
        if plugin_id not in enabled_plugins:
            if changed:
                self.save_settings(settings)
            return False
        del enabled_plugins[plugin_id]
        self.save_settings(settings)
        return True

    def plugin_cache_root(self, plugin_id: str) -> Path:
        name, publisher = split_plugin_id(plugin_id)
        if publisher:
            return self.plugins_cache_dir / publisher / name
        return self.plugins_cache_dir / name

    def cleanup_plugin_cache(self, plugin: PluginView) -> list[Path]:
        removed_paths: list[Path] = []
        targets: list[Path] = []
        targets.extend(plugin.install_paths)
        targets.append(self.plugin_cache_root(plugin.plugin_id))

        unique_targets: list[Path] = []
        seen: set[Path] = set()
        for target in targets:
            resolved = target.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_targets.append(target)

        for target in sorted(unique_targets, key=lambda item: len(item.parts), reverse=True):
            if not target.exists():
                continue
            if not is_relative_to(target, self.plugins_cache_dir):
                continue
            shutil.rmtree(target, ignore_errors=True)
            removed_paths.append(target)

        self._prune_empty_cache_dirs(plugin.plugin_id)
        return removed_paths

    def _prune_empty_cache_dirs(self, plugin_id: str) -> None:
        plugin_root = self.plugin_cache_root(plugin_id)
        name_root = plugin_root
        publisher_root = plugin_root.parent

        for candidate in (name_root, publisher_root):
            if candidate.exists() and is_relative_to(candidate, self.plugins_cache_dir):
                try:
                    candidate.rmdir()
                except OSError:
                    pass

    def uninstall_plugin(self, plugin_id: str, claude_bin: str = "claude") -> subprocess.CompletedProcess[str]:
        plugin = self.get_plugin_view(plugin_id)
        completed = subprocess.run(
            [claude_bin, "plugin", "uninstall", plugin_id],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            error_output = (completed.stderr or completed.stdout or "").strip()
            raise StoreError(f"Failed to uninstall plugin {plugin_id}\n{error_output}")

        self.cleanup_plugin_cache(plugin)
        self.remove_plugin_from_registry(plugin_id)
        self.remove_plugin_from_settings(plugin_id)
        return completed


def split_plugin_id(plugin_id: str) -> tuple[str, str]:
    if "@" not in plugin_id:
        return plugin_id, ""
    name, publisher = plugin_id.rsplit("@", 1)
    return name, publisher


def is_relative_to(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _maybe_path(value: Any) -> Path | None:
    if isinstance(value, str) and value.strip():
        return Path(value)
    return None


def _maybe_string(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
