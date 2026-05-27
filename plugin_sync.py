from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from plugin_store import ClaudePluginStore, SettingsLayer, SyncPreferences


GLOBAL_SCOPES = {"global", "user"}
PROJECT_SCOPES = {"local", "project", "workspace"}


@dataclass
class PluginScopePlan:
    global_plugin_ids: set[str]
    project_only_plugin_ids: set[str]
    unknown_scope_plugin_ids: set[str]


@dataclass
class SyncResult:
    changed: bool
    added_plugin_ids: list[str]
    restored_disabled_plugin_ids: list[str]
    disabled_project_plugin_ids: list[str]
    skipped_project_plugin_ids: list[str]
    unknown_scope_plugin_ids: list[str]
    normalized_enabled_plugins: bool
    changed_paths: list[str]
    updated_layers_count: int
    count_sync_applied: bool
    state_sync_applied: bool
    state_sync_mode: str
    corrected_plugin_ids: list[str]
    accepted_plugin_ids: list[str]
    desired_seeded_plugin_ids: list[str]


def sync_enabled_plugins(store: ClaudePluginStore) -> SyncResult:
    registry = store.load_installed_registry()
    plan = classify_plugin_scopes(registry)
    preferences = store.load_sync_preferences()
    explicit_state_by_layer = store.load_explicit_plugin_state_by_layer()
    disabled_plugin_ids = store.load_disabled_plugin_ids()
    stored_desired_enabled_plugins = store.load_desired_enabled_plugins()

    if preferences.sync_plugin_enabled_state:
        desired_enabled_plugins, desired_seeded_plugin_ids = seed_missing_desired_enabled_plugins(
            plugin_ids=plan.global_plugin_ids,
            layers=store.settings_layers(),
            explicit_state_by_layer=explicit_state_by_layer,
            desired_enabled_plugins=stored_desired_enabled_plugins,
            fallback_disabled_plugin_ids=disabled_plugin_ids,
        )
        canonical_enabled_state = build_canonical_enabled_state(
            plugin_ids=plan.global_plugin_ids,
            layers=store.settings_layers(),
            explicit_state_by_layer=explicit_state_by_layer,
            desired_enabled_plugins=desired_enabled_plugins,
            fallback_disabled_plugin_ids=disabled_plugin_ids,
        )
        accepted_plugin_ids: set[str] = set()
        state_sync_mode = "one_way"
    else:
        canonical_enabled_state = build_external_canonical_enabled_state(
            plugin_ids=plan.global_plugin_ids,
            layers=store.settings_layers(),
            explicit_state_by_layer=explicit_state_by_layer,
            fallback_disabled_plugin_ids=disabled_plugin_ids,
        )
        desired_enabled_plugins = dict(canonical_enabled_state)
        desired_seeded_plugin_ids = set()
        accepted_plugin_ids = {
            plugin_id
            for plugin_id, enabled in canonical_enabled_state.items()
            if stored_desired_enabled_plugins.get(plugin_id) != enabled
        }
        state_sync_mode = "two_way"

    if desired_enabled_plugins != stored_desired_enabled_plugins:
        store.save_desired_enabled_plugins(desired_enabled_plugins)

    updated_disabled_plugin_ids = {
        plugin_id for plugin_id, enabled in canonical_enabled_state.items() if not enabled
    }
    if updated_disabled_plugin_ids != disabled_plugin_ids:
        store.save_disabled_plugin_ids(updated_disabled_plugin_ids)

    added_plugin_ids: set[str] = set()
    restored_disabled_plugin_ids: set[str] = set()
    disabled_project_plugin_ids: set[str] = set()
    corrected_plugin_ids: set[str] = set()
    changed_paths: list[str] = []
    normalized_enabled_plugins = False

    for layer in store.settings_layers():
        layer_result = _sync_layer(
            store,
            layer,
            preferences,
            plan,
            canonical_enabled_state,
            added_plugin_ids,
            restored_disabled_plugin_ids,
            disabled_project_plugin_ids,
            corrected_plugin_ids,
        )
        if layer_result.changed:
            changed_paths.append(str(layer.path))
        normalized_enabled_plugins = normalized_enabled_plugins or layer_result.normalized

    return SyncResult(
        changed=bool(changed_paths) or bool(accepted_plugin_ids),
        added_plugin_ids=sorted(added_plugin_ids, key=str.lower),
        restored_disabled_plugin_ids=sorted(restored_disabled_plugin_ids, key=str.lower),
        disabled_project_plugin_ids=sorted(disabled_project_plugin_ids, key=str.lower),
        skipped_project_plugin_ids=sorted(plan.project_only_plugin_ids, key=str.lower),
        unknown_scope_plugin_ids=sorted(plan.unknown_scope_plugin_ids, key=str.lower),
        normalized_enabled_plugins=normalized_enabled_plugins,
        changed_paths=changed_paths,
        updated_layers_count=len(changed_paths),
        count_sync_applied=preferences.sync_plugin_count,
        state_sync_applied=preferences.sync_plugin_enabled_state,
        state_sync_mode=state_sync_mode,
        corrected_plugin_ids=sorted(corrected_plugin_ids, key=str.lower),
        accepted_plugin_ids=sorted(accepted_plugin_ids, key=str.lower),
        desired_seeded_plugin_ids=sorted(desired_seeded_plugin_ids, key=str.lower),
    )


def seed_missing_desired_enabled_plugins(
    *,
    plugin_ids: set[str],
    layers: list[SettingsLayer],
    explicit_state_by_layer: dict[SettingsLayer, dict[str, bool]],
    desired_enabled_plugins: dict[str, bool],
    fallback_disabled_plugin_ids: set[str],
) -> tuple[dict[str, bool], set[str]]:
    seeded_state = dict(desired_enabled_plugins)
    seeded_plugin_ids: set[str] = set()
    sorted_layers = sorted(layers, key=lambda layer: layer.precedence, reverse=True)
    for plugin_id in sorted(plugin_ids, key=str.lower):
        if plugin_id in seeded_state:
            continue
        resolved = None
        for layer in sorted_layers:
            layer_state = explicit_state_by_layer.get(layer)
            if layer_state is None or plugin_id not in layer_state:
                continue
            resolved = layer_state[plugin_id]
            break
        if resolved is None:
            resolved = plugin_id not in fallback_disabled_plugin_ids
        seeded_state[plugin_id] = resolved
        seeded_plugin_ids.add(plugin_id)
    return seeded_state, seeded_plugin_ids


def build_canonical_enabled_state(
    *,
    plugin_ids: set[str],
    layers: list[SettingsLayer],
    explicit_state_by_layer: dict[SettingsLayer, dict[str, bool]],
    desired_enabled_plugins: dict[str, bool],
    fallback_disabled_plugin_ids: set[str],
) -> dict[str, bool]:
    canonical_state: dict[str, bool] = {}
    sorted_layers = sorted(layers, key=lambda layer: layer.precedence, reverse=True)
    for plugin_id in sorted(plugin_ids, key=str.lower):
        if plugin_id in desired_enabled_plugins:
            canonical_state[plugin_id] = desired_enabled_plugins[plugin_id]
            continue
        resolved = None
        for layer in sorted_layers:
            layer_state = explicit_state_by_layer.get(layer)
            if layer_state is None or plugin_id not in layer_state:
                continue
            resolved = layer_state[plugin_id]
            break
        if resolved is None:
            resolved = plugin_id not in fallback_disabled_plugin_ids
        canonical_state[plugin_id] = resolved
    return canonical_state


def build_external_canonical_enabled_state(
    *,
    plugin_ids: set[str],
    layers: list[SettingsLayer],
    explicit_state_by_layer: dict[SettingsLayer, dict[str, bool]],
    fallback_disabled_plugin_ids: set[str],
) -> dict[str, bool]:
    canonical_state: dict[str, bool] = {}
    sorted_layers = sorted(layers, key=lambda layer: layer.precedence, reverse=True)
    for plugin_id in sorted(plugin_ids, key=str.lower):
        resolved = None
        for layer in sorted_layers:
            layer_state = explicit_state_by_layer.get(layer)
            if layer_state is None or plugin_id not in layer_state:
                continue
            resolved = layer_state[plugin_id]
            break
        if resolved is None:
            resolved = plugin_id not in fallback_disabled_plugin_ids
        canonical_state[plugin_id] = resolved
    return canonical_state


def _sync_layer(
    store: ClaudePluginStore,
    layer: SettingsLayer,
    preferences: SyncPreferences,
    plan: PluginScopePlan,
    canonical_enabled_state: dict[str, bool],
    added_plugin_ids: set[str],
    restored_disabled_plugin_ids: set[str],
    disabled_project_plugin_ids: set[str],
    corrected_plugin_ids: set[str],
):
    def apply(enabled_plugins: dict[str, bool]) -> bool:
        changed = False

        if preferences.sync_plugin_count:
            for plugin_id in sorted(plan.global_plugin_ids, key=str.lower):
                if plugin_id not in enabled_plugins:
                    enabled_plugins[plugin_id] = canonical_enabled_state[plugin_id]
                    if canonical_enabled_state[plugin_id]:
                        added_plugin_ids.add(plugin_id)
                    else:
                        restored_disabled_plugin_ids.add(plugin_id)
                    changed = True

        if preferences.sync_plugin_enabled_state:
            for plugin_id, enabled in canonical_enabled_state.items():
                if plugin_id not in enabled_plugins:
                    continue
                if enabled_plugins.get(plugin_id) is enabled:
                    continue
                enabled_plugins[plugin_id] = enabled
                corrected_plugin_ids.add(plugin_id)
                if enabled:
                    added_plugin_ids.discard(plugin_id)
                else:
                    restored_disabled_plugin_ids.add(plugin_id)
                changed = True

        if preferences.sync_plugin_count:
            for plugin_id in sorted(plan.project_only_plugin_ids, key=str.lower):
                if enabled_plugins.get(plugin_id) is True:
                    enabled_plugins[plugin_id] = False
                    disabled_project_plugin_ids.add(plugin_id)
                    changed = True

        return changed

    return store.update_enabled_plugins_for_path(
        layer.path,
        apply,
        create_if_missing=layer.kind == "user",
    )


def plugin_sync_health(store: ClaudePluginStore) -> dict[str, object]:
    registry = store.load_installed_registry()
    plan = classify_plugin_scopes(registry)
    preferences = store.load_sync_preferences()
    layers = store.settings_layers()
    explicit_state_by_layer = store.load_explicit_plugin_state_by_layer()
    desired_enabled_plugins = store.load_desired_enabled_plugins()
    canonical_state = build_canonical_enabled_state(
        plugin_ids=plan.global_plugin_ids,
        layers=layers,
        explicit_state_by_layer=explicit_state_by_layer,
        desired_enabled_plugins=desired_enabled_plugins,
        fallback_disabled_plugin_ids=store.load_disabled_plugin_ids(),
    )
    installed_plugin_ids = sorted(registry.get("plugins", {}).keys(), key=str.lower)
    global_plugin_ids = sorted(plan.global_plugin_ids, key=str.lower)
    project_only_plugin_ids = sorted(plan.project_only_plugin_ids, key=str.lower)
    unknown_scope_plugin_ids = sorted(plan.unknown_scope_plugin_ids, key=str.lower)

    layer_health: list[dict[str, object]] = []
    globally_enabled_project_plugins: set[str] = set()
    missing_plugin_ids: set[str] = set()
    disabled_plugin_ids: set[str] = set()
    for layer in layers:
        enabled_plugins = explicit_state_by_layer.get(layer, {})
        layer_missing = [plugin_id for plugin_id in global_plugin_ids if plugin_id not in enabled_plugins]
        layer_disabled = [plugin_id for plugin_id in global_plugin_ids if enabled_plugins.get(plugin_id) is False]
        layer_project_enabled = [plugin_id for plugin_id in project_only_plugin_ids if enabled_plugins.get(plugin_id) is True]
        layer_health.append(
            {
                "path": str(layer.path),
                "kind": layer.kind,
                "precedence": layer.precedence,
                "missing_enabled_plugins": layer_missing,
                "disabled_plugins": layer_disabled,
                "globally_enabled_project_plugins": layer_project_enabled,
            }
        )
        missing_plugin_ids.update(layer_missing)
        disabled_plugin_ids.update(layer_disabled)
        globally_enabled_project_plugins.update(layer_project_enabled)

    return {
        "installed_count": len(installed_plugin_ids),
        "global_plugin_ids": global_plugin_ids,
        "project_only_plugin_ids": project_only_plugin_ids,
        "unknown_scope_plugin_ids": unknown_scope_plugin_ids,
        "missing_enabled_plugins": sorted(missing_plugin_ids, key=str.lower),
        "disabled_plugins": sorted(disabled_plugin_ids, key=str.lower),
        "globally_enabled_project_plugins": sorted(globally_enabled_project_plugins, key=str.lower),
        "canonical_enabled_state": canonical_state,
        "sync_preferences": {
            "syncPluginCount": preferences.sync_plugin_count,
            "syncPluginEnabledState": preferences.sync_plugin_enabled_state,
        },
        "layers": layer_health,
        "healthy": not missing_plugin_ids and not globally_enabled_project_plugins,
    }


def classify_plugin_scopes(registry: dict[str, Any]) -> PluginScopePlan:
    global_plugin_ids: set[str] = set()
    project_only_plugin_ids: set[str] = set()
    unknown_scope_plugin_ids: set[str] = set()
    plugins = registry.get("plugins", {})
    if not isinstance(plugins, dict):
        return PluginScopePlan(set(), set(), set())

    for plugin_id, raw_records in plugins.items():
        if not isinstance(plugin_id, str):
            continue
        records = raw_records if isinstance(raw_records, list) else []
        has_global_record = False
        has_project_record = False
        has_unknown_record = False

        for record in records:
            if not isinstance(record, dict):
                has_unknown_record = True
                continue
            scope = str(record.get("scope", "")).strip().lower()
            project_path = record.get("projectPath")
            has_project_path = isinstance(project_path, str) and bool(project_path.strip())

            if has_project_path or scope in PROJECT_SCOPES:
                has_project_record = True
            elif scope in GLOBAL_SCOPES:
                has_global_record = True
            else:
                has_unknown_record = True

        if has_global_record:
            global_plugin_ids.add(plugin_id)
        elif has_project_record:
            project_only_plugin_ids.add(plugin_id)
        elif has_unknown_record:
            unknown_scope_plugin_ids.add(plugin_id)

    return PluginScopePlan(global_plugin_ids, project_only_plugin_ids, unknown_scope_plugin_ids)
