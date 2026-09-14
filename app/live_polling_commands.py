"""Modbus V10固定合法轮询计划。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from live_register_catalog import get_register_catalog, get_register_item

READ_FUNCTION_AREAS = {1: "coil", 2: "discrete_input", 3: "holding_register", 4: "input_register"}

# 先读协议字，再读必选点和扩展监测点；配置块只在参数页面按需读取。
_DEFAULT_BLOCKS = (
    ("standard", 4, "input_register.system.protocol_version", 37, True, 250, "协议、诊断与链路"),
    ("fast", 2, "input_register.output.total_heat_state", 20, True, 120, "必选状态与报警"),
    ("fast", 4, "input_register.sensor_3.temperature", 8, True, 120, "必选温湿度、压力和流量"),
    ("fast", 2, "input_register.sensor_1.read_ok", 19, True, 120, "扩展有效性与故障"),
    ("fast", 2, "discrete_input.valve_1.home_not_reached", 22, True, 120, "三阀位置状态"),
    ("fast", 2, "discrete_input.heat_session_1.active", 19, True, 120, "会话与阀校准状态"),
    ("fast", 4, "input_register.sensor_1.temperature", 8, True, 120, "左右温湿度"),
    ("fast", 4, "input_register.heat_session_1.session_run_seconds", 66, True, 120, "运行统计、会话和阀诊断"),
    ("fast", 1, "holding.runtime.remote_heat", 11, True, 200, "运行请求与脉冲命令"),
    ("fast", 1, "holding.runtime.htc1_mode", 14, True, 200, "加热及阀成对控制"),
    ("slow", 1, "holding.dehumidification.enabled", 41, False, 500, "设备布尔配置"),
    ("slow", 1, "holding.logging.sensor_enabled", 2, False, 500, "记录配置"),
    ("slow", 1, "holding.schedule.slot_1.enabled", 24, False, 500, "任务使能配置"),
    ("slow", 3, "holding.communication.slave_id", 11, False, 500, "通信及日志数值配置"),
    ("slow", 3, "holding.system.rtc_sync_epoch", 2, False, 500, "RTC校时值"),
    ("slow", 3, "holding.sensor_1.temperature_offset", 23, False, 500, "T1参数"),
    ("slow", 3, "holding.sensor_2.temperature_offset", 23, False, 500, "T2参数"),
    ("slow", 3, "holding.sensor_3.temperature_offset", 23, False, 500, "T3参数"),
    ("slow", 3, "holding.pressure.offset", 6, False, 500, "压力参数"),
    ("slow", 3, "holding.flow.offset", 8, False, 500, "流量参数"),
    ("slow", 3, "holding.dehumidification.cycle_interval_seconds", 9, False, 500, "除湿参数"),
    ("slow", 3, "holding.antifreeze.source_sensor_id", 8, False, 500, "防冻参数"),
    ("slow", 3, "holding.sensor_fault.humidity_temperature_action", 3, False, 500, "故障策略"),
    *(("slow", 3, f"holding.schedule.slot_{task}.start_month", 24, False, 500, f"任务{task}数值参数") for task in range(1, 13)),
)


def _item_ids_for_block(catalog: list[dict[str, Any]], function_code: int, address: int, count: int) -> list[str]:
    area = READ_FUNCTION_AREAS[function_code]
    end = address + count - 1
    return [str(item["id"]) for item in catalog if item.get("area") == area and int(item["address"]) >= address and int(item["addressEnd"]) <= end]


def _request_template(function_code: int, address: int, count: int) -> str:
    return f"{{slaveId}} {function_code:02X} {address >> 8:02X} {address & 0xFF:02X} {count >> 8:02X} {count & 0xFF:02X}"


def build_default_polling_commands(catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    source = [dict(item) for item in (catalog or get_register_catalog())]
    commands: list[dict[str, Any]] = []
    for group, function_code, start_id, count, auto_poll, delay_ms, name in _DEFAULT_BLOCKS:
        address = int(get_register_item(start_id)["address"])
        commands.append({
            "id": f"v10.{group}.fc{function_code}.{address}.{count}", "name": name,
            "mode": "modbus_read", "functionCode": function_code,
            "area": READ_FUNCTION_AREAS[function_code], "address": address, "count": count,
            "requestHex": _request_template(function_code, address, count), "appendCrc": True,
            "expectResponse": True, "responseMode": "modbus", "responseTimeoutMs": None,
            "autoPoll": auto_poll, "delayAfterMs": delay_ms, "sourceGroup": group,
            "decodeMode": "catalog", "catalogItemIds": _item_ids_for_block(source, function_code, address, count),
        })
    return commands


def normalize_polling_commands(commands: Any, catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """旧版或被改写的轮询计划全部替换为V10固定计划。"""
    defaults = build_default_polling_commands(catalog)
    if not isinstance(commands, list) or len(commands) != len(defaults): return defaults
    expected = {(int(x["functionCode"]), int(x["address"]), int(x["count"])) for x in defaults}
    provided: set[tuple[int, int, int]] = set()
    for command in commands:
        if not isinstance(command, dict): return defaults
        try: block = (int(command.get("functionCode")), int(command.get("address")), int(command.get("count")))
        except (TypeError, ValueError): return defaults
        if block not in expected or block in provided: return defaults
        provided.add(block)
    return deepcopy(defaults) if provided == expected else defaults


def _optional_timeout(value: Any) -> int | None:
    if value in {None, ""}: return None
    try: return max(50, int(value))
    except (TypeError, ValueError): return None
