"""将 V9 点值投影为远程监控界面需要的稳定视图模型。"""

from __future__ import annotations

import math
from typing import Any


def _finite_or_none(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _display_value(item: dict[str, Any]) -> Any:
    value = item.get("currentValue")
    enum_values = item.get("enumValues") or {}
    if value is not None and isinstance(enum_values, dict):
        return enum_values.get(value, enum_values.get(str(value), value))
    return value


def _project_item(item: dict[str, Any]) -> dict[str, Any]:
    current = item.get("currentValue")
    if isinstance(current, float) and not math.isfinite(current):
        item = dict(item, currentValue=None)
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
            "totalActionCount": _take(by_id, f"{prefix}.total_action_count"),
        })

    heat_sessions = []
    for side in range(1, 3):
        prefix = f"input_register.heat_session_{side}"
        flags_item = _take(by_id, f"{prefix}.session_flags")
        flags_value = int(flags_item.get("value") or 0)
        heat_sessions.append({
            "channel": side,
            "runSeconds": _take(by_id, f"{prefix}.session_run_seconds"),
            "startHumidity": _take(by_id, f"{prefix}.start_humidity"),
            "predictedPeakHumidity": _take(by_id, f"{prefix}.predicted_peak_humidity"),
            "stopTargetHumidity": _take(by_id, f"{prefix}.stop_target_humidity"),
            "flags": flags_item,
            "sessionActive": bool(flags_value & 0x1),
            "peakValid": bool(flags_value & 0x2),
            "stopTargetValid": bool(flags_value & 0x4),
            "fallingStopProgress": _take(by_id, f"{prefix}.falling_stop_progress"),
        })

    channel_stats = [
        {"key": "htc1", "name": "加热通道1",
         "cumulativeSeconds": _take(by_id, "input_register.runtime.htc1_cumulative_seconds"),
         "runSeconds": heat_sessions[0]["runSeconds"]},
        {"key": "htc2", "name": "加热通道2",
         "cumulativeSeconds": _take(by_id, "input_register.runtime.htc2_cumulative_seconds"),
         "runSeconds": heat_sessions[1]["runSeconds"]},
        {"key": "antifreeze", "name": "防冻加热",
         "cumulativeSeconds": _take(by_id, "input_register.runtime.antifreeze_cumulative_seconds"),
         "runSeconds": _take(by_id, "input_register.runtime.antifreeze_run_seconds")},
    ]

    outputs = [
        {"key": "htc1", "name": "加热通道1", "state": _take(by_id, "input_register.output.htc1_state"), "mode": _take(by_id, "input_register.output.htc1_mode"), "count": _take(by_id, "input_register.output.htc1_open_count")},
        {"key": "htc2", "name": "加热通道2", "state": _take(by_id, "input_register.output.htc2_state"), "mode": _take(by_id, "input_register.output.htc2_mode"), "count": _take(by_id, "input_register.output.htc2_open_count")},
        {"key": "antifreeze", "name": "防冻加热", "state": _take(by_id, "input_register.output.antifreeze_state"), "mode": _take(by_id, "input_register.output.antifreeze_mode"), "count": _take(by_id, "input_register.output.antifreeze_open_count")},
        {"key": "alarm", "name": "告警输出", "state": _take(by_id, "input_register.output.alarm_state"), "mode": None, "count": None},
    ]

    alarm_items = [_take(by_id, point_id) for point_id in (
        "input_register.alarm.error_group_0",
        "input_register.alarm.error_group_1",
        "input_register.alarm.error_group_2",
    )]
    alarm_active = any(int(item.get("value") or 0) != 0 for item in alarm_items)
    control_items = [item for item in snapshot.get("controls", []) if isinstance(item, dict)]
    controls_by_id = {str(item.get("id")): item for item in control_items if item.get("id")}
    runtime_valves = []
    for channel, valve_name in enumerate(valve_names, start=1):
        prefix = f"holding.runtime.valve_{channel}"
        runtime_valves.append({
            "channel": channel,
            "name": valve_name,
            "command": _take(controls_by_id, prefix),
            "faultReason": _take(controls_by_id, f"{prefix}_diagnostic_fault"),
            "effectiveSource": _take(controls_by_id, f"{prefix}_diagnostic_source"),
            "remoteSeconds": _take(controls_by_id, f"{prefix}_remote_seconds"),
        })
    valve_guard_reason = _take(
        controls_by_id, "holding.runtime.valve_guard_reason"
    )
    valve_guard = {
        "active": int(valve_guard_reason.get("value") or 0) in {1, 2, 3},
        "reason": valve_guard_reason,
        "remainingSeconds": _take(
            controls_by_id, "holding.runtime.valve_guard_remaining_seconds"
        ),
        "actionCount": _take(
            controls_by_id, "holding.runtime.valve_action_count"
        ),
        "actionLimit": _take(
            controls_by_id, "holding.runtime.valve_action_limit"
        ),
    }
    schedule_prefix = "holding.schedule"
    schedule_plan = {
        "taskCount": _take(controls_by_id, f"{schedule_prefix}.task_count"),
        "selectedTask": _take(controls_by_id, f"{schedule_prefix}.selected_task"),
        "enabled": _take(controls_by_id, f"{schedule_prefix}.enabled"),
        "startMonth": _take(controls_by_id, f"{schedule_prefix}.start_month"),
        "startDay": _take(controls_by_id, f"{schedule_prefix}.start_day"),
        "startHour": _take(controls_by_id, f"{schedule_prefix}.start_hour"),
        "startMinute": _take(controls_by_id, f"{schedule_prefix}.start_minute"),
        "durationDays": _take(controls_by_id, f"{schedule_prefix}.duration_days"),
        "humidityOverrideEnabled": _take(controls_by_id, f"{schedule_prefix}.humidity_override_enabled"),
    }
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
        "runtimeValves": runtime_valves,
        "valveGuard": valve_guard,
        "heatSessions": heat_sessions,
        "channelStats": channel_stats,
        "schedulePlan": schedule_plan,
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
