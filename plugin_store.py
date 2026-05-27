from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class StoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class EnabledPluginsUpdateResult:
    changed: bool
    normalized: bool


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


@dataclass(frozen=True)
class SyncPreferences:
    sync_plugin_count: bool = True
    sync_plugin_enabled_state: bool = True


@dataclass(frozen=True)
class SettingsLayer:
    kind: str
    path: Path
    precedence: int


class ClaudePluginStore:
    def __init__(self, claude_dir: str | Path | None = None, project_dir: str | Path | None = None) -> None:
        self.claude_dir = Path(claude_dir).expanduser() if claude_dir else Path.home() / ".claude"
        self.project_dir = Path(project_dir).expanduser() if project_dir else None
        self.plugins_dir = self.claude_dir / "plugins"
        self.plugins_cache_dir = self.plugins_dir / "cache"
        self.installed_plugins_path = self.plugins_dir / "installed_plugins.json"
        self.settings_path = self.claude_dir / "settings.json"
        self.claudeck_state_path = self.plugins_dir / "claudeck_state.json"

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

    def load_settings_from_path(self, path: Path) -> dict[str, Any]:
        settings = self._read_json(path, {})
        if not isinstance(settings, dict):
            raise StoreError(f"Unexpected settings structure: {path}")
        return settings

    def save_settings_to_path(self, path: Path, settings: dict[str, Any]) -> None:
        self._write_json(path, settings)

    def load_settings(self) -> dict[str, Any]:
        return self.load_settings_from_path(self.settings_path)

    def save_settings(self, settings: dict[str, Any]) -> None:
        self.save_settings_to_path(self.settings_path, settings)

    def normalize_enabled_plugins(self, settings: dict[str, Any]) -> tuple[dict[str, bool], bool]:
        changed = False
        raw_enabled = settings.get("enabledPlugins")
        if not isinstance(raw_enabled, dict):
            settings["enabledPlugins"] = {}
            return settings["enabledPlugins"], True

        normalized: dict[str, bool] = {}
        for key, value in raw_enabled.items():
            normalized_key = str(key)
            normalized_value = normalize_bool(value)
            normalized[normalized_key] = normalized_value
            if normalized_key != key or normalized_value != value:
                changed = True

        if changed:
            settings["enabledPlugins"] = normalized
            return normalized, True

        return raw_enabled, False

    def load_claudeck_state(self) -> dict[str, Any]:
        state = self._read_json(
            self.claudeck_state_path,
            {
                "version": 1,
                "disabledPluginIds": [],
                "desiredEnabledPlugins": {},
                "syncPreferences": {
                    "syncPluginCount": True,
                    "syncPluginEnabledState": True,
                },
            },
        )
        if not isinstance(state, dict):
            raise StoreError(f"Unexpected ClauDeck state structure: {self.claudeck_state_path}")
        if not isinstance(state.get("disabledPluginIds"), list):
            state["disabledPluginIds"] = []
        if not isinstance(state.get("desiredEnabledPlugins"), dict):
            state["desiredEnabledPlugins"] = {}
        if not isinstance(state.get("syncPreferences"), dict):
            state["syncPreferences"] = {}
        return state

    def save_claudeck_state(self, state: dict[str, Any]) -> None:
        state["version"] = 1
        disabled_plugin_ids = state.get("disabledPluginIds", [])
        if not isinstance(disabled_plugin_ids, list):
            disabled_plugin_ids = []
        sync_preferences = state.get("syncPreferences", {})
        if not isinstance(sync_preferences, dict):
            sync_preferences = {}
        desired_enabled_plugins = state.get("desiredEnabledPlugins", {})
        if not isinstance(desired_enabled_plugins, dict):
            desired_enabled_plugins = {}
        state["disabledPluginIds"] = sorted({str(plugin_id) for plugin_id in disabled_plugin_ids}, key=str.lower)
        state["desiredEnabledPlugins"] = {
            str(plugin_id): normalize_bool(value)
            for plugin_id, value in desired_enabled_plugins.items()
        }
        state["syncPreferences"] = {
            "syncPluginCount": normalize_bool(sync_preferences.get("syncPluginCount", True)),
            "syncPluginEnabledState": normalize_bool(sync_preferences.get("syncPluginEnabledState", True)),
        }
        self._write_json(self.claudeck_state_path, state)

    def load_disabled_plugin_ids(self) -> set[str]:
        state = self.load_claudeck_state()
        disabled_plugin_ids = state.get("disabledPluginIds", [])
        if not isinstance(disabled_plugin_ids, list):
            return set()
        return {str(plugin_id) for plugin_id in disabled_plugin_ids}

    def save_disabled_plugin_ids(self, disabled_plugin_ids: set[str]) -> None:
        state = self.load_claudeck_state()
        state["disabledPluginIds"] = sorted(disabled_plugin_ids, key=str.lower)
        self.save_claudeck_state(state)

    def remember_plugin_disabled(self, plugin_id: str) -> None:
        disabled_plugin_ids = self.load_disabled_plugin_ids()
        if plugin_id in disabled_plugin_ids:
            return
        disabled_plugin_ids.add(plugin_id)
        self.save_disabled_plugin_ids(disabled_plugin_ids)

    def forget_plugin_disabled(self, plugin_id: str) -> None:
        disabled_plugin_ids = self.load_disabled_plugin_ids()
        if plugin_id not in disabled_plugin_ids:
            return
        disabled_plugin_ids.remove(plugin_id)
        self.save_disabled_plugin_ids(disabled_plugin_ids)

    def load_desired_enabled_plugins(self) -> dict[str, bool]:
        state = self.load_claudeck_state()
        desired_enabled_plugins = state.get("desiredEnabledPlugins", {})
        if not isinstance(desired_enabled_plugins, dict):
            return {}
        return {
            str(plugin_id): normalize_bool(value)
            for plugin_id, value in desired_enabled_plugins.items()
        }

    def save_desired_enabled_plugins(self, desired_enabled_plugins: dict[str, bool]) -> None:
        state = self.load_claudeck_state()
        state["desiredEnabledPlugins"] = {
            str(plugin_id): normalize_bool(value)
            for plugin_id, value in desired_enabled_plugins.items()
        }
        self.save_claudeck_state(state)

    def load_sync_preferences(self) -> SyncPreferences:
        state = self.load_claudeck_state()
        sync_preferences = state.get("syncPreferences", {})
        if not isinstance(sync_preferences, dict):
            return SyncPreferences()
        return SyncPreferences(
            sync_plugin_count=normalize_bool(sync_preferences.get("syncPluginCount", True)),
            sync_plugin_enabled_state=normalize_bool(sync_preferences.get("syncPluginEnabledState", True)),
        )

    def save_sync_preferences(self, preferences: SyncPreferences) -> None:
        state = self.load_claudeck_state()
        state["syncPreferences"] = {
            "syncPluginCount": preferences.sync_plugin_count,
            "syncPluginEnabledState": preferences.sync_plugin_enabled_state,
        }
        self.save_claudeck_state(state)

    def update_sync_preferences(
        self,
        *,
        sync_plugin_count: bool | None = None,
        sync_plugin_enabled_state: bool | None = None,
    ) -> SyncPreferences:
        current = self.load_sync_preferences()
        updated = SyncPreferences(
            sync_plugin_count=current.sync_plugin_count if sync_plugin_count is None else sync_plugin_count,
            sync_plugin_enabled_state=(
                current.sync_plugin_enabled_state
                if sync_plugin_enabled_state is None
                else sync_plugin_enabled_state
            ),
        )
        self.save_sync_preferences(updated)
        return updated

    def settings_layers(self) -> list[SettingsLayer]:
        layers = [SettingsLayer("user", self.settings_path, 10)]
        if self.project_dir is not None:
            project_claude_dir = self.project_dir / ".claude"
            layers.append(SettingsLayer("project", project_claude_dir / "settings.json", 20))
            layers.append(SettingsLayer("project-local", project_claude_dir / "settings.local.json", 30))

        deduped: list[SettingsLayer] = []
        seen: set[Path] = set()
        for layer in layers:
            resolved = layer.path.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            deduped.append(layer)
        return sorted(deduped, key=lambda layer: layer.precedence)

    def existing_settings_layers(self) -> list[SettingsLayer]:
        return [layer for layer in self.settings_layers() if layer.kind == "user" or layer.path.exists()]

    def watch_settings_paths(self) -> list[Path]:
        return [layer.path for layer in self.settings_layers()]

    def load_effective_enabled_plugins(self) -> dict[str, bool]:
        enabled_plugins: dict[str, bool] = {}
        for layer in self.settings_layers():
            if not layer.path.exists() and layer.kind != "user":
                continue
            settings = self.load_settings_from_path(layer.path)
            layer_enabled_plugins, _ = self.normalize_enabled_plugins(settings)
            enabled_plugins.update(layer_enabled_plugins)
        return enabled_plugins

    def load_explicit_plugin_state_by_layer(self) -> dict[SettingsLayer, dict[str, bool]]:
        explicit_state_by_layer: dict[SettingsLayer, dict[str, bool]] = {}
        for layer in self.settings_layers():
            if not layer.path.exists() and layer.kind != "user":
                continue
            settings = self.load_settings_from_path(layer.path)
            enabled_plugins, _ = self.normalize_enabled_plugins(settings)
            explicit_state_by_layer[layer] = dict(enabled_plugins)
        return explicit_state_by_layer

    def load_enabled_plugins_by_layer(self) -> dict[Path, dict[str, bool]]:
        enabled_plugins_by_layer: dict[Path, dict[str, bool]] = {}
        for layer in self.settings_layers():
            if not layer.path.exists() and layer.kind != "user":
                continue
            settings = self.load_settings_from_path(layer.path)
            enabled_plugins, _ = self.normalize_enabled_plugins(settings)
            enabled_plugins_by_layer[layer.path] = dict(enabled_plugins)
        return enabled_plugins_by_layer

    def _file_signature(self, path: Path) -> tuple[int, int] | None:
        if not path.exists():
            return None
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    def update_enabled_plugins_for_path(
        self,
        path: Path,
        updater: Callable[[dict[str, bool]], bool],
        *,
        create_if_missing: bool,
        max_attempts: int = 3,
    ) -> EnabledPluginsUpdateResult:
        if not create_if_missing and not path.exists():
            return EnabledPluginsUpdateResult(changed=False, normalized=False)

        for _ in range(max_attempts):
            before_signature = self._file_signature(path)
            settings = self.load_settings_from_path(path)
            after_signature = self._file_signature(path)
            if before_signature != after_signature:
                continue

            enabled_plugins, normalized = self.normalize_enabled_plugins(settings)
            updated_enabled_plugins = dict(enabled_plugins)
            updater_changed = updater(updated_enabled_plugins)
            changed = normalized or updater_changed or updated_enabled_plugins != enabled_plugins

            if not changed:
                return EnabledPluginsUpdateResult(changed=False, normalized=False)

            if self._file_signature(path) != after_signature:
                continue

            settings["enabledPlugins"] = updated_enabled_plugins
            self._write_json(path, settings)
            return EnabledPluginsUpdateResult(changed=True, normalized=normalized)

        raise StoreError(f"Settings changed while updating enabledPlugins: {path}")

    def update_enabled_plugins(
        self,
        updater: Callable[[dict[str, bool]], bool],
        *,
        max_attempts: int = 3,
    ) -> EnabledPluginsUpdateResult:
        return self.update_enabled_plugins_for_path(
            self.settings_path,
            updater,
            create_if_missing=True,
            max_attempts=max_attempts,
        )

    def list_plugin_ids(self) -> list[str]:
        registry = self.load_installed_registry()
        return sorted(registry.get("plugins", {}).keys(), key=str.lower)

    def build_plugin_views(self) -> list[PluginView]:
        registry = self.load_installed_registry()
        enabled_plugins = self.load_effective_enabled_plugins()
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
        def apply(enabled_plugins: dict[str, bool]) -> bool:
            if enabled_plugins.get(plugin_id) is enabled:
                return False
            enabled_plugins[plugin_id] = enabled
            return True

        desired_enabled_plugins = self.load_desired_enabled_plugins()
        desired_enabled_plugins[plugin_id] = enabled
        self.save_desired_enabled_plugins(desired_enabled_plugins)

        for layer in self.settings_layers():
            self.update_enabled_plugins_for_path(
                layer.path,
                apply,
                create_if_missing=layer.kind == "user",
            )
        if enabled:
            self.forget_plugin_disabled(plugin_id)
        else:
            self.remember_plugin_disabled(plugin_id)

    def remove_plugin_from_registry(self, plugin_id: str) -> bool:
        registry = self.load_installed_registry()
        plugins = registry.get("plugins", {})
        if plugin_id not in plugins:
            return False
        del plugins[plugin_id]
        self.save_installed_registry(registry)
        return True

    def remove_plugin_from_settings(self, plugin_id: str) -> bool:
        removed = False

        def apply(enabled_plugins: dict[str, bool]) -> bool:
            nonlocal removed
            if plugin_id not in enabled_plugins:
                return False
            del enabled_plugins[plugin_id]
            removed = True
            return True

        for layer in self.settings_layers():
            self.update_enabled_plugins_for_path(
                layer.path,
                apply,
                create_if_missing=False,
            )
        return removed

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


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"false", "0", "no", "off", "disabled", "disable"}:
            return False
        if normalized in {"true", "1", "yes", "on", "enabled", "enable"}:
            return True
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


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
