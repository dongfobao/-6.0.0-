"""将V10四区点值投影为远程监控界面视图模型。"""

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


def _synthetic(point_id: str, name: str, value: Any, updated_at: Any = None,
               enum_values: dict[int, str] | None = None) -> dict[str, Any]:
    return _project_item({"id": point_id, "name": name, "currentValue": value,
                          "updatedAt": updated_at, "dataType": "enum16",
                          "enumValues": enum_values or {}})


def build_monitoring_snapshot(snapshot: dict[str, Any], device: dict[str, Any] | None = None) -> dict[str, Any]:
    items = [item for item in snapshot.get("metrics", []) if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in items if item.get("id")}
    status_items = [item for item in snapshot.get("statuses", []) if isinstance(item, dict)]
    by_id.update({str(item.get("id")): item for item in status_items if item.get("id")})
    control_items = [item for item in snapshot.get("controls", []) if isinstance(item, dict)]
    controls_by_id = {str(item.get("id")): item for item in control_items if item.get("id")}
    channels = []
    sensor_roles = (("left", "左温湿度"), ("right", "右温湿度"), ("upper", "上温湿度"))
    for channel, (sensor_role, sensor_name) in enumerate(sensor_roles, start=1):
        prefix = f"input_register.sensor_{channel}"
        channels.append({
            "channel": channel,
            "role": sensor_role,
            "name": sensor_name,
            "temperature": _take(by_id, f"{prefix}.temperature"),
            "humidity": _take(by_id, f"{prefix}.humidity"),
            "status": _take(by_id, f"{prefix}.status"),
            "readOk": _take(by_id, f"{prefix}.read_ok"),
        })

    valves = []
    valve_roles = (("upper", "上阀"), ("left", "左阀"), ("right", "右阀"))
    for channel, (valve_role, valve_name) in enumerate(valve_roles, start=1):
        prefix = f"input_register.valve_{channel}"
        di_prefix = f"discrete_input.valve_{channel}"
        home_missing = bool((_take(by_id, f"{di_prefix}.home_not_reached").get("value")))
        work_missing = bool((_take(by_id, f"{di_prefix}.work_not_reached").get("value")))
        moving = bool((_take(by_id, f"{di_prefix}.moving").get("value")))
        fault = bool((_take(by_id, f"{di_prefix}.fault").get("value")))
        unknown = bool((_take(by_id, f"{di_prefix}.unknown").get("value")))
        disabled = bool((_take(by_id, f"{di_prefix}.disabled").get("value")))
        display_state = 0 if disabled else 4 if fault else 3 if moving else 1 if not home_missing else 2 if not work_missing else 5
        actuator_state = 3 if disabled else 2 if fault else 1 if moving else 0
        position = 0 if not home_missing else 1 if not work_missing else 2
        updated_at = _take(by_id, f"{di_prefix}.home_not_reached").get("updatedAt")
        valves.append({
            "channel": channel,
            "role": valve_role,
            "name": valve_name,
            "displayState": _synthetic(f"{prefix}.display_state", f"{valve_name}状态", display_state, updated_at, {0: "禁用", 1: "原位", 2: "工作位", 3: "运动中", 4: "故障", 5: "未知"}),
            "actuatorState": _synthetic(f"{prefix}.actuator_state", f"{valve_name}执行器状态", actuator_state, updated_at, {0: "空闲", 1: "运动中", 2: "故障", 3: "禁用"}),
            "position": _synthetic(f"{prefix}.position", f"{valve_name}位置", position, updated_at, {0: "原位", 1: "工作位", 2: "未知"}),
            "faultReason": _take(by_id, f"{prefix}.fault_reason"),
            "currentAdc": _take(by_id, f"{prefix}.current_adc"),
            "controlSource": _take(by_id, f"{prefix}.control_source"),
            "totalActionCount": _take(by_id, f"{prefix}.total_action_count"),
        })

    heat_sessions = []
    for side, side_role in enumerate(("left", "right"), start=1):
        prefix = f"input_register.heat_session_{side}"
        di_prefix = f"discrete_input.heat_session_{side}"
        active = bool(_take(by_id, f"{di_prefix}.active").get("value"))
        peak_valid = not bool(_take(by_id, f"{di_prefix}.peak_invalid").get("value"))
        stop_valid = not bool(_take(by_id, f"{di_prefix}.stop_target_invalid").get("value"))
        flags_value = (1 if active else 0) | (2 if peak_valid else 0) | (4 if stop_valid else 0)
        flags_item = _synthetic(f"{prefix}.session_flags", "会话标志", flags_value)
        heat_sessions.append({
            "channel": side,
            "role": side_role,
            "runSeconds": _take(by_id, f"{prefix}.session_run_seconds"),
            "startHumidity": _take(by_id, f"{prefix}.start_humidity"),
            "predictedPeakHumidity": _take(by_id, f"{prefix}.predicted_peak_humidity"),
            "stopTargetHumidity": _take(by_id, f"{prefix}.stop_target_humidity"),
            "flags": flags_item,
            "sessionActive": active,
            "peakValid": peak_valid,
            "stopTargetValid": stop_valid,
            "fallingStopProgress": _synthetic(f"{prefix}.falling_stop_progress", "停热确认进度", f"{_take(by_id, f'{prefix}.falling_stop_count').get('value') or 0}/{_take(by_id, f'{prefix}.falling_stop_target').get('value') or 0}"),
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
        {"key": "htc1", "name": "加热通道1", "state": _take(by_id, "input_register.output.htc1_state"), "mode": _take(controls_by_id, "holding.runtime.htc1_mode"), "count": _take(by_id, "input_register.output.htc1_open_count")},
        {"key": "htc2", "name": "加热通道2", "state": _take(by_id, "input_register.output.htc2_state"), "mode": _take(controls_by_id, "holding.runtime.htc2_mode"), "count": _take(by_id, "input_register.output.htc2_open_count")},
        {"key": "antifreeze", "name": "防冻加热", "state": _take(by_id, "input_register.output.antifreeze_state"), "mode": _take(controls_by_id, "holding.runtime.antifreeze_mode"), "count": _take(by_id, "input_register.output.antifreeze_open_count")},
        {"key": "alarm", "name": "告警输出", "state": _take(by_id, "input_register.output.alarm_state"), "mode": None, "count": None},
    ]

    alarm_ids = [point_id for point_id in by_id if point_id.startswith("discrete_input.alarm.")]
    alarm_items = [_take(by_id, point_id) for point_id in sorted(alarm_ids)]
    alarm_active = bool(_take(by_id, "discrete_input.alarm.any").get("value"))
    sensor_module_alarms = {
        "pressure": bool(_take(by_id, "discrete_input.alarm.pressure_fault").get("value")) or bool(_take(by_id, "discrete_input.alarm.pressure_limit").get("value")),
        "flow": bool(_take(by_id, "discrete_input.alarm.flow_fault").get("value")) or bool(_take(by_id, "discrete_input.alarm.breath_no_change").get("value")),
        "t1": bool(_take(by_id, "discrete_input.alarm.sensor_1_fault").get("value")),
        "t2": bool(_take(by_id, "discrete_input.alarm.sensor_2_fault").get("value")),
        "t3": any(bool(_take(by_id, point_id).get("value")) for point_id in ("discrete_input.alarm.sensor_3_fault", "discrete_input.alarm.humidity_limit", "discrete_input.alarm.temperature_limit")),
    }
    equipment_module_alarms = {
        "heater": any(bool(_take(by_id, point_id).get("value")) for point_id in ("discrete_input.alarm.htc1_fault", "discrete_input.alarm.htc2_fault", "discrete_input.alarm.power_overheat")),
        "antifreeze": bool(_take(by_id, "discrete_input.alarm.antifreeze_fault").get("value")),
    }
    runtime_valves = []
    for channel, (valve_role, valve_name) in enumerate(valve_roles, start=1):
        prefix = f"holding.runtime.valve_{channel}"
        runtime_valves.append({
            "channel": channel,
            "role": valve_role,
            "name": valve_name,
            "command": _take(controls_by_id, prefix),
            "faultReason": _take(by_id, f"input_register.valve_{channel}.fault_reason"),
            "effectiveSource": _take(by_id, f"input_register.valve_{channel}.control_source"),
            "remoteSeconds": _take(by_id, f"input_register.valve_{channel}.remote_seconds"),
        })
    valve_guard_reason = _take(
        by_id, "input_register.runtime.valve_guard_reason"
    )
    valve_guard = {
        "active": int(valve_guard_reason.get("value") or 0) in {1, 2, 3},
        "reason": valve_guard_reason,
        "remainingSeconds": _take(
            by_id, "input_register.runtime.valve_guard_remaining_seconds"
        ),
        "actionCount": _take(
            by_id, "input_register.runtime.valve_action_count"
        ),
        "actionLimit": _take(
            by_id, "input_register.runtime.valve_action_limit"
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
            "flags": _synthetic("input_register.system.flags", "系统状态", 1 if alarm_active else 0),
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
        "remoteHeat": _take(controls_by_id, "holding.runtime.remote_heat"),
        "valves": valves,
        "runtimeValves": runtime_valves,
        "valveGuard": valve_guard,
        "heatSessions": heat_sessions,
        "channelStats": channel_stats,
        "schedulePlan": schedule_plan,
        "alarms": {
            "active": alarm_active,
            "groups": alarm_items,
            "sensorModules": sensor_module_alarms,
            "equipmentModules": equipment_module_alarms,
        },
        "communication": {
            "online": _take(by_id, "input_register.communication.online"),
            "failureCount": _take(by_id, "input_register.communication.failure_count"),
            "lastSuccess": _take(by_id, "input_register.communication.last_success"),
            "lastFailure": _take(by_id, "input_register.communication.last_failure"),
            "health": session.get("communication_health", "idle"),
            "text": session.get("communication_text", "待采集"),
        },
    }
