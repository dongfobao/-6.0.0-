"""YLDQ 6.0 / Modbus V7 唯一寄存器点表。

地址与类型直接对应下位机 V7 映射。上位机的轮询、解码、界面和导出都必须引用
这里的点 ID，禁止在业务代码中再次硬编码寄存器地址。
"""

from __future__ import annotations

from collections import Counter
from typing import Any


PROTOCOL_VERSION_WORD = 0x0700

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
        "sourceOfTruth": "firmware-v7",
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
    _point("input_register.system.protocol_version", "协议版本", "input_register", 0, group="system", notes="固定值 0x0700"),
    _point(
        "input_register.system.flags", "系统状态标志", "input_register", 1, "bitfield16", group="system",
        bit_definitions={0: "暂存有效", 1: "暂存已修改", 2: "最近提交成功", 4: "任意告警", 5: "HTC1运行", 6: "HTC2运行", 7: "防冻运行"},
    ),
    _point("input_register.system.rtc_seconds", "设备时间", "input_register", 2, "uint32", group="system", unit="s"),
    _point("input_register.system.config_generation", "配置代次", "input_register", 4, group="system"),
    _point("input_register.system.last_config_error", "最近配置错误", "input_register", 5, group="system"),
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
for channel_index, base_address in enumerate((320, 326, 332), start=1):
    prefix = f"input_register.valve_{channel_index}"
    display = f"阀门{channel_index}"
    REGISTER_CATALOG.extend([
        _point(f"{prefix}.display_state", f"{display}显示状态", "input_register", base_address, "enum16", group="valve", poll_group="fast", enum_values=_VALVE_STATE),
        _point(f"{prefix}.actuator_state", f"{display}执行器状态", "input_register", base_address + 1, "enum16", group="valve", poll_group="fast", enum_values=_VALVE_STATE),
        _point(f"{prefix}.position", f"{display}位置", "input_register", base_address + 2, group="valve", unit="%", poll_group="fast"),
        _point(f"{prefix}.fault_reason", f"{display}故障原因", "input_register", base_address + 3, group="valve", poll_group="fast"),
        _point(f"{prefix}.current_adc", f"{display}电流采样", "input_register", base_address + 4, group="valve", unit="ADC", poll_group="fast"),
        _point(f"{prefix}.control_source", f"{display}控制来源", "input_register", base_address + 5, "enum16", group="valve", poll_group="fast"),
    ])


REGISTER_CATALOG.extend([
    _point("input_register.alarm.active_low", "活动告警低位", "input_register", 400, "uint32", group="alarm"),
    _point("input_register.alarm.active_high", "活动告警高位", "input_register", 402, "uint32", group="alarm"),
    _point("input_register.alarm.latched", "锁存告警", "input_register", 404, "uint32", group="alarm"),
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
    config_key: str | None = None,
    notes: str = "",
) -> dict[str, Any]:
    return _point(
        point_id, name, "holding_register", address, data_type, group=group, unit=unit,
        writable=writable, poll_group="slow", config_key=config_key, notes=notes,
    )


REGISTER_CATALOG.extend([
    _holding("holding.config.protocol_version", "配置协议版本", 0, writable=False),
    _holding("holding.config.state", "配置事务状态", 1, writable=False),
    _holding("holding.config.generation", "配置代次", 2, writable=False),
    _holding("holding.config.command", "配置事务命令", 3, group="config_transaction"),
    _holding("holding.config.error", "配置事务错误", 4, writable=False),
])


_SENSOR_CONFIG_FIELDS = (
    (0, "online", "启用", "bool", ""),
    (1, "bus", "总线", "enum16", ""),
    (2, "modbus_address", "Modbus地址", "uint16", ""),
    (3, "temperature_offset", "温度偏移", "float32", "°C"),
    (5, "humidity_offset", "湿度偏移", "float32", "%RH"),
    (7, "temperature_alarm_high", "温度报警上限", "float32", "°C"),
    (9, "temperature_alarm_low", "温度报警下限", "float32", "°C"),
    (11, "humidity_control_high", "湿度控制上限", "float32", "%RH"),
    (13, "humidity_control_low", "湿度控制下限", "float32", "%RH"),
    (15, "humidity_alarm_high", "湿度报警上限", "float32", "%RH"),
    (17, "humidity_alarm_low", "湿度报警下限", "float32", "%RH"),
    (19, "temperature_alarm_enabled", "温度报警使能", "bool", ""),
    (20, "humidity_alarm_enabled", "湿度报警使能", "bool", ""),
)
for channel_index, base_address in enumerate((100, 121, 142), start=1):
    for offset, key, label, data_type, unit in _SENSOR_CONFIG_FIELDS:
        REGISTER_CATALOG.append(_holding(
            f"holding.sensor_{channel_index}.{key}", f"温湿度{channel_index}{label}", base_address + offset,
            data_type, unit=unit, config_key=f"sensors[{channel_index - 1}].{key}",
        ))


_CONFIG_BLOCKS: tuple[tuple[int, str, str, tuple[tuple[int, str, str, str, str], ...]], ...] = (
    (200, "pressure", "压力", (
        (0, "online", "启用", "bool", ""), (1, "offset", "偏移", "float32", "kPa"),
        (3, "alarm_high", "报警上限", "float32", "kPa"), (5, "alarm_low", "报警下限", "float32", "kPa"),
    )),
    (220, "flow", "流量", (
        (0, "online", "启用", "bool", ""), (1, "offset", "偏移", "float32", "L/min"),
        (3, "breath_high", "呼吸高阈值", "float32", "L/min"), (5, "breath_low", "呼吸低阈值", "float32", "L/min"),
        (7, "no_change_alarm_days", "无变化报警时间", "uint32", "天"),
    )),
    (400, "control", "控制", (
        (0, "humidity_enabled", "湿度控制使能", "bool", ""), (1, "antifreeze_enabled", "防冻使能", "bool", ""),
        (2, "antifreeze_sensor_id", "防冻传感器ID", "uint16", ""), (3, "antifreeze_on_temperature", "防冻开启温度", "float32", "°C"),
        (5, "antifreeze_off_temperature", "防冻关闭温度", "float32", "°C"), (7, "close_delay_hours", "关闭延时", "uint32", "小时"),
        (9, "temperature_humidity_fault_action", "温湿度故障动作", "enum16", ""),
        (10, "pressure_fault_action", "压力故障动作", "enum16", ""), (11, "flow_fault_action", "流量故障动作", "enum16", ""),
    )),
    (500, "output", "输出", (
        (0, "htc1_online", "加热通道1启用", "bool", ""), (1, "htc1_power_on_state", "加热通道1上电状态", "enum16", ""),
        (2, "htc2_online", "加热通道2启用", "bool", ""), (3, "htc2_power_on_state", "加热通道2上电状态", "enum16", ""),
        (4, "antifreeze_online", "防冻加热启用", "bool", ""), (5, "antifreeze_power_on_state", "防冻加热上电状态", "enum16", ""),
        (6, "alarm_online", "告警输出启用", "bool", ""), (7, "alarm_power_on_state", "告警输出上电状态", "enum16", ""),
    )),
    (520, "alarm", "告警", (
        (0, "master_enabled", "总开关", "bool", ""), (1, "humidity_high_enabled", "湿度高报警", "bool", ""),
        (2, "temperature_enabled", "温度报警", "bool", ""), (3, "pressure_enabled", "压力报警", "bool", ""),
        (4, "flow_no_change_enabled", "流量无变化报警", "bool", ""), (5, "valve_enabled", "阀门报警", "bool", ""),
        (6, "fault_output_enabled", "故障输出", "bool", ""),
    )),
    (600, "logging", "记录", (
        (0, "sensor_enabled", "传感器日志使能", "bool", ""), (1, "sensor_interval", "传感器记录周期", "uint32", "s"),
        (3, "breath_enabled", "呼吸记录使能", "bool", ""), (4, "retention_days", "保留天数", "uint16", "d"),
    )),
    (700, "communication", "通信", (
        (0, "slave_id", "从站地址", "uint16", ""), (1, "baudrate", "波特率", "uint32", "bit/s"),
        (3, "parity", "校验方式", "enum16", ""),
    )),
)
for base, prefix, display, fields in _CONFIG_BLOCKS:
    for offset, key, label, data_type, unit in fields:
        REGISTER_CATALOG.append(_holding(
            f"holding.{prefix}.{key}", f"{display}{label}", base + offset, data_type,
            unit=unit, config_key=f"{prefix}.{key}",
        ))


REGISTER_CATALOG.extend([
    _holding("holding.valve_route.mode", "阀门路由模式", 300, "enum16", config_key="control.valveRouting.mode"),
    _holding("holding.valve_route.restart_protection_days", "停热后同路再次启动保护间隔", 301, "uint32", unit="天", config_key="control.valveRouting.switchIntervalDays"),
    _holding("holding.valve_route.force_close_days", "强制关闭时间", 303, "uint32", unit="天", config_key="control.valveRouting.forceCloseDays"),
    _holding("holding.valve_route.initial_route", "阀门初始路由", 305, "enum16", config_key="control.valveRouting.initialRoute"),
    _holding("holding.valve_route.cooling_delay_hours", "停热后阀门冷却延时", 306, "uint32", unit="小时", config_key="control.valveRouting.valveCoolingHours"),
])
for channel_index, base_address in enumerate((310, 312, 314), start=1):
    REGISTER_CATALOG.extend([
        _holding(f"holding.valve_{channel_index}.online", f"阀门{channel_index}启用", base_address, "bool", config_key=f"valves[{channel_index - 1}].online"),
        _holding(f"holding.valve_{channel_index}.home_high_level", f"阀门{channel_index}回零方向高电平", base_address + 1, "bool", config_key=f"valves[{channel_index - 1}].home_high_level"),
    ])


REGISTER_CATALOG.extend([
    _holding("holding.runtime.remote_heat", "远程加热", 800, "bool", group="runtime_control"),
    _holding("holding.runtime.htc1_mode", "加热通道1模式", 801, group="runtime_control"),
    _holding("holding.runtime.htc2_mode", "加热通道2模式", 802, group="runtime_control"),
    _holding("holding.runtime.antifreeze_mode", "防冻加热模式", 803, group="runtime_control"),
    _holding("holding.runtime.valve_1", "阀门1命令", 804, group="runtime_control"),
    _holding("holding.runtime.valve_2", "阀门2命令", 805, group="runtime_control"),
    _holding("holding.runtime.valve_3", "阀门3命令", 806, group="runtime_control"),
    _holding("holding.runtime.reset", "复位命令", 807, group="runtime_control"),
])
for channel_index, base_address in enumerate((808, 811, 814), start=1):
    REGISTER_CATALOG.extend([
        _holding(f"holding.runtime.valve_{channel_index}_diagnostic_fault", f"阀门{channel_index}故障原因", base_address, group="diagnostic", writable=False),
        _holding(f"holding.runtime.valve_{channel_index}_diagnostic_source", f"阀门{channel_index}生效控制源", base_address + 1, group="diagnostic", writable=False),
        _holding(f"holding.runtime.valve_{channel_index}_remote_seconds", f"阀门{channel_index}远程命令剩余时间", base_address + 2, group="diagnostic", unit="s", writable=False),
    ])


_ENUM_MAPS: dict[str, dict[int, str]] = {
    **{f"holding.sensor_{channel}.bus": {0: "UART", 1: "I2C"} for channel in range(1, 4)},
    "holding.valve_route.mode": {0: "自动", 1: "固定", 2: "轮换"},
    "holding.valve_route.initial_route": {0: "上阀", 1: "左阀", 2: "右阀"},
    "holding.communication.parity": {0: "无校验", 1: "奇校验", 2: "偶校验"},
}
for point_id in (
    "holding.control.temperature_humidity_fault_action",
    "holding.control.pressure_fault_action",
    "holding.control.flow_fault_action",
):
    _ENUM_MAPS[point_id] = {0: "保持", 1: "关闭相关输出", 2: "进入安全状态"}
for point_id in (
    "holding.output.htc1_power_on_state", "holding.output.htc2_power_on_state",
    "holding.output.antifreeze_power_on_state", "holding.output.alarm_power_on_state",
):
    _ENUM_MAPS[point_id] = {0: "上电关闭", 1: "上电开启"}
for item in REGISTER_CATALOG:
    enum_values = _ENUM_MAPS.get(str(item["id"]))
    if enum_values:
        item["enumValues"] = enum_values

_CONFIG_KEY_OVERRIDES = {
    "holding.flow.no_change_alarm_days": "sensors.flow.noChangeAlarmDays",
    "holding.control.close_delay_hours": "control.antifreeze.closeDelayHours",
}
_VALUE_CONSTRAINTS = {
    "holding.flow.no_change_alarm_days": (0, 365),
    "holding.valve_route.restart_protection_days": (0, 365),
    "holding.valve_route.force_close_days": (0, 365),
    "holding.valve_route.cooling_delay_hours": (0, 8760),
    "holding.control.close_delay_hours": (0, 8760),
}
for item in REGISTER_CATALOG:
    point_id = str(item["id"])
    if point_id in _CONFIG_KEY_OVERRIDES:
        item["configKey"] = _CONFIG_KEY_OVERRIDES[point_id]
    if point_id in _VALUE_CONSTRAINTS:
        minimum, maximum = _VALUE_CONSTRAINTS[point_id]
        item["minimum"] = minimum
        item["maximum"] = maximum
        item["step"] = 1


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
        "protocolVersion": "7.0",
        "protocolWord": PROTOCOL_VERSION_WORD,
        "total": len(REGISTER_CATALOG),
        "readable": len(REGISTER_CATALOG),
        "writable": sum(1 for item in REGISTER_CATALOG if item["writable"]),
        "groups": dict(group_counts),
        "areas": dict(area_counts),
    }
