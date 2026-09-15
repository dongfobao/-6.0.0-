"""YLDQ Modbus V10唯一点表。

地址、类型和权限来自通信文档生成器同步的JSON，本文件只补充稳定点ID、枚举和输入约束。
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

PROTOCOL_VERSION_WORD = 0x0A00
_MAP = json.loads(Path(__file__).with_name("modbus_v10_point_map.json").read_text(encoding="utf-8"))
_FIELDS = {(str(f["area"]), int(f["address"])): dict(f) for f in _MAP["fields"]}
_TYPE = {"BOOL": "bool", "U16": "uint16", "U32": "uint32", "U64": "uint64", "F32": "float32"}
_AREA = {"DI": "discrete_input", "IR": "input_register", "COIL": "coil", "HR": "holding_register"}
_READ_FC = {"DI": 2, "IR": 4, "COIL": 1, "HR": 3}


def _make(field: dict[str, Any], point_id: str, group: str, **extra: Any) -> dict[str, Any]:
    code = str(field["area"])
    count = int(field["count"])
    writable = code in {"COIL", "HR"} and str(field.get("access")) != "R"
    item: dict[str, Any] = {
        "id": point_id, "name": str(field["name"]), "group": group,
        "functionCode": [_READ_FC[code]], "area": _AREA[code],
        "address": int(field["address"]), "addressEnd": int(field["address"]) + count - 1,
        "wordLength": count, "dataType": _TYPE[str(field["type"])],
        "unit": "" if field.get("unit") in {None, "—"} else str(field["unit"]),
        "readable": True, "writable": writable, "derived": False,
        "pollGroup": "fast" if code in {"DI", "IR"} else "slow",
        "uiVisible": True, "analysisExport": code == "IR",
        "sourceOfTruth": "station-modbus-v10", "notes": str(field.get("description") or ""),
    }
    if writable:
        item["functionCode"] += [5, 15] if code == "COIL" else [6, 16]
    item.update(extra)
    return item


REGISTER_CATALOG: list[dict[str, Any]] = []


def _add(area: str, address: int, point_id: str, group: str, **extra: Any) -> None:
    REGISTER_CATALOG.append(_make(_FIELDS[(area, address)], point_id, group, **extra))


# 离散输入。read_ok沿用上位机正逻辑，线上0有效/1无效由解码反相。
_DI_IDS = {
    0: "input_register.output.total_heat_state", 1: "input_register.output.htc1_state",
    2: "input_register.output.htc2_state", 3: "input_register.output.antifreeze_state",
    4: "input_register.output.alarm_state", 5: "discrete_input.breath.exhale",
    6: "discrete_input.breath.inhale", 7: "discrete_input.breath.no_breath",
    8: "discrete_input.alarm.any", 9: "discrete_input.alarm.sensor_3_fault",
    10: "discrete_input.alarm.pressure_fault", 11: "discrete_input.alarm.flow_fault",
    12: "discrete_input.alarm.actuator_fault", 13: "discrete_input.alarm.pressure_limit",
    14: "discrete_input.alarm.humidity_limit", 15: "discrete_input.alarm.temperature_limit",
    16: "discrete_input.alarm.breath_no_change", 17: "input_register.sensor_3.read_ok",
    18: "discrete_input.pressure.read_ok", 19: "discrete_input.flow.read_ok",
    32: "input_register.sensor_1.read_ok", 33: "input_register.sensor_2.read_ok",
    34: "discrete_input.alarm.sensor_1_fault", 35: "discrete_input.alarm.sensor_2_fault",
    36: "discrete_input.alarm.htc1_fault", 37: "discrete_input.alarm.htc2_fault",
    38: "discrete_input.alarm.antifreeze_fault", 39: "discrete_input.alarm.valve_1_fault",
    40: "discrete_input.alarm.valve_2_fault", 41: "discrete_input.alarm.valve_3_fault",
    42: "discrete_input.alarm.power_overheat", 43: "discrete_input.pressure.heat_protection",
    48: "discrete_input.valve_guard.active", 49: "discrete_input.config.save_busy",
    50: "discrete_input.config.save_failed", 96: "discrete_input.heat_session_1.active",
    97: "discrete_input.heat_session_1.peak_invalid", 98: "discrete_input.heat_session_1.stop_target_invalid",
    100: "discrete_input.heat_session_2.active", 101: "discrete_input.heat_session_2.peak_invalid",
    102: "discrete_input.heat_session_2.stop_target_invalid",
}
for _address, _id in _DI_IDS.items():
    _add("DI", _address, _id, "status", invertBoolean=_address in {17, 18, 19, 32, 33})
for _channel, _base in enumerate((64, 72, 80), start=1):
    for _offset, _suffix in enumerate(("home_not_reached", "work_not_reached", "moving", "fault", "unknown", "disabled")):
        _add("DI", _base + _offset, f"discrete_input.valve_{_channel}.{_suffix}", "valve")
for _channel, _base in enumerate((104, 108, 112), start=1):
    for _offset, _suffix in enumerate(("calibrating", "calibration_succeeded", "calibration_failed")):
        _add("DI", _base + _offset, f"discrete_input.valve_{_channel}.{_suffix}", "valve")

# 输入寄存器。
_IR_IDS = {
    0: "input_register.sensor_3.temperature", 2: "input_register.sensor_3.humidity",
    4: "input_register.pressure", 6: "input_register.flow",
    16: "input_register.sensor_1.temperature", 18: "input_register.sensor_1.humidity",
    20: "input_register.sensor_2.temperature", 22: "input_register.sensor_2.humidity",
    32: "input_register.heat_session_1.session_run_seconds", 34: "input_register.heat_session_2.session_run_seconds",
    36: "input_register.runtime.antifreeze_run_seconds", 38: "input_register.runtime.htc1_cumulative_seconds",
    40: "input_register.runtime.htc2_cumulative_seconds", 42: "input_register.runtime.antifreeze_cumulative_seconds",
    44: "input_register.output.htc1_open_count", 48: "input_register.output.htc2_open_count",
    52: "input_register.output.antifreeze_open_count", 56: "input_register.valve_1.total_action_count",
    58: "input_register.valve_2.total_action_count", 60: "input_register.valve_3.total_action_count",
    64: "input_register.heat_session_1.start_humidity", 66: "input_register.heat_session_1.predicted_peak_humidity",
    68: "input_register.heat_session_1.stop_target_humidity", 70: "input_register.heat_session_1.falling_stop_count",
    71: "input_register.heat_session_1.falling_stop_target", 72: "input_register.heat_session_2.start_humidity",
    74: "input_register.heat_session_2.predicted_peak_humidity", 76: "input_register.heat_session_2.stop_target_humidity",
    78: "input_register.heat_session_2.falling_stop_count", 79: "input_register.heat_session_2.falling_stop_target",
    80: "input_register.valve_1.current_adc", 81: "input_register.valve_2.current_adc", 82: "input_register.valve_3.current_adc",
    84: "input_register.valve_1.remote_seconds", 85: "input_register.valve_2.remote_seconds", 86: "input_register.valve_3.remote_seconds",
    88: "input_register.runtime.valve_guard_remaining_seconds", 89: "input_register.runtime.valve_action_count",
    90: "input_register.runtime.valve_action_limit", 92: "input_register.valve_1.fault_reason",
    93: "input_register.valve_2.fault_reason", 94: "input_register.valve_3.fault_reason",
    95: "input_register.valve_1.control_source", 96: "input_register.valve_2.control_source", 97: "input_register.valve_3.control_source",
    100: "input_register.system.protocol_version", 104: "input_register.sensor_1.status",
    105: "input_register.sensor_2.status", 106: "input_register.sensor_3.status", 107: "input_register.pressure_status",
    108: "input_register.pressure_type", 109: "input_register.flow_status", 110: "input_register.breath_state",
    112: "input_register.system.rtc_seconds", 114: "input_register.system.config_generation",
    115: "input_register.system.last_config_error", 116: "input_register.runtime.valve_guard_reason",
    117: "input_register.valve_1.last_attempt_count", 118: "input_register.valve_2.last_attempt_count",
    119: "input_register.valve_3.last_attempt_count", 120: "input_register.valve_1.calibration_remaining_seconds",
    121: "input_register.valve_2.calibration_remaining_seconds", 122: "input_register.valve_3.calibration_remaining_seconds",
    124: "input_register.communication.online", 126: "input_register.communication.failure_count",
    128: "input_register.communication.last_success", 130: "input_register.communication.last_failure",
    132: "input_register.system.storage_mode", 133: "input_register.system.config_version_major",
    134: "input_register.system.config_version_minor", 135: "input_register.system.config_version_patch",
    136: "input_register.system.persist_diagnostic",
}
_SENSOR_STATUS = {0: "正常", 1: "超时", 2: "停用", 3: "CRC错误", 4: "恢复中", 5: "数据异常", 65535: "不可用"}
_FAULT_REASON = {0: "无故障", 1: "阀门编号无效", 2: "阀门忙", 3: "动作队列已满", 4: "回原位超时", 5: "目标位置校验失败", 6: "驱动器故障", 7: "过流", 8: "开路", 9: "限位开关卡滞", 65535: "不可用"}
_SOURCE = {0: "自动", 1: "远程", 2: "安全保护", 3: "周期维护", 65535: "不可用"}
for _address, _id in _IR_IDS.items():
    _enum: dict[int, str] = {}
    if _address in {92, 93, 94}: _enum = _FAULT_REASON
    elif _address in {95, 96, 97}: _enum = _SOURCE
    elif _address in {104, 105, 106, 107, 109}: _enum = _SENSOR_STATUS
    elif _address == 108: _enum = {0: "正常", 1: "正压", 2: "负压", 65535: "不可用"}
    elif _address == 110: _enum = {0: "呼气", 1: "吸气", 2: "无呼吸", 65535: "无效"}
    elif _address == 115: _enum = {0: "无", 1: "加载失败", 2: "校验失败", 3: "保存失败", 4: "运行命令失败", 5: "保存中"}
    elif _address == 116: _enum = {0: "无保护", 1: "初始充电", 2: "频率限制", 3: "故障重试", 65535: "不可用"}
    elif _address == 124: _enum = {0: "离线", 1: "在线"}
    elif _address == 132: _enum = {0: "未配置", 1: "SD主配置", 2: "Flash降级", 3: "致命错误"}
    _add("IR", _address, _id, "system" if _address >= 100 else "runtime", enumValues=_enum)

# 线圈：成对控制合并为一个逻辑点，完整使用FC0F。
for _address, _id in {0: "holding.runtime.remote_heat", 1: "holding.runtime.reset", 4: "holding.runtime.valve_1_fault_reset", 5: "holding.runtime.valve_2_fault_reset", 6: "holding.runtime.valve_3_fault_reset", 8: "holding.runtime.valve_1_calibrate", 9: "holding.runtime.valve_2_calibrate", 10: "holding.runtime.valve_3_calibrate"}.items():
    _add("COIL", _address, _id, "runtime_control", pulse=_address != 0, allowedValues=[0, 1])
for _name, _address in zip(("htc1", "htc2", "antifreeze"), (16, 18, 20)):
    _field = dict(_FIELDS[("COIL", _address)], count=2)
    _item = _make(_field, f"holding.runtime.{_name}_mode", "runtime_control", dataType="control_pair", allowedValues=[0, 1, 2], enumValues={0: "自动", 1: "强制关", 2: "强制开"})
    _item["functionCode"] = [1, 15]
    REGISTER_CATALOG.append(_item)
for _channel, _address in enumerate((24, 26, 28), start=1):
    _field = dict(_FIELDS[("COIL", _address)], count=2)
    _item = _make(_field, f"holding.runtime.valve_{_channel}", "runtime_control", dataType="control_pair", allowedValues=[0, 1, 2], enumValues={0: "释放远程控制", 1: "回原位", 2: "到工作位"})
    _item["functionCode"] = [1, 15]
    REGISTER_CATALOG.append(_item)

_CONFIG_COILS = {
    32: "holding.dehumidification.enabled", 33: "holding.dehumidification.mode", 34: "holding.antifreeze.enabled",
    40: "holding.sensor_1.enabled", 41: "holding.sensor_2.enabled", 42: "holding.sensor_3.enabled",
    43: "holding.pressure.enabled", 44: "holding.flow.enabled", 48: "holding.valve_1.enabled",
    49: "holding.valve_2.enabled", 50: "holding.valve_3.enabled", 52: "holding.valve_1.home_high_level",
    53: "holding.valve_2.home_high_level", 54: "holding.valve_3.home_high_level", 56: "holding.output.htc1_enabled",
    57: "holding.output.htc2_enabled", 58: "holding.output.antifreeze_enabled", 59: "holding.output.alarm_enabled",
    60: "holding.output.htc1_power_on_state", 61: "holding.output.htc2_power_on_state",
    62: "holding.output.antifreeze_power_on_state", 63: "holding.output.alarm_power_on_state",
    64: "holding.alarm.master_enabled", 65: "holding.sensor_3.humidity_alarm_enabled",
    66: "holding.sensor_3.temperature_alarm_enabled", 67: "holding.alarm.humidity_high_enabled",
    68: "holding.alarm.temperature_enabled", 69: "holding.alarm.pressure_enabled", 70: "holding.alarm.flow_no_change_enabled",
    71: "holding.alarm.valve_enabled", 72: "holding.alarm.fault_output_enabled",
    80: "holding.logging.sensor_enabled", 81: "holding.logging.breath_enabled",
}
for _address, _id in _CONFIG_COILS.items(): _add("COIL", _address, _id, "config", allowedValues=[0, 1])
for _task in range(1, 13):
    _add("COIL", 94 + _task * 2, f"holding.schedule.slot_{_task}.enabled", "schedule", allowedValues=[0, 1])
    _add("COIL", 95 + _task * 2, f"holding.schedule.slot_{_task}.humidity_override_enabled", "schedule", allowedValues=[0, 1])

# 保持寄存器。
_HR_IDS = {
    0: "holding.communication.slave_id", 1: "holding.communication.parity", 2: "holding.communication.baudrate",
    8: "holding.logging.sensor_interval", 10: "holding.logging.retention_days", 16: "holding.system.rtc_sync_epoch",
    220: "holding.pressure.offset", 222: "holding.pressure.alarm_high", 224: "holding.pressure.alarm_low",
    240: "holding.flow.offset", 242: "holding.flow.breath_high", 244: "holding.flow.breath_low",
    246: "holding.flow.no_change_alarm_seconds", 260: "holding.dehumidification.cycle_interval_seconds",
    262: "holding.dehumidification.post_heating_cooling_seconds", 264: "holding.dehumidification.force_close_seconds",
    266: "holding.dehumidification.idle_position_upper", 267: "holding.dehumidification.idle_position_left",
    268: "holding.dehumidification.idle_position_right", 280: "holding.antifreeze.source_sensor_id",
    282: "holding.antifreeze.open_temperature", 284: "holding.antifreeze.close_temperature",
    286: "holding.antifreeze.close_delay_seconds", 300: "holding.sensor_fault.humidity_temperature_action",
    301: "holding.sensor_fault.pressure_action", 302: "holding.sensor_fault.flow_action",
}
for _address, _id in _HR_IDS.items(): _add("HR", _address, _id, "time_sync" if _address == 16 else "config")
_SENSOR_OFFSETS = ((0, "temperature_offset"), (2, "humidity_offset"), (4, "temperature_alarm_high"), (6, "temperature_alarm_low"), (8, "humidity_start_threshold"), (10, "humidity_falling_stop_threshold"), (12, "humidity_peak_drop_threshold"), (14, "humidity_alarm_high"), (16, "humidity_alarm_low"), (18, "threshold_confirm_interval_seconds"), (20, "threshold_confirm_count"), (21, "bus"), (22, "modbus_address"))
for _channel, _base in enumerate((100, 132, 164), start=1):
    for _offset, _suffix in _SENSOR_OFFSETS:
        if "alarm" in _suffix and _channel != 3: continue
        _add("HR", _base + _offset, f"holding.sensor_{_channel}.{_suffix}", "config")
for _task in range(1, 13):
    _base = 512 + (_task - 1) * 32
    for _offset, _suffix in ((0, "start_month"), (1, "start_day"), (2, "start_hour"), (3, "start_minute"), (4, "duration_seconds")):
        _add("HR", _base + _offset, f"holding.schedule.slot_{_task}.{_suffix}", "schedule")
    for _channel in range(1, 4):
        _add("HR", _base + 4 + _channel * 2, f"holding.schedule.slot_{_task}.humidity_start_threshold_{_channel}", "schedule")
        _add("HR", _base + 10 + _channel * 2, f"holding.schedule.slot_{_task}.humidity_falling_stop_threshold_{_channel}", "schedule")
        _add("HR", _base + 16 + _channel * 2, f"holding.schedule.slot_{_task}.humidity_peak_drop_threshold_{_channel}", "schedule")

_ENUMS = {
    "holding.communication.parity": {0: "无校验", 1: "奇校验", 2: "偶校验"},
    "holding.dehumidification.mode": {0: "单通道", 1: "双通道"},
    "holding.antifreeze.source_sensor_id": {1: "T1", 2: "T2", 3: "T3"},
}
for _id in ("holding.sensor_fault.humidity_temperature_action", "holding.sensor_fault.pressure_action", "holding.sensor_fault.flow_action"):
    _ENUMS[_id] = {0: "忽略", 1: "报警", 2: "报警并关闭", 3: "报警并切安全位"}
_RANGES = {
    "holding.communication.slave_id": (1, 247), "holding.logging.sensor_interval": (1, 86400),
    "holding.logging.retention_days": (0, 3650), "holding.flow.no_change_alarm_seconds": (0, 31536000),
    "holding.dehumidification.cycle_interval_seconds": (0, 31536000),
    "holding.dehumidification.post_heating_cooling_seconds": (0, 31536000),
    "holding.dehumidification.force_close_seconds": (1, 31536000),
    "holding.antifreeze.close_delay_seconds": (0, 31536000), "holding.system.rtc_sync_epoch": (946684800, 4102444799),
}
_DISPLAY_DURATIONS = {
    # Modbus线协议统一使用秒；上位机按设备LCD和配置文件的业务单位显示。
    "holding.flow.no_change_alarm_seconds": (86400, "天", 0, 365),
    "holding.dehumidification.cycle_interval_seconds": (86400, "天", 0, 365),
    "holding.dehumidification.post_heating_cooling_seconds": (3600, "小时", 0, 8760),
    "holding.dehumidification.force_close_seconds": (3600, "小时", 0.01, 8760),
    "holding.antifreeze.close_delay_seconds": (3600, "小时", 0, 8760),
}
for _item in REGISTER_CATALOG:
    _id = str(_item["id"])
    if _id in _ENUMS:
        _item["enumValues"] = _ENUMS[_id]
        if _item["writable"]: _item["allowedValues"] = list(_ENUMS[_id])
    if _id == "holding.communication.baudrate": _item["allowedValues"] = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
    if _id in _RANGES: _item["minimum"], _item["maximum"] = _RANGES[_id]
    if _id in _DISPLAY_DURATIONS:
        _scale, _unit, _minimum, _maximum = _DISPLAY_DURATIONS[_id]
        _item.update(displayScale=_scale, displayUnit=_unit,
                     displayMinimum=_minimum, displayMaximum=_maximum,
                     displayStep=0.01)
    if ".modbus_address" in _id: _item["minimum"], _item["maximum"] = 0, 247
    if any(_token in _id for _token in ("humidity_start_threshold", "humidity_falling_stop_threshold", "humidity_peak_drop_threshold", "humidity_alarm_")): _item["minimum"], _item["maximum"] = 0, 100
    if ".threshold_confirm_interval_seconds" in _id: _item["minimum"], _item["maximum"] = 1, 86400
    if ".threshold_confirm_count" in _id: _item["minimum"], _item["maximum"] = 1, 10
    if _id.endswith(("idle_position_upper", "idle_position_left", "idle_position_right")): _item["allowedValues"] = [0, 1]


def _validate_catalog() -> None:
    ids: set[str] = set()
    occupied: dict[tuple[str, int], str] = {}
    capacities = {"discrete_input": 128, "input_register": 160, "coil": 128, "holding_register": 1024}
    for item in REGISTER_CATALOG:
        point_id = str(item["id"])
        if point_id in ids: raise RuntimeError(f"重复点ID: {point_id}")
        ids.add(point_id)
        if int(item["addressEnd"]) >= capacities[str(item["area"])]: raise RuntimeError(f"点越界: {point_id}")
        for address in range(int(item["address"]), int(item["addressEnd"]) + 1):
            key = (str(item["area"]), address)
            if key in occupied: raise RuntimeError(f"地址重叠: {key} {occupied[key]} / {point_id}")
            occupied[key] = point_id
    for address in range(20):
        if ("discrete_input", address) not in occupied: raise RuntimeError(f"缺少必选DI{address}")
    for address in range(8):
        if ("input_register", address) not in occupied: raise RuntimeError(f"缺少必选IR{address}")


_validate_catalog()


def get_register_catalog() -> list[dict[str, Any]]: return deepcopy(REGISTER_CATALOG)


def get_register_item(point_id: str) -> dict[str, Any]:
    for item in REGISTER_CATALOG:
        if item["id"] == point_id: return deepcopy(item)
    raise KeyError(f"未知V10点: {point_id}")


def get_register_catalog_summary() -> dict[str, Any]:
    return {"protocolVersion": "10.0", "protocolWord": PROTOCOL_VERSION_WORD,
            "total": len(REGISTER_CATALOG), "readable": len(REGISTER_CATALOG),
            "writable": sum(1 for item in REGISTER_CATALOG if item["writable"]),
            "groups": dict(Counter(item["group"] for item in REGISTER_CATALOG)),
            "areas": dict(Counter(item["area"] for item in REGISTER_CATALOG)),
            "writeEnabled": bool(_MAP.get("write_enabled_by_default"))}
