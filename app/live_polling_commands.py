"""Modbus V7 固定轮询计划。

自动轮询只允许标准寄存器读命令。任意十六进制脚本不进入自动采集链路，避免误写设备。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from live_register_catalog import get_register_catalog


READ_FUNCTION_AREAS = {2: "discrete_input", 3: "holding_register", 4: "input_register"}

# 地址块按下位机 V7 映射显式定义，避免跨越保留区读取。
_DEFAULT_BLOCKS = (
    ("standard", 4, 0, 10, True, 250, "系统状态与主显示温湿度"),
    ("fast", 4, 100, 18, True, 120, "三路温湿度"),
    ("fast", 4, 200, 14, True, 120, "压力、流量与呼吸状态"),
    ("fast", 4, 300, 38, True, 120, "输出、累计运行与三路阀门"),
    ("standard", 4, 400, 6, True, 250, "告警状态"),
    ("standard", 4, 500, 7, True, 250, "通信健康"),
    ("standard", 3, 0, 5, True, 300, "配置事务状态"),
    ("standard", 3, 800, 17, True, 300, "运行控制与阀门诊断"),
    ("slow", 3, 100, 63, False, 500, "三路温湿度配置"),
    ("slow", 3, 200, 7, False, 500, "压力配置"),
    ("slow", 3, 220, 9, False, 500, "流量配置"),
    ("slow", 3, 300, 16, False, 500, "阀门配置"),
    ("slow", 3, 400, 12, False, 500, "控制配置"),
    ("slow", 3, 500, 27, False, 500, "输出与告警配置"),
    ("slow", 3, 600, 5, False, 500, "记录配置"),
    ("slow", 3, 700, 4, False, 500, "通信配置"),
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
    for group, function_code, address, count, auto_poll, delay_ms, name in _DEFAULT_BLOCKS:
        commands.append({
            "id": f"v7.{group}.fc{function_code}.{address}.{count}",
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
    """校验用户保存的轮询计划；非法或旧协议计划直接替换为 V7 默认计划。"""
    defaults = build_default_polling_commands(catalog)
    if not isinstance(commands, list) or not commands:
        return defaults

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, command in enumerate(commands):
        if not isinstance(command, dict) or str(command.get("mode") or "modbus_read") != "modbus_read":
            return defaults
        try:
            function_code = int(command.get("functionCode"))
            address = int(command.get("address"))
            count = int(command.get("count"))
        except (TypeError, ValueError):
            return defaults
        if function_code not in READ_FUNCTION_AREAS or address < 0 or not 1 <= count <= 125:
            return defaults
        command_id = str(command.get("id") or f"v7.custom.{index + 1}").strip()
        if not command_id or command_id in seen:
            return defaults
        seen.add(command_id)
        normalized.append({
            "id": command_id,
            "name": str(command.get("name") or f"FC{function_code:02d} {address}×{count}"),
            "mode": "modbus_read",
            "functionCode": function_code,
            "area": READ_FUNCTION_AREAS[function_code],
            "address": address,
            "count": count,
            "requestHex": _request_template(function_code, address, count),
            "appendCrc": True,
            "expectResponse": True,
            "responseMode": "modbus",
            "responseTimeoutMs": _optional_timeout(command.get("responseTimeoutMs")),
            "autoPoll": bool(command.get("autoPoll", True)),
            "delayAfterMs": max(0, int(command.get("delayAfterMs") or 200)),
            "sourceGroup": str(command.get("sourceGroup") or "custom"),
            "decodeMode": "catalog",
            "catalogItemIds": [str(value) for value in command.get("catalogItemIds", []) if str(value)],
        })
    return normalized or deepcopy(defaults)


def _optional_timeout(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return max(50, int(value))
    except (TypeError, ValueError):
        return None
