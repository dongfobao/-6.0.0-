from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from live_polling_commands import build_default_polling_commands, normalize_polling_commands


DEFAULT_POLLING_GROUPS: dict[str, dict[str, Any]] = {
    "fast": {"intervalMs": 1000, "targets": ["flow", "breath_states", "heating_states", "alarm_states"]},
    "standard": {"intervalMs": 5000, "targets": ["temperature", "humidity", "pressure", "sensor_alarms"]},
    "slow": {"intervalMs": 30000, "targets": ["holding_registers", "coils", "task_config"]},
}

DEFAULT_DEVICE_PROFILE: dict[str, Any] = {
    "name": "New Device",
    "deviceType": "YLDQ-4.0.6",
    "protocolType": "modbus",
    "transport": "rtu",
    "address": "COM1",
    "slaveId": 1,
    "baudrate": 9600,
    "databits": 8,
    "stopbits": 1,
    "parity": "N",
    "timeoutMs": 1200,
    "retryCount": 2,
    "pollingProfile": "default-yldq",
    "pollingSettings": deepcopy(DEFAULT_POLLING_GROUPS),
    "pollingCommands": build_default_polling_commands(),
    "enabled": True,
}

LEGACY_CATALOG_ITEM_IDS: dict[str, str] = {
    "coil.drain_online": "coil.valve_online",
    "coil.cht_online": "coil.antifreeze_online",
    "input.drain_state": "input.valve_state",
    "input.valve_state": "input.antifreeze_state",
}


def _normalize_interval_ms(value: Any, default_value: int) -> int:
    try:
        interval_ms = int(value)
    except (TypeError, ValueError):
        interval_ms = int(default_value)
    return max(100, interval_ms)


def _normalize_targets(value: Any, default_value: list[str]) -> list[str]:
    if not isinstance(value, list):
        return deepcopy(default_value)
    targets = [str(item).strip() for item in value if str(item).strip()]
    return targets or deepcopy(default_value)


def _normalize_polling_groups(
    groups: Any,
    fallback_groups: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    source_groups = groups if isinstance(groups, dict) else {}
    default_groups = deepcopy(fallback_groups or DEFAULT_POLLING_GROUPS)
    normalized: dict[str, dict[str, Any]] = {}

    for group_key in ("fast", "standard", "slow"):
        base_group = default_groups.get(group_key) or DEFAULT_POLLING_GROUPS[group_key]
        source_group = source_groups.get(group_key) if isinstance(source_groups.get(group_key), dict) else {}
        normalized[group_key] = {
            "intervalMs": _normalize_interval_ms(
                source_group.get("intervalMs"),
                int(base_group.get("intervalMs") or DEFAULT_POLLING_GROUPS[group_key]["intervalMs"]),
            ),
            "targets": _normalize_targets(
                source_group.get("targets"),
                list(base_group.get("targets") or DEFAULT_POLLING_GROUPS[group_key]["targets"]),
            ),
        }

    for group_key, group_value in source_groups.items():
        if group_key in normalized or not isinstance(group_value, dict):
            continue
        base_group = default_groups.get(group_key) if isinstance(default_groups.get(group_key), dict) else {"intervalMs": 1000, "targets": []}
        normalized[str(group_key)] = {
            "intervalMs": _normalize_interval_ms(group_value.get("intervalMs"), int(base_group.get("intervalMs") or 1000)),
            "targets": _normalize_targets(group_value.get("targets"), list(base_group.get("targets") or [])),
        }

    return normalized


def _default_profiles() -> list[dict[str, Any]]:
    return [
        {
            "key": "default-yldq",
            "label": "Default YLDQ Polling",
            "groups": deepcopy(DEFAULT_POLLING_GROUPS),
        }
    ]


def _normalize_profiles(profiles: Any) -> list[dict[str, Any]]:
    if not isinstance(profiles, list):
        return _default_profiles()

    normalized_profiles: list[dict[str, Any]] = []
    for index, profile in enumerate(profiles):
        if not isinstance(profile, dict):
            continue
        key = str(profile.get("key") or "").strip() or f"profile-{index + 1}"
        label = str(profile.get("label") or key).strip() or key
        normalized_profiles.append(
            {
                "key": key,
                "label": label,
                "groups": _normalize_polling_groups(profile.get("groups")),
            }
        )

    return normalized_profiles or _default_profiles()


def _uses_generated_default_commands(commands: Any) -> bool:
    if not isinstance(commands, list) or not commands:
        return True
    for command in commands:
        if not isinstance(command, dict):
            return False
        command_id = str(command.get("id") or "")
        if not command_id.startswith("default."):
            return False
    return True


def _migrate_legacy_catalog_item_ids(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    migrated: list[dict[str, Any]] = []
    for command in commands:
        next_command = deepcopy(command)
        item_ids = next_command.get("catalogItemIds")
        if isinstance(item_ids, list):
            next_command["catalogItemIds"] = [
                LEGACY_CATALOG_ITEM_IDS.get(str(item_id), str(item_id))
                for item_id in item_ids
                if str(item_id)
            ]
        migrated.append(next_command)
    return migrated


def _build_profile_groups_index(profiles: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    index: dict[str, dict[str, dict[str, Any]]] = {}
    for profile in profiles:
        key = str(profile.get("key") or "").strip()
        groups = profile.get("groups")
        if key and isinstance(groups, dict):
            index[key] = groups
    return index


def _normalize_device_payload(
    payload: dict[str, Any],
    existing_id: str | None = None,
    profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_profiles = _normalize_profiles(profiles)
    profile_groups_index = _build_profile_groups_index(normalized_profiles)

    device = deepcopy(DEFAULT_DEVICE_PROFILE)
    device.update(payload or {})
    device["id"] = existing_id or str(device.get("id") or f"dev-{uuid.uuid4().hex[:8]}")
    device["name"] = str(device.get("name") or DEFAULT_DEVICE_PROFILE["name"]).strip() or DEFAULT_DEVICE_PROFILE["name"]
    device["deviceType"] = str(device.get("deviceType") or DEFAULT_DEVICE_PROFILE["deviceType"]).strip() or DEFAULT_DEVICE_PROFILE["deviceType"]
    device["protocolType"] = "modbus"
    transport = str(device.get("transport") or "rtu").lower()
    device["transport"] = "tcp" if transport == "tcp" else "rtu"
    device["address"] = str(device.get("address") or DEFAULT_DEVICE_PROFILE["address"]).strip() or DEFAULT_DEVICE_PROFILE["address"]
    device["slaveId"] = max(1, min(247, int(device.get("slaveId") or 1)))
    device["baudrate"] = int(device.get("baudrate") or DEFAULT_DEVICE_PROFILE["baudrate"])
    device["databits"] = int(device.get("databits") or DEFAULT_DEVICE_PROFILE["databits"])
    device["stopbits"] = int(device.get("stopbits") or DEFAULT_DEVICE_PROFILE["stopbits"])
    parity = str(device.get("parity") or DEFAULT_DEVICE_PROFILE["parity"]).upper()
    device["parity"] = parity if parity in {"N", "E", "O"} else "N"
    device["timeoutMs"] = max(100, int(device.get("timeoutMs") or DEFAULT_DEVICE_PROFILE["timeoutMs"]))
    device["retryCount"] = max(0, int(device.get("retryCount") or DEFAULT_DEVICE_PROFILE["retryCount"]))
    device["pollingProfile"] = str(device.get("pollingProfile") or DEFAULT_DEVICE_PROFILE["pollingProfile"]).strip() or DEFAULT_DEVICE_PROFILE["pollingProfile"]
    polling_defaults = profile_groups_index.get(device["pollingProfile"]) or DEFAULT_POLLING_GROUPS
    raw_polling_settings = device.get("pollingSettings")
    if raw_polling_settings is None:
        raw_polling_settings = device.get("pollingGroups")
    device["pollingSettings"] = _normalize_polling_groups(raw_polling_settings, polling_defaults)
    if (
        device["pollingProfile"] == DEFAULT_DEVICE_PROFILE["pollingProfile"]
        and _uses_generated_default_commands(device.get("pollingCommands"))
    ):
        device["pollingCommands"] = build_default_polling_commands()
    else:
        device["pollingCommands"] = normalize_polling_commands(
            _migrate_legacy_catalog_item_ids(device.get("pollingCommands") or [])
        )
    device["enabled"] = bool(device.get("enabled", True))
    return device


def _default_payload() -> dict[str, Any]:
    return {
        "devices": [],
        "selectedDeviceId": None,
        "profiles": _default_profiles(),
    }


def load_live_devices(store_path: Path) -> dict[str, Any]:
    if not store_path.exists():
        return _default_payload()
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except Exception:
        return _default_payload()
    result = _default_payload()
    if isinstance(payload, dict):
        result["selectedDeviceId"] = payload.get("selectedDeviceId")
        if isinstance(payload.get("profiles"), list) and payload["profiles"]:
            result["profiles"] = _normalize_profiles(payload["profiles"])
        if isinstance(payload.get("devices"), list):
            result["devices"] = [
                _normalize_device_payload(item, profiles=result["profiles"])
                for item in payload["devices"]
                if isinstance(item, dict)
            ]
    if result["devices"] and not any(item["id"] == result["selectedDeviceId"] for item in result["devices"]):
        result["selectedDeviceId"] = result["devices"][0]["id"]
    return result


def save_live_devices(store_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    profiles = _normalize_profiles(payload.get("profiles"))
    normalized = {
        "devices": [
            _normalize_device_payload(item, profiles=profiles)
            for item in payload.get("devices", [])
            if isinstance(item, dict)
        ],
        "selectedDeviceId": payload.get("selectedDeviceId"),
        "profiles": profiles,
    }
    if normalized["devices"] and not any(item["id"] == normalized["selectedDeviceId"] for item in normalized["devices"]):
        normalized["selectedDeviceId"] = normalized["devices"][0]["id"]
    store_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def export_live_devices_json(store_path: Path) -> str:
    payload = load_live_devices(store_path)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_live_devices_payload(store_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("设备配置文件必须是 JSON 对象")
    return save_live_devices(store_path, payload)


def create_live_device(store_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_live_devices(store_path)
    device = _normalize_device_payload(payload, profiles=current["profiles"])
    current["devices"].append(device)
    current["selectedDeviceId"] = device["id"]
    save_live_devices(store_path, current)
    return device


def update_live_device(store_path: Path, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_live_devices(store_path)
    for index, device in enumerate(current["devices"]):
        if device["id"] == device_id:
            merged = deepcopy(device)
            merged.update(payload or {})
            normalized = _normalize_device_payload(merged, existing_id=device_id, profiles=current["profiles"])
            current["devices"][index] = normalized
            save_live_devices(store_path, current)
            return normalized
    raise KeyError(f"Device not found: {device_id}")


def delete_live_device(store_path: Path, device_id: str) -> dict[str, Any]:
    current = load_live_devices(store_path)
    filtered = [item for item in current["devices"] if item["id"] != device_id]
    if len(filtered) == len(current["devices"]):
        raise KeyError(f"Device not found: {device_id}")
    current["devices"] = filtered
    if current["selectedDeviceId"] == device_id:
        current["selectedDeviceId"] = filtered[0]["id"] if filtered else None
    save_live_devices(store_path, current)
    return current


def select_live_device(store_path: Path, device_id: str) -> dict[str, Any]:
    current = load_live_devices(store_path)
    if device_id and not any(item["id"] == device_id for item in current["devices"]):
        raise KeyError(f"Device not found: {device_id}")
    current["selectedDeviceId"] = device_id
    save_live_devices(store_path, current)
    return current
