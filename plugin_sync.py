from __future__ import annotations

from dataclasses import dataclass

from plugin_store import ClaudePluginStore


@dataclass
class SyncResult:
    changed: bool
    added_plugin_ids: list[str]
    normalized_enabled_plugins: bool


def sync_enabled_plugins(store: ClaudePluginStore) -> SyncResult:
    registry = store.load_installed_registry()
    settings = store.load_settings()
    enabled_plugins, normalized = store.normalize_enabled_plugins(settings)
    changed = normalized
    added_plugin_ids: list[str] = []

    for plugin_id in registry.get("plugins", {}):
        if plugin_id not in enabled_plugins:
            enabled_plugins[plugin_id] = True
            added_plugin_ids.append(plugin_id)
            changed = True

    if changed:
        store.save_settings(settings)

    return SyncResult(
        changed=changed,
        added_plugin_ids=sorted(added_plugin_ids, key=str.lower),
        normalized_enabled_plugins=normalized,
    )


def plugin_sync_health(store: ClaudePluginStore) -> dict[str, object]:
    registry = store.load_installed_registry()
    settings = store.load_settings()
    enabled_plugins, normalized = store.normalize_enabled_plugins(settings)
    installed_plugin_ids = sorted(registry.get("plugins", {}).keys(), key=str.lower)
    missing_plugin_ids = [plugin_id for plugin_id in installed_plugin_ids if plugin_id not in enabled_plugins]
    disabled_plugin_ids = [plugin_id for plugin_id in installed_plugin_ids if enabled_plugins.get(plugin_id) is False]

    return {
        "installed_count": len(installed_plugin_ids),
        "missing_enabled_plugins": missing_plugin_ids,
        "disabled_plugins": disabled_plugin_ids,
        "normalized_enabled_plugins": normalized,
        "healthy": not missing_plugin_ids,
    }
