from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from live_polling_commands import build_default_polling_commands, normalize_polling_commands


DEFAULT_POLLING_GROUPS: dict[str, dict[str, Any]] = {
    "fast": {"intervalMs": 1000, "targets": ["three_channel_environment", "flow", "pressure", "outputs", "valves"]},
    "standard": {"intervalMs": 5000, "targets": ["system", "alarms", "communication", "runtime"]},
    "slow": {"intervalMs": 30000, "targets": ["configuration"]},
}

DEFAULT_DEVICE_PROFILE: dict[str, Any] = {
    "name": "New Device",
    "deviceType": "YLDQ-6.0-Modbus-V9",
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

ALLOWED_BAUDRATES = {1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200}
_STORE_LOCKS_GUARD = threading.Lock()
_STORE_LOCKS: dict[str, threading.RLock] = {}


def _store_lock(store_path: Path) -> threading.RLock:
    key = str(Path(store_path).resolve())
    with _STORE_LOCKS_GUARD:
        return _STORE_LOCKS.setdefault(key, threading.RLock())


def _normalize_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "是", "开"}:
            return True
        if normalized in {"0", "false", "no", "off", "否", "关"}:
            return False
    raise ValueError(f"无效的布尔值: {value!r}")


def _bounded_int(value: Any, name: str, minimum: int, maximum: int, default: int) -> int:
    raw = default if value in (None, "") else value
    try:
        number = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} 必须在 {minimum}–{maximum} 之间")
    return number


def _atomic_write_json(store_path: Path, payload: dict[str, Any]) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = store_path.with_name(f".{store_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, store_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _pending_profile_path(store_path: Path) -> Path:
    return store_path.with_name(f".{store_path.name}.pending-profile.json")


def stage_pending_device_profile(store_path: Path, device_id: str, profile: dict[str, Any]) -> None:
    """在提交设备通信参数前写入恢复日志，防止设备提交成功而本地档案丢失。"""
    with _store_lock(store_path):
        _atomic_write_json(_pending_profile_path(store_path), {
            "deviceId": str(device_id), "profile": dict(profile),
        })


def clear_pending_device_profile(store_path: Path) -> None:
    with _store_lock(store_path):
        pending_path = _pending_profile_path(store_path)
        if pending_path.exists():
            pending_path.unlink()

def _normalize_interval_ms(value: Any, default_value: int) -> int:
    try:
        interval_ms = int(value)
    except (TypeError, ValueError):
        interval_ms = int(default_value)
    return max(100, min(300_000, interval_ms))


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
    device["transport"] = "rtu"
    device["address"] = str(device.get("address") or DEFAULT_DEVICE_PROFILE["address"]).strip() or DEFAULT_DEVICE_PROFILE["address"]
    device["slaveId"] = _bounded_int(device.get("slaveId"), "从站地址", 1, 247, 1)
    device["baudrate"] = _bounded_int(device.get("baudrate"), "波特率", 1200, 115200, 9600)
    if device["baudrate"] not in ALLOWED_BAUDRATES:
        raise ValueError(f"不支持的波特率: {device['baudrate']}")
    device["databits"] = _bounded_int(device.get("databits"), "数据位", 7, 8, 8)
    device["stopbits"] = _bounded_int(device.get("stopbits"), "停止位", 1, 2, 1)
    parity = str(device.get("parity") or DEFAULT_DEVICE_PROFILE["parity"]).upper()
    if parity not in {"N", "E", "O"}:
        raise ValueError(f"不支持的校验位: {parity}")
    device["parity"] = parity
    device["timeoutMs"] = _bounded_int(device.get("timeoutMs"), "通信超时", 100, 30_000, 1200)
    device["retryCount"] = _bounded_int(device.get("retryCount"), "重试次数", 0, 5, 2)
    device["pollingProfile"] = str(device.get("pollingProfile") or DEFAULT_DEVICE_PROFILE["pollingProfile"]).strip() or DEFAULT_DEVICE_PROFILE["pollingProfile"]
    polling_defaults = profile_groups_index.get(device["pollingProfile"]) or DEFAULT_POLLING_GROUPS
    raw_polling_settings = device.get("pollingSettings")
    if raw_polling_settings is None:
        raw_polling_settings = device.get("pollingGroups")
    device["pollingSettings"] = _normalize_polling_groups(raw_polling_settings, polling_defaults)
    device["pollingCommands"] = normalize_polling_commands(device.get("pollingCommands"))
    device["enabled"] = _normalize_bool(device.get("enabled"), True)
    return device


def _default_payload() -> dict[str, Any]:
    return {
        "devices": [],
        "selectedDeviceId": None,
        "profiles": _default_profiles(),
    }


def load_live_devices(store_path: Path) -> dict[str, Any]:
    with _store_lock(store_path):
        if not store_path.exists():
            return _default_payload()
        try:
            payload = json.loads(store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"设备配置文件损坏，已拒绝清空现有设备: {store_path}") from exc
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
    ids = [str(item["id"]) for item in result["devices"]]
    if len(ids) != len(set(ids)):
        raise ValueError("设备配置文件中存在重复设备 ID")
    endpoints = [(str(item["address"]).upper(), int(item["slaveId"])) for item in result["devices"]]
    if len(endpoints) != len(set(endpoints)):
        raise ValueError("设备配置文件中存在重复串口从站")
    selected = next((item for item in result["devices"] if item["id"] == result["selectedDeviceId"]), None)
    if selected is None or not selected.get("enabled", True):
        result["selectedDeviceId"] = next((item["id"] for item in result["devices"] if item.get("enabled", True)), None)
    pending_path = _pending_profile_path(store_path)
    if pending_path.exists():
        try:
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            pending_id = str(pending.get("deviceId") or "") if isinstance(pending, dict) else ""
            profile = pending.get("profile") if isinstance(pending, dict) else None
            if pending_id and isinstance(profile, dict):
                for index, device in enumerate(result["devices"]):
                    if device["id"] == pending_id:
                        merged = deepcopy(device)
                        merged.update(profile)
                        result["devices"][index] = _normalize_device_payload(
                            merged, existing_id=pending_id, profiles=result["profiles"]
                        )
                        break
                _atomic_write_json(store_path, result)
                pending_path.unlink()
        except (OSError, ValueError, json.JSONDecodeError):
            # 恢复日志保留到下次启动；本次仍返回已能解析的主配置。
            pass
    return result


def save_live_devices(store_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    with _store_lock(store_path):
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
        ids = [str(item["id"]) for item in normalized["devices"]]
        if len(ids) != len(set(ids)):
            raise ValueError("设备 ID 不能重复")
        endpoints = [(str(item["address"]).upper(), int(item["slaveId"])) for item in normalized["devices"]]
        if len(endpoints) != len(set(endpoints)):
            raise ValueError("同一串口上的从站地址不能重复")
        selected = next((item for item in normalized["devices"] if item["id"] == normalized["selectedDeviceId"]), None)
        if selected is None or not selected.get("enabled", True):
            normalized["selectedDeviceId"] = next((item["id"] for item in normalized["devices"] if item.get("enabled", True)), None)
        _atomic_write_json(store_path, normalized)
        return normalized


def export_live_devices_json(store_path: Path) -> str:
    payload = load_live_devices(store_path)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_live_devices_payload(store_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("设备配置文件必须是 JSON 对象")
    return save_live_devices(store_path, payload)


def create_live_device(store_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    with _store_lock(store_path):
        current = load_live_devices(store_path)
        device = _normalize_device_payload(payload, profiles=current["profiles"])
        current["devices"].append(device)
        if device.get("enabled", True):
            current["selectedDeviceId"] = device["id"]
        save_live_devices(store_path, current)
        return device


def update_live_device(store_path: Path, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _store_lock(store_path):
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
    with _store_lock(store_path):
        current = load_live_devices(store_path)
        filtered = [item for item in current["devices"] if item["id"] != device_id]
        if len(filtered) == len(current["devices"]):
            raise KeyError(f"Device not found: {device_id}")
        current["devices"] = filtered
        if current["selectedDeviceId"] == device_id:
            current["selectedDeviceId"] = next((item["id"] for item in filtered if item.get("enabled", True)), None)
        save_live_devices(store_path, current)
        return current


def select_live_device(store_path: Path, device_id: str) -> dict[str, Any]:
    with _store_lock(store_path):
        current = load_live_devices(store_path)
        selected = next((item for item in current["devices"] if item["id"] == device_id), None)
        if device_id and selected is None:
            raise KeyError(f"Device not found: {device_id}")
        if selected is not None and not selected.get("enabled", True):
            raise ValueError("禁用设备不能被选为当前监控设备")
        current["selectedDeviceId"] = device_id
        save_live_devices(store_path, current)
        return current
