"""将 V7 点值投影为远程监控界面需要的稳定视图模型。"""

from __future__ import annotations

from typing import Any


def _display_value(item: dict[str, Any]) -> Any:
    value = item.get("currentValue")
    enum_values = item.get("enumValues") or {}
    if value is not None and isinstance(enum_values, dict):
        return enum_values.get(value, enum_values.get(str(value), value))
    return value


def _project_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "value": item.get("currentValue"),
        "displayValue": _display_value(item),
        "unit": item.get("unit") or "",
        "updatedAt": item.get("updatedAt"),
        "dataType": item.get("dataType"),
        "enumValues": item.get("enumValues") or {},
        "bitDefinitions": item.get("bitDefinitions") or {},
    }


def _take(by_id: dict[str, dict[str, Any]], point_id: str) -> dict[str, Any]:
    return _project_item(by_id.get(point_id) or {"id": point_id, "name": point_id})


def build_monitoring_snapshot(snapshot: dict[str, Any], device: dict[str, Any] | None = None) -> dict[str, Any]:
    items = [item for item in snapshot.get("metrics", []) if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in items if item.get("id")}
    channels = []
    for channel in range(1, 4):
        prefix = f"input_register.sensor_{channel}"
        channels.append({
            "channel": channel,
            "temperature": _take(by_id, f"{prefix}.temperature"),
            "humidity": _take(by_id, f"{prefix}.humidity"),
            "status": _take(by_id, f"{prefix}.status"),
            "readOk": _take(by_id, f"{prefix}.read_ok"),
        })

    valves = []
    valve_names = ("上阀", "左阀", "右阀")
    for channel, valve_name in enumerate(valve_names, start=1):
        prefix = f"input_register.valve_{channel}"
        valves.append({
            "channel": channel,
            "name": valve_name,
            "displayState": _take(by_id, f"{prefix}.display_state"),
            "actuatorState": _take(by_id, f"{prefix}.actuator_state"),
            "position": _take(by_id, f"{prefix}.position"),
            "faultReason": _take(by_id, f"{prefix}.fault_reason"),
            "currentAdc": _take(by_id, f"{prefix}.current_adc"),
            "controlSource": _take(by_id, f"{prefix}.control_source"),
        })

    outputs = [
        {"key": "htc1", "name": "加热通道1", "state": _take(by_id, "input_register.output.htc1_state"), "mode": _take(by_id, "input_register.output.htc1_mode"), "count": _take(by_id, "input_register.output.htc1_open_count")},
        {"key": "htc2", "name": "加热通道2", "state": _take(by_id, "input_register.output.htc2_state"), "mode": _take(by_id, "input_register.output.htc2_mode"), "count": _take(by_id, "input_register.output.htc2_open_count")},
        {"key": "antifreeze", "name": "防冻加热", "state": _take(by_id, "input_register.output.antifreeze_state"), "mode": _take(by_id, "input_register.output.antifreeze_mode"), "count": _take(by_id, "input_register.output.antifreeze_open_count")},
        {"key": "alarm", "name": "告警输出", "state": _take(by_id, "input_register.output.alarm_state"), "mode": None, "count": None},
    ]

    alarm_items = [_take(by_id, point_id) for point_id in (
        "input_register.alarm.active_low", "input_register.alarm.active_high", "input_register.alarm.latched"
    )]
    alarm_active = any(int(item.get("value") or 0) != 0 for item in alarm_items)
    session = snapshot.get("session") if isinstance(snapshot.get("session"), dict) else {}
    return {
        "deviceId": snapshot.get("deviceId"),
        "device": device,
        "snapshotAt": snapshot.get("snapshotAt"),
        "session": session,
        "system": {
            "protocolVersion": _take(by_id, "input_register.system.protocol_version"),
            "flags": _take(by_id, "input_register.system.flags"),
            "rtcSeconds": _take(by_id, "input_register.system.rtc_seconds"),
            "configGeneration": _take(by_id, "input_register.system.config_generation"),
            "lastConfigError": _take(by_id, "input_register.system.last_config_error"),
        },
        "environmentChannels": channels,
        "process": {
            "pressure": _take(by_id, "input_register.pressure"),
            "pressureStatus": _take(by_id, "input_register.pressure_status"),
            "pressureType": _take(by_id, "input_register.pressure_type"),
            "flow": _take(by_id, "input_register.flow"),
            "flowStatus": _take(by_id, "input_register.flow_status"),
            "breathState": _take(by_id, "input_register.breath_state"),
        },
        "outputs": outputs,
        "remoteHeat": _take(by_id, "input_register.output.remote_heat"),
        "valves": valves,
        "alarms": {"active": alarm_active, "groups": alarm_items},
        "communication": {
            "online": _take(by_id, "input_register.communication.online"),
            "failureCount": _take(by_id, "input_register.communication.failure_count"),
            "lastSuccess": _take(by_id, "input_register.communication.last_success"),
            "lastFailure": _take(by_id, "input_register.communication.last_failure"),
            "health": session.get("communication_health", "idle"),
            "text": session.get("communication_text", "待采集"),
        },
    }
