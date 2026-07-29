"""YLDQ 6.0 / Modbus V9 唯一寄存器点表。

地址与类型直接对应下位机 V9 映射。上位机的轮询、解码、界面和导出都必须引用
这里的点 ID，禁止在业务代码中再次硬编码寄存器地址。
"""

from __future__ import annotations

from collections import Counter
from typing import Any


PROTOCOL_VERSION_WORD = 0x0900

_TYPE_WORDS = {
    "bool": 1,
    "uint16": 1,
    "int16": 1,
    "enum16": 1,
    "bitfield16": 1,
    "uint32": 2,
    "int32": 2,
    "float32": 2,
    "uint64": 4,
}


def _point(
    point_id: str,
    name: str,
    area: str,
    address: int,
    data_type: str = "uint16",
    *,
    group: str,
    unit: str = "",
    writable: bool = False,
    poll_group: str = "standard",
    config_key: str | None = None,
    enum_values: dict[int, str] | None = None,
    bit_definitions: dict[int, str] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    word_length = _TYPE_WORDS[data_type]
    function_codes = [3, 6, 16] if area == "holding_register" and writable else [3] if area == "holding_register" else [4]
    item: dict[str, Any] = {
        "id": point_id,
        "name": name,
        "group": group,
        "functionCode": function_codes,
        "area": area,
        "address": address,
        "addressEnd": address + word_length - 1,
        "wordLength": word_length,
        "dataType": data_type,
        "unit": unit,
        "readable": True,
        "writable": writable,
        "derived": False,
        "pollGroup": poll_group,
        "uiVisible": True,
        "analysisExport": area == "input_register",
        "sourceOfTruth": "firmware-v9",
        "notes": notes,
    }
    if config_key:
        item["configKey"] = config_key
    if enum_values:
        item["enumValues"] = enum_values
    if bit_definitions:
        item["bitDefinitions"] = bit_definitions
    return item


REGISTER_CATALOG: list[dict[str, Any]] = [
    _point("input_register.system.protocol_version", "协议版本", "input_register", 0, group="system", notes="固定值 0x0900"),
    _point(
        "input_register.system.flags", "系统状态标志", "input_register", 1, "bitfield16", group="system",
        bit_definitions={0: "暂存有效", 1: "暂存已修改", 2: "最近提交成功", 4: "任意告警", 5: "HTC1运行", 6: "HTC2运行", 7: "防冻运行"},
    ),
    _point("input_register.system.rtc_seconds", "设备时间", "input_register", 2, "uint32", group="system", unit="s"),
    _point("input_register.system.config_generation", "配置代次", "input_register", 4, group="system"),
    _point("input_register.system.last_config_error", "最近配置错误", "input_register", 5, group="system"),
    _point("input_register.system.display_temperature", "主显示温度", "input_register", 6, "float32", group="system", unit="°C"),
    _point("input_register.system.display_humidity", "主显示湿度", "input_register", 8, "float32", group="system", unit="%RH"),
]


for channel_index, base_address in enumerate((100, 106, 112), start=1):
    prefix = f"input_register.sensor_{channel_index}"
    display = f"温湿度{channel_index}"
    REGISTER_CATALOG.extend([
        _point(f"{prefix}.temperature", f"{display}温度", "input_register", base_address, "float32", group="environment", unit="°C", poll_group="fast"),
        _point(f"{prefix}.humidity", f"{display}湿度", "input_register", base_address + 2, "float32", group="environment", unit="%RH", poll_group="fast"),
        _point(f"{prefix}.status", f"{display}状态", "input_register", base_address + 4, group="environment", poll_group="fast"),
        _point(f"{prefix}.read_ok", f"{display}通信正常", "input_register", base_address + 5, "bool", group="environment", poll_group="fast"),
    ])


REGISTER_CATALOG.extend([
    _point("input_register.pressure", "压力", "input_register", 200, "float32", group="process", unit="kPa", poll_group="fast"),
    _point("input_register.pressure_status", "压力状态", "input_register", 202, group="process", poll_group="fast"),
    _point("input_register.pressure_type", "压力传感器类型", "input_register", 203, group="process", poll_group="fast"),
    _point("input_register.flow", "流量", "input_register", 210, "float32", group="process", unit="L/min", poll_group="fast"),
    _point("input_register.flow_status", "流量状态", "input_register", 212, group="process", poll_group="fast"),
    _point(
        "input_register.breath_state", "呼吸状态", "input_register", 213, "enum16", group="process", poll_group="fast",
        enum_values={65535: "无有效状态", 0: "呼气", 1: "吸气", 2: "无呼吸"},
    ),
    _point("input_register.output.htc1_state", "加热通道1状态", "input_register", 300, "enum16", group="output", poll_group="fast", enum_values={0: "关", 1: "开", 2: "闪烁", 3: "切换中"}),
    _point("input_register.output.htc2_state", "加热通道2状态", "input_register", 301, "enum16", group="output", poll_group="fast", enum_values={0: "关", 1: "开", 2: "闪烁", 3: "切换中"}),
    _point("input_register.output.antifreeze_state", "防冻加热状态", "input_register", 302, "enum16", group="output", poll_group="fast", enum_values={0: "关", 1: "开", 2: "闪烁", 3: "切换中"}),
    _point("input_register.output.alarm_state", "告警输出状态", "input_register", 303, "enum16", group="output", poll_group="fast", enum_values={0: "关", 1: "开", 2: "闪烁", 3: "切换中"}),
    _point("input_register.output.htc1_mode", "加热通道1模式", "input_register", 304, "enum16", group="output", poll_group="fast", enum_values={0: "自动", 1: "强制关", 2: "强制开"}),
    _point("input_register.output.htc2_mode", "加热通道2模式", "input_register", 305, "enum16", group="output", poll_group="fast", enum_values={0: "自动", 1: "强制关", 2: "强制开"}),
    _point("input_register.output.antifreeze_mode", "防冻加热模式", "input_register", 306, "enum16", group="output", poll_group="fast", enum_values={0: "自动", 1: "强制关", 2: "强制开"}),
    _point("input_register.output.remote_heat", "远程加热使能", "input_register", 307, "bool", group="output", poll_group="fast"),
    _point("input_register.output.htc1_open_count", "加热通道1累计打开次数", "input_register", 308, "uint64", group="runtime", unit="次", poll_group="standard"),
    _point("input_register.output.htc2_open_count", "加热通道2累计打开次数", "input_register", 312, "uint64", group="runtime", unit="次", poll_group="standard"),
    _point("input_register.output.antifreeze_open_count", "防冻加热累计打开次数", "input_register", 316, "uint64", group="runtime", unit="次", poll_group="standard"),
])


_VALVE_STATE = {0: "禁用", 1: "原位", 2: "工作位", 3: "运动中", 4: "故障", 5: "未知", 65535: "不可用"}
_VALVE_ACTUATOR_STATE = {0: "空闲", 1: "运动中", 2: "故障", 3: "禁用", 65535: "不可用"}
_VALVE_POSITION = {0: "原位", 1: "工作位", 2: "未知", 65535: "不可用"}
for channel_index, base_address in enumerate((320, 326, 332), start=1):
    prefix = f"input_register.valve_{channel_index}"
    display = f"阀门{channel_index}"
    REGISTER_CATALOG.extend([
        _point(f"{prefix}.display_state", f"{display}显示状态", "input_register", base_address, "enum16", group="valve", poll_group="fast", enum_values=_VALVE_STATE),
        _point(f"{prefix}.actuator_state", f"{display}执行器状态", "input_register", base_address + 1, "enum16", group="valve", poll_group="fast", enum_values=_VALVE_ACTUATOR_STATE),
        _point(f"{prefix}.position", f"{display}位置", "input_register", base_address + 2, "enum16", group="valve", poll_group="fast", enum_values=_VALVE_POSITION),
        _point(f"{prefix}.fault_reason", f"{display}故障原因", "input_register", base_address + 3, group="valve", poll_group="fast"),
        _point(f"{prefix}.current_adc", f"{display}电流采样", "input_register", base_address + 4, group="valve", unit="ADC", poll_group="fast"),
        _point(f"{prefix}.control_source", f"{display}控制来源", "input_register", base_address + 5, "enum16", group="valve", poll_group="fast"),
    ])


REGISTER_CATALOG.extend([
    _point("input_register.alarm.error_group_0", "错误标志组0", "input_register", 400, "uint32", group="alarm"),
    _point("input_register.alarm.error_group_1", "错误标志组1", "input_register", 402, "uint32", group="alarm"),
    _point("input_register.alarm.error_group_2", "错误标志组2", "input_register", 404, "uint32", group="alarm"),
    _point("input_register.communication.online", "通信在线", "input_register", 500, "bool", group="communication"),
    _point("input_register.communication.failure_count", "通信失败次数", "input_register", 501, "uint32", group="communication"),
    _point("input_register.communication.last_success", "最近通信成功时间", "input_register", 503, "uint32", group="communication", unit="s"),
    _point("input_register.communication.last_failure", "最近通信失败时间", "input_register", 505, "uint32", group="communication", unit="s"),
])


def _holding(
    point_id: str,
    name: str,
    address: int,
    data_type: str = "uint16",
    *,
    group: str = "config",
    unit: str = "",
    writable: bool = True,
    poll_group: str = "slow",
    config_key: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    return _point(
        point_id, name, "holding_register", address, data_type, group=group, unit=unit,
        writable=writable, poll_group=poll_group, config_key=config_key, notes=notes,
    )


REGISTER_CATALOG.extend([
    _holding("holding.config.protocol_version", "配置协议版本", 0, writable=False),
    _holding("holding.config.state", "配置事务状态", 1, writable=False),
    _holding("holding.config.generation", "配置代次", 2, writable=False),
    _holding("holding.config.command", "配置事务命令", 3, group="config_transaction"),
    _holding("holding.config.error", "配置事务错误", 4, writable=False),
])


_SENSOR_CONFIG_FIELDS = (
    (0, "enabled", "启用", "bool", ""),
    (1, "bus", "总线", "enum16", ""),
    (2, "modbus_address", "Modbus地址", "uint16", ""),
    (3, "temperature_offset", "温度偏移", "float32", "°C"),
    (5, "humidity_offset", "湿度偏移", "float32", "%RH"),
    (7, "temperature_alarm_high", "温度报警上限", "float32", "°C"),
    (9, "temperature_alarm_low", "温度报警下限", "float32", "°C"),
    (11, "humidity_start_threshold", "启动湿度", "float32", "%RH"),
    (13, "humidity_falling_stop_threshold", "回落停热湿度", "float32", "%RH"),
    (15, "humidity_alarm_high", "湿度报警上限", "float32", "%RH"),
    (17, "humidity_alarm_low", "湿度报警下限", "float32", "%RH"),
    (19, "temperature_alarm_enabled", "温度报警使能", "bool", ""),
    (20, "humidity_alarm_enabled", "湿度报警使能", "bool", ""),
)
_UPPER_SENSOR_ONLY_FIELDS = {
    "temperature_alarm_high", "temperature_alarm_low", "humidity_alarm_high", "humidity_alarm_low",
    "temperature_alarm_enabled", "humidity_alarm_enabled",
}
_SENSOR_CONFIG_KEYS = {
    "enabled": "enabled",
    "bus": "bus",
    "modbus_address": "modbusAddress",
    "temperature_offset": "temperatureOffset",
    "humidity_offset": "humidityOffset",
    "temperature_alarm_high": "temperatureAlarmHigh",
    "temperature_alarm_low": "temperatureAlarmLow",
    "humidity_start_threshold": "humidityStartThreshold",
    "humidity_falling_stop_threshold": "humidityFallingStopThreshold",
    "humidity_alarm_high": "humidityAlarmHigh",
    "humidity_alarm_low": "humidityAlarmLow",
    "temperature_alarm_enabled": "temperatureAlarmEnabled",
    "humidity_alarm_enabled": "humidityAlarmEnabled",
}
for channel_index, base_address in enumerate((100, 121, 142), start=1):
    for offset, key, label, data_type, unit in _SENSOR_CONFIG_FIELDS:
        if channel_index != 3 and key in _UPPER_SENSOR_ONLY_FIELDS:
            continue
        REGISTER_CATALOG.append(_holding(
            f"holding.sensor_{channel_index}.{key}", f"温湿度{channel_index}{label}", base_address + offset,
            data_type, unit=unit,
            config_key=(
                f"sensors.humidityTemperature[{channel_index - 1}]."
                f"{_SENSOR_CONFIG_KEYS[key]}"
            ),
        ))


# 阈值确认属于每路温湿度传感器的运行参数。主传感器配置块已占满，故使用紧随其后的独立连续块。
for channel_index, base_address in enumerate((163, 167, 171), start=1):
    REGISTER_CATALOG.extend([
        _holding(
            f"holding.sensor_{channel_index}.threshold_confirm_interval_seconds",
            f"温湿度{channel_index}阈值确认间隔", base_address, "uint32", unit="秒",
            config_key=f"sensors.humidityTemperature[{channel_index - 1}].thresholdConfirmIntervalSeconds",
            notes="阈值连续确认的采样间隔，范围 1–86400 秒。",
        ),
        _holding(
            f"holding.sensor_{channel_index}.threshold_confirm_count",
            f"温湿度{channel_index}阈值确认次数", base_address + 2, "uint32", unit="次",
            config_key=f"sensors.humidityTemperature[{channel_index - 1}].thresholdConfirmCount",
            notes="达到高/低阈值后需要的确认次数，范围 1–10。",
        ),
    ])


REGISTER_CATALOG.append(_holding(
    "holding.system.rtc_sync_epoch", "同步电脑时间", 175, "uint32", group="time_sync", unit="Unix 秒",
    notes="仅由“同步电脑时间”操作写入；标准 Unix UTC 秒由下位机转换为中国标准时间后写入 RTC，不保存为开机同步配置。",
))


for channel_index, base_address in enumerate((187, 189, 191), start=1):
    REGISTER_CATALOG.append(_holding(
        f"holding.sensor_{channel_index}.humidity_peak_drop_threshold",
        f"温湿度{channel_index}峰值回落幅度",
        base_address,
        "float32",
        unit="%RH",
        config_key=(
            f"sensors.humidityTemperature[{channel_index - 1}]."
            "humidityPeakDropThreshold"
        ),
    ))


_SCHEDULE_FIELDS = (
    (0, "selected_task", "当前编辑任务", "uint16", "", "选择要查看或编辑的任务，范围 1–12。"),
    (1, "task_count", "已配置任务数", "uint16", "条", "任务库中有效任务数，范围 0–12。"),
    (2, "enabled", "当前任务启用", "bool", "", ""),
    (3, "start_month", "开始月份", "uint16", "月", "0 表示不设置开始时间。"),
    (4, "start_day", "开始日期", "uint16", "日", ""),
    (5, "start_hour", "开始小时", "uint16", "时", ""),
    (6, "start_minute", "开始分钟", "uint16", "分", ""),
    (7, "duration_days", "持续时间", "uint32", "天", ""),
    (9, "humidity_override_enabled", "湿度覆盖启用", "bool", "", ""),
    (10, "humidity_start_threshold_1", "温湿度1启动湿度", "float32", "%RH", ""),
    (12, "humidity_start_threshold_2", "温湿度2启动湿度", "float32", "%RH", ""),
    (14, "humidity_start_threshold_3", "温湿度3启动湿度", "float32", "%RH", ""),
    (16, "humidity_falling_stop_threshold_1", "温湿度1回落停热湿度", "float32", "%RH", ""),
    (18, "humidity_falling_stop_threshold_2", "温湿度2回落停热湿度", "float32", "%RH", ""),
    (20, "humidity_falling_stop_threshold_3", "温湿度3回落停热湿度", "float32", "%RH", ""),
    (22, "humidity_peak_drop_threshold_1", "温湿度1峰值回落幅度", "float32", "%RH", ""),
    (24, "humidity_peak_drop_threshold_2", "温湿度2峰值回落幅度", "float32", "%RH", ""),
    (26, "humidity_peak_drop_threshold_3", "温湿度3峰值回落幅度", "float32", "%RH", ""),
)
for offset, key, label, data_type, unit, notes in _SCHEDULE_FIELDS:
    schedule_config_key = f"schedule.current.{key}"
    for field_name, json_name in (
        ("humidity_start_threshold", "humidityStartThreshold"),
        ("humidity_falling_stop_threshold", "humidityFallingStopThreshold"),
        ("humidity_peak_drop_threshold", "humidityPeakDropThreshold"),
    ):
        if key.startswith(f"{field_name}_"):
            schedule_config_key = (
                f"schedule.current.{json_name}[{int(key.rsplit('_', 1)[1]) - 1}]"
            )
            break
    REGISTER_CATALOG.append(_holding(
        f"holding.schedule.{key}", label, 720 + offset, data_type, group="schedule",
        unit=unit, config_key=schedule_config_key, notes=notes,
    ))
REGISTER_CATALOG.append(_holding(
    "holding.schedule.operation", "任务增删操作", 748, "uint16", group="schedule",
    config_key="schedule.operation",
    notes="写 1 添加任务，写 2 删除当前任务；操作只修改暂存区，仍需通过 HR3 提交。",
))


_CONFIG_BLOCKS: tuple[tuple[int, str, str, tuple[tuple[int, str, str, str, str, str], ...]], ...] = (
    (200, "pressure", "压力", (
        (0, "enabled", "启用", "bool", "", "sensors.pressure.enabled"),
        (1, "offset", "偏移", "float32", "kPa", "sensors.pressure.offset"),
        (3, "alarm_high", "报警上限", "float32", "kPa", "sensors.pressure.alarmHigh"),
        (5, "alarm_low", "报警下限", "float32", "kPa", "sensors.pressure.alarmLow"),
    )),
    (220, "flow", "流量", (
        (0, "enabled", "启用", "bool", "", "sensors.flow.enabled"),
        (1, "offset", "偏移", "float32", "L/min", "sensors.flow.offset"),
        (3, "breath_high", "呼吸高阈值", "float32", "L/min", "sensors.flow.breathHigh"),
        (5, "breath_low", "呼吸低阈值", "float32", "L/min", "sensors.flow.breathLow"),
        (7, "no_change_alarm_days", "无变化报警时间", "uint32", "天", "sensors.flow.noChangeAlarmDays"),
    )),
    (400, "dehumidification", "除湿", (
        (0, "enabled", "启用", "bool", "", "control.dehumidification.enabled"),
        (1, "mode", "工作模式", "enum16", "", "control.dehumidification.mode"),
        (2, "cycle_interval_days", "自动重启与维护换路周期", "uint32", "天", "control.dehumidification.cycleIntervalDays"),
        (4, "post_heating_cooling_hours", "停热后设备冷却时间", "uint32", "小时", "control.dehumidification.postHeatingCoolingHours"),
        (6, "force_close_hours", "最长加热时间", "uint32", "小时", "control.dehumidification.forceCloseHours"),
        (8, "idle_position_upper", "上阀业务空闲位置", "enum16", "", "control.dehumidification.idlePositions.upper"),
        (9, "idle_position_left", "左阀业务空闲位置", "enum16", "", "control.dehumidification.idlePositions.left"),
        (10, "idle_position_right", "右阀业务空闲位置", "enum16", "", "control.dehumidification.idlePositions.right"),
    )),
    (420, "antifreeze", "防冻", (
        (0, "enabled", "启用", "bool", "", "control.antifreeze.enabled"),
        (1, "source_sensor_id", "来源传感器", "uint16", "", "control.antifreeze.sourceSensorId"),
        (2, "open_temperature", "开启温度", "float32", "°C", "control.antifreeze.openTemperature"),
        (4, "close_temperature", "关闭温度", "float32", "°C", "control.antifreeze.closeTemperature"),
        (6, "close_delay_hours", "关闭延时", "uint32", "小时", "control.antifreeze.closeDelayHours"),
    )),
    (430, "sensor_fault", "传感器故障", (
        (0, "humidity_temperature_action", "温湿度故障动作", "enum16", "", "control.sensorFault.humidityTemperatureFaultAction"),
        (1, "pressure_action", "压力故障动作", "enum16", "", "control.sensorFault.pressureFaultAction"),
        (2, "flow_action", "流量故障动作", "enum16", "", "control.sensorFault.flowFaultAction"),
    )),
    (500, "output", "输出", (
        (0, "htc1_enabled", "加热通道1启用", "bool", "", "outputs.heatChannel1.enabled"),
        (1, "htc1_power_on_state", "加热通道1上电状态", "enum16", "", "outputs.heatChannel1.powerOnState"),
        (2, "htc2_enabled", "加热通道2启用", "bool", "", "outputs.heatChannel2.enabled"),
        (3, "htc2_power_on_state", "加热通道2上电状态", "enum16", "", "outputs.heatChannel2.powerOnState"),
        (4, "antifreeze_enabled", "防冻加热启用", "bool", "", "outputs.antifreeze.enabled"),
        (5, "antifreeze_power_on_state", "防冻加热上电状态", "enum16", "", "outputs.antifreeze.powerOnState"),
        (6, "alarm_enabled", "告警输出启用", "bool", "", "outputs.alarm.enabled"),
        (7, "alarm_power_on_state", "告警输出上电状态", "enum16", "", "outputs.alarm.powerOnState"),
    )),
    (520, "alarm", "告警", (
        (0, "master_enabled", "总开关", "bool", "", "alarm.enabled"),
        (1, "humidity_high_enabled", "湿度高报警", "bool", "", "alarm.humidityHighAlarm"),
        (2, "temperature_enabled", "温度报警", "bool", "", "alarm.temperatureAlarm"),
        (3, "pressure_enabled", "压力报警", "bool", "", "alarm.pressureAlarm"),
        (4, "flow_no_change_enabled", "流量无变化报警", "bool", "", "alarm.flowNoChangeAlarm"),
        (5, "valve_enabled", "阀门报警", "bool", "", "alarm.valveFaultAlarm"),
        (6, "fault_output_enabled", "故障输出", "bool", "", "alarm.alarmOutputOnFault"),
    )),
    (600, "logging", "记录", (
        (0, "sensor_enabled", "传感器日志使能", "bool", "", "logging.sensorLogEnabled"),
        (1, "sensor_interval", "传感器记录周期", "uint32", "秒", "logging.sensorLogIntervalSeconds"),
        (3, "breath_enabled", "呼吸记录使能", "bool", "", "logging.breathRecordEnabled"),
        (4, "retention_days", "保留天数", "uint16", "天", "logging.retainDays"),
    )),
    (700, "communication", "通信", (
        (0, "slave_id", "从站地址", "uint16", "", "communication.modbus.slaveAddress"),
        (1, "baudrate", "波特率", "uint32", "bit/s", "communication.modbus.baudRate"),
        (3, "parity", "校验方式", "enum16", "", "communication.modbus.parity"),
    )),
)
for base, prefix, display, fields in _CONFIG_BLOCKS:
    for offset, key, label, data_type, unit, config_key in fields:
        REGISTER_CATALOG.append(_holding(
            f"holding.{prefix}.{key}", f"{display}{label}", base + offset, data_type,
            unit=unit, config_key=config_key,
        ))


for channel_index, (role, display, base_address) in enumerate((
    ("upper", "上阀", 300),
    ("left", "左阀", 302),
    ("right", "右阀", 304),
), start=1):
    REGISTER_CATALOG.extend([
        _holding(f"holding.valve_{channel_index}.enabled", f"{display}启用", base_address, "bool", config_key=f"valves.{role}.enabled"),
        _holding(f"holding.valve_{channel_index}.home_high_level", f"{display}回零方向高电平", base_address + 1, "bool", config_key=f"valves.{role}.homeDirectionHigh"),
    ])


REGISTER_CATALOG.extend([
    _holding("holding.runtime.remote_heat", "远程加热", 800, "bool", group="runtime_control"),
    _holding("holding.runtime.htc1_mode", "加热通道1模式", 801, group="runtime_control"),
    _holding("holding.runtime.htc2_mode", "加热通道2模式", 802, group="runtime_control"),
    _holding("holding.runtime.antifreeze_mode", "防冻加热模式", 803, group="runtime_control"),
    _holding("holding.runtime.valve_1", "阀门1命令", 804, group="runtime_control"),
    _holding("holding.runtime.valve_2", "阀门2命令", 805, group="runtime_control"),
    _holding("holding.runtime.valve_3", "阀门3命令", 806, group="runtime_control"),
    _holding("holding.runtime.reset", "阀门故障复位/系统复位", 807, group="runtime_control",
             notes="1/2/4/7 为阀门故障复位掩码；0xA55A 为远程系统复位。"),
])
for channel_index, base_address in enumerate((808, 811, 814), start=1):
    REGISTER_CATALOG.extend([
        _holding(f"holding.runtime.valve_{channel_index}_diagnostic_fault", f"阀门{channel_index}故障原因", base_address, group="diagnostic", writable=False),
        _holding(f"holding.runtime.valve_{channel_index}_diagnostic_source", f"阀门{channel_index}生效控制源", base_address + 1, group="diagnostic", writable=False),
        _holding(f"holding.runtime.valve_{channel_index}_remote_seconds", f"阀门{channel_index}远程命令剩余时间", base_address + 2, group="diagnostic", unit="s", writable=False),
    ])
REGISTER_CATALOG.extend([
    _holding(
        "holding.runtime.valve_guard_reason", "阀门动作保护原因", 817, "enum16",
        group="diagnostic", writable=False, poll_group="fast",
    ),
    _holding(
        "holding.runtime.valve_guard_remaining_seconds", "阀门动作保护剩余时间", 818,
        group="diagnostic", unit="s", writable=False, poll_group="fast",
    ),
    _holding(
        "holding.runtime.valve_action_count", "阀门当前动作脉冲数", 819,
        group="diagnostic", unit="次", writable=False, poll_group="fast",
    ),
    _holding(
        "holding.runtime.valve_action_limit", "阀门动作脉冲上限", 820,
        group="diagnostic", unit="次", writable=False, poll_group="fast",
    ),
])


_ENUM_MAPS: dict[str, dict[int, str]] = {
    "holding.runtime.htc1_mode": {0: "自动", 1: "强制关", 2: "强制开"},
    "holding.runtime.htc2_mode": {0: "自动", 1: "强制关", 2: "强制开"},
    "holding.runtime.antifreeze_mode": {0: "自动", 1: "强制关", 2: "强制开"},
    "holding.runtime.reset": {0: "无操作", 1: "复位阀门1故障", 2: "复位阀门2故障", 4: "复位阀门3故障", 7: "复位全部阀门故障", 0xA55A: "远程系统复位"},
    "holding.runtime.valve_guard_reason": {
        0: "无保护", 1: "开机充电等待", 2: "阀门动作保护", 3: "阀门未到位重试等待",
    },
    **{f"holding.sensor_{channel}.bus": {0: "UART", 1: "I2C"} for channel in range(1, 4)},
    "holding.dehumidification.mode": {0: "单管", 1: "双管"},
    **{f"holding.dehumidification.idle_position_{role}": {0: "原位", 1: "工作位"}
       for role in ("upper", "left", "right")},
    "holding.communication.parity": {0: "无校验", 1: "奇校验", 2: "偶校验"},
    **{f"holding.runtime.valve_{channel}": {0: "释放远程控制", 1: "回原位", 2: "到工作位", 3: "回原点校准"} for channel in range(1, 4)},
    **{f"holding.runtime.valve_{channel}_diagnostic_fault": {
        0: "无故障", 1: "阀门编号无效", 2: "阀门忙", 3: "动作队列已满", 4: "回原位超时",
        5: "目标位置校验失败", 6: "驱动器故障", 7: "过流", 8: "开路", 9: "限位开关卡滞",
    } for channel in range(1, 4)},
    **{f"input_register.valve_{channel}.control_source": {
        0: "自动", 1: "远程", 2: "安全保护", 3: "周期维护",
    } for channel in range(1, 4)},
    **{f"holding.runtime.valve_{channel}_diagnostic_source": {
        0: "自动", 1: "远程", 2: "安全保护", 3: "周期维护",
    } for channel in range(1, 4)},
}
for point_id in (
    "holding.sensor_fault.humidity_temperature_action",
    "holding.sensor_fault.pressure_action",
    "holding.sensor_fault.flow_action",
):
    _ENUM_MAPS[point_id] = {
        0: "忽略",
        1: "仅报警",
        2: "报警并停热",
        3: "报警停热并回安全位",
    }
for point_id in (
    "holding.output.htc1_power_on_state", "holding.output.htc2_power_on_state",
    "holding.output.antifreeze_power_on_state", "holding.output.alarm_power_on_state",
):
    _ENUM_MAPS[point_id] = {0: "上电关闭", 1: "上电开启"}
for item in REGISTER_CATALOG:
    enum_values = _ENUM_MAPS.get(str(item["id"]))
    if enum_values:
        item["enumValues"] = enum_values

_VALUE_CONSTRAINTS = {
    "holding.flow.no_change_alarm_days": (0, 365),
    "holding.dehumidification.cycle_interval_days": (0, 365),
    "holding.dehumidification.post_heating_cooling_hours": (0, 8760),
    "holding.dehumidification.force_close_hours": (1, 8760),
    "holding.antifreeze.close_delay_hours": (0, 8760),
    "holding.antifreeze.source_sensor_id": (1, 3),
    "holding.logging.sensor_interval": (1, 86400),
    "holding.logging.retention_days": (0, 3650),
    "holding.communication.slave_id": (1, 247),
    **{f"holding.sensor_{channel}.threshold_confirm_interval_seconds": (1, 86400) for channel in range(1, 4)},
    **{f"holding.sensor_{channel}.threshold_confirm_count": (1, 10) for channel in range(1, 4)},
    **{f"holding.sensor_{channel}.humidity_start_threshold": (0, 100) for channel in range(1, 4)},
    **{f"holding.sensor_{channel}.humidity_falling_stop_threshold": (0, 100) for channel in range(1, 4)},
    **{f"holding.sensor_{channel}.humidity_peak_drop_threshold": (0.01, 100) for channel in range(1, 4)},
    "holding.system.rtc_sync_epoch": (946684800, 4102444799),
    "holding.schedule.selected_task": (1, 12),
    "holding.schedule.task_count": (0, 12),
    "holding.schedule.start_month": (0, 12),
    "holding.schedule.start_day": (0, 31),
    "holding.schedule.start_hour": (0, 23),
    "holding.schedule.start_minute": (0, 59),
    "holding.schedule.duration_days": (0, 3650),
    "holding.schedule.operation": (1, 2),
    **{
        f"holding.schedule.{field}_{channel}": (0.01 if field == "humidity_peak_drop_threshold" else 0, 100)
        for field in (
            "humidity_start_threshold",
            "humidity_falling_stop_threshold",
            "humidity_peak_drop_threshold",
        )
        for channel in range(1, 4)
    },
}
_ALLOWED_VALUES = {
    "holding.communication.baudrate": [
        1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200
    ],
}
for item in REGISTER_CATALOG:
    point_id = str(item["id"])
    if point_id in _VALUE_CONSTRAINTS:
        minimum, maximum = _VALUE_CONSTRAINTS[point_id]
        item["minimum"] = minimum
        item["maximum"] = maximum
        item["step"] = 0.01 if isinstance(minimum, float) else 1
    if point_id in _ALLOWED_VALUES:
        item["allowedValues"] = list(_ALLOWED_VALUES[point_id])


def _validate_catalog() -> None:
    point_ids: set[str] = set()
    occupied: dict[tuple[str, int], str] = {}
    for item in REGISTER_CATALOG:
        point_id = str(item["id"])
        if point_id in point_ids:
            raise RuntimeError(f"重复点 ID: {point_id}")
        point_ids.add(point_id)
        for address in range(int(item["address"]), int(item["addressEnd"]) + 1):
            key = (str(item["area"]), address)
            if key in occupied:
                raise RuntimeError(f"寄存器重叠: {key} ({occupied[key]} / {point_id})")
            occupied[key] = point_id


_validate_catalog()


def get_register_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in REGISTER_CATALOG]


def get_register_catalog_summary() -> dict[str, Any]:
    group_counts = Counter(item["group"] for item in REGISTER_CATALOG)
    area_counts = Counter(item["area"] for item in REGISTER_CATALOG)
    return {
        "protocolVersion": "9.0",
        "protocolWord": PROTOCOL_VERSION_WORD,
        "total": len(REGISTER_CATALOG),
        "readable": len(REGISTER_CATALOG),
        "writable": sum(1 for item in REGISTER_CATALOG if item["writable"]),
        "groups": dict(group_counts),
        "areas": dict(area_counts),
    }
