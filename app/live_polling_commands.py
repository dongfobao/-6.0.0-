"""Modbus V9 固定轮询计划。

自动轮询只允许标准寄存器读命令。任意十六进制脚本不进入自动采集链路，避免误写设备。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from live_register_catalog import get_register_catalog, get_register_item


READ_FUNCTION_AREAS = {2: "discrete_input", 3: "holding_register", 4: "input_register"}

# 地址块按下位机 V9 映射显式定义，避免跨越保留区读取。
_DEFAULT_BLOCKS = (
    ("standard", 4, "input_register.system.protocol_version", 10, True, 250, "系统状态"),
    ("fast", 4, "input_register.sensor_1.temperature", 18, True, 120, "三路温湿度"),
    ("fast", 4, "input_register.pressure", 14, True, 120, "压力、流量与呼吸状态"),
    ("fast", 4, "input_register.heat_session_1.session_run_seconds", 36, True, 120, "加热会话、运行统计与阀门累计动作"),
    ("fast", 4, "input_register.output.htc1_state", 38, True, 120, "输出、累计运行与三路阀门"),
    ("standard", 4, "input_register.alarm.error_group_0", 6, True, 250, "告警状态"),
    ("standard", 4, "input_register.communication.online", 7, True, 250, "通信健康"),
    ("standard", 3, "holding.config.protocol_version", 5, True, 300, "配置事务状态"),
    ("fast", 3, "holding.runtime.remote_heat", 21, True, 300, "运行控制、阀门诊断与动作保护"),
    ("slow", 3, "holding.sensor_1.enabled", 63, False, 500, "三路温湿度配置"),
    ("slow", 3, "holding.sensor_1.threshold_confirm_interval_seconds", 12, False, 500, "三路阈值确认配置"),
    ("slow", 3, "holding.system.rtc_sync_epoch", 2, False, 500, "RTC 同步事务值"),
    ("slow", 3, "holding.sensor_1.humidity_peak_drop_threshold", 6, False, 500, "三路峰值回落配置"),
    ("slow", 3, "holding.pressure.enabled", 7, False, 500, "压力配置"),
    ("slow", 3, "holding.flow.enabled", 9, False, 500, "流量配置"),
    ("slow", 3, "holding.valve_1.enabled", 6, False, 500, "阀门设置"),
    ("slow", 3, "holding.dehumidification.enabled", 11, False, 500, "除湿配置"),
    ("slow", 3, "holding.antifreeze.enabled", 8, False, 500, "防冻配置"),
    ("slow", 3, "holding.sensor_fault.humidity_temperature_action", 3, False, 500, "传感器故障策略"),
    ("slow", 3, "holding.output.htc1_enabled", 8, False, 500, "输出配置"),
    ("slow", 3, "holding.alarm.master_enabled", 7, False, 500, "告警配置"),
    ("slow", 3, "holding.logging.sensor_enabled", 5, False, 500, "记录配置"),
    ("slow", 3, "holding.communication.slave_id", 4, False, 500, "通信配置"),
    ("slow", 3, "holding.schedule.selected_task", 29, False, 500, "定时任务配置"),
)


def _item_ids_for_block(catalog: list[dict[str, Any]], function_code: int, address: int, count: int) -> list[str]:
    area = READ_FUNCTION_AREAS[function_code]
    end_address = address + count - 1
    return [
        str(item["id"])
        for item in catalog
        if item.get("area") == area
        and int(item.get("address", -1)) >= address
        and int(item.get("addressEnd", -1)) <= end_address
    ]


def _request_template(function_code: int, address: int, count: int) -> str:
    return f"{{slaveId}} {function_code:02X} {address >> 8:02X} {address & 0xFF:02X} {count >> 8:02X} {count & 0xFF:02X}"


def build_default_polling_commands(catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    source_catalog = [dict(item) for item in (catalog or get_register_catalog())]
    commands: list[dict[str, Any]] = []
    for group, function_code, start_id, count, auto_poll, delay_ms, name in _DEFAULT_BLOCKS:
        # 慢速配置块也必须进入调度；sourceGroup 的间隔已经限制了总线负载。
        if group == "slow":
            auto_poll = True
        address = int(get_register_item(start_id)["address"])
        commands.append({
            "id": f"v9.{group}.fc{function_code}.{address}.{count}",
            "name": name,
            "mode": "modbus_read",
            "functionCode": function_code,
            "area": READ_FUNCTION_AREAS[function_code],
            "address": address,
            "count": count,
            "requestHex": _request_template(function_code, address, count),
            "appendCrc": True,
            "expectResponse": True,
            "responseMode": "modbus",
            "responseTimeoutMs": None,
            "autoPoll": auto_poll,
            "delayAfterMs": delay_ms,
            "sourceGroup": group,
            "decodeMode": "catalog",
            "catalogItemIds": _item_ids_for_block(source_catalog, function_code, address, count),
        })
    return commands


def normalize_polling_commands(commands: Any, catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """校验用户保存的轮询计划；非法或非 V9 计划直接替换为默认计划。"""
    defaults = build_default_polling_commands(catalog)
    if not isinstance(commands, list) or len(commands) != len(defaults):
        return defaults

    # 轮询块是 V9 协议的一部分：只接受点表明确声明的完整固定集合，
    # 不允许借设备配置插入对保留地址或未定义区域的任意读请求。
    expected_blocks = {
        (int(item["functionCode"]), int(item["address"]), int(item["count"]))
        for item in defaults
    }
    provided_blocks: set[tuple[int, int, int]] = set()
    for command in commands:
        if not isinstance(command, dict):
            return defaults
        try:
            block = (
                int(command.get("functionCode")),
                int(command.get("address")),
                int(command.get("count")),
            )
        except (TypeError, ValueError):
            return defaults
        if block not in expected_blocks or block in provided_blocks:
            return defaults
        provided_blocks.add(block)
    if provided_blocks != expected_blocks:
        return defaults

    # 地址块、顺序、点 ID、自动轮询标志和延时都属于协议定义，不接受设备档案覆盖。
    # 只把传入列表当作“是否仍是完整 V9 固定块集合”的兼容性校验，实际始终返回点表生成值。
    return deepcopy(defaults)


def _optional_timeout(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return max(50, int(value))
    except (TypeError, ValueError):
        return None
