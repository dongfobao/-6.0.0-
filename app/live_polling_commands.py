from __future__ import annotations

from copy import deepcopy
from typing import Any

from live_register_catalog import get_register_catalog


READ_FUNCTION_AREAS = {
    1: "coil",
    2: "discrete_input",
    3: "holding_register",
    4: "input_register",
}

DEFAULT_COMMAND_DELAY_MS = {
    "fast": 200,
    "standard": 500,
    "slow": 1000,
}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_blocks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_items = sorted(
        items,
        key=lambda item: (
            int(item.get("functionCode", [0])[0]),
            str(item.get("area") or ""),
            int(item.get("address") or 0),
        ),
    )
    blocks: list[dict[str, Any]] = []
    for item in sorted_items:
        function_code = int(item.get("functionCode", [0])[0])
        area = str(item.get("area") or "")
        item_start = int(item.get("address") or 0)
        item_end = int(item.get("addressEnd") or (item_start + int(item.get("wordLength") or 1) - 1))
        max_count = 2000 if function_code in {1, 2} else 125
        if not blocks or blocks[-1]["functionCode"] != function_code or blocks[-1]["area"] != area:
            blocks.append({
                "functionCode": function_code,
                "area": area,
                "address": item_start,
                "addressEnd": item_end,
                "count": item_end - item_start + 1,
                "items": [item],
            })
            continue
        last_block = blocks[-1]
        new_count = item_end - last_block["address"] + 1
        if item_start > last_block["addressEnd"] + 1 or new_count > max_count:
            blocks.append({
                "functionCode": function_code,
                "area": area,
                "address": item_start,
                "addressEnd": item_end,
                "count": item_end - item_start + 1,
                "items": [item],
            })
            continue
        last_block["addressEnd"] = max(last_block["addressEnd"], item_end)
        last_block["count"] = last_block["addressEnd"] - last_block["address"] + 1
        last_block["items"].append(item)
    return blocks


def build_default_polling_commands(catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    readable_items = [dict(item) for item in (catalog or get_register_catalog()) if item.get("readable")]
    commands: list[dict[str, Any]] = []
    for group_key in ("fast", "standard", "slow"):
        group_items = [item for item in readable_items if item.get("pollGroup") == group_key]
        for block in _build_blocks(group_items):
            command_id = f"default.{group_key}.fc{block['functionCode']}.{block['address']}.{block['count']}"
            commands.append({
                "id": command_id,
                "name": _default_command_name(group_key, block),
                "mode": "modbus_read",
                "functionCode": block["functionCode"],
                "area": block["area"],
                "address": block["address"],
                "count": block["count"],
                "requestHex": _modbus_request_template(block["functionCode"], block["address"], block["count"]),
                "appendCrc": True,
                "expectResponse": True,
                "responseMode": "modbus",
                "responseTimeoutMs": None,
                "autoPoll": group_key != "slow",
                "delayAfterMs": DEFAULT_COMMAND_DELAY_MS[group_key],
                "sourceGroup": group_key,
                "decodeMode": "catalog",
                "catalogItemIds": [str(item.get("id")) for item in block["items"] if item.get("id")],
            })
    return commands


def normalize_polling_commands(
    commands: Any,
    catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    default_commands = build_default_polling_commands(catalog)
    source = commands if isinstance(commands, list) and commands else default_commands
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, command in enumerate(source):
        if not isinstance(command, dict):
            continue
        mode = str(command.get("mode") or command.get("type") or "modbus_read").strip() or "modbus_read"
        if mode not in {"modbus_read", "raw_hex"}:
            continue
        function_code = _safe_int(command.get("functionCode"), 0)
        if mode == "modbus_read" and function_code not in READ_FUNCTION_AREAS:
            parsed = _parse_request_template(command.get("requestHex"))
            if parsed:
                function_code, address, count = parsed
            else:
                continue
        else:
            address = max(0, _safe_int(command.get("address"), 0))
            count = max(1, _safe_int(command.get("count"), 1))
        max_count = 2000 if function_code in {1, 2} else 125
        count = max(1, min(max_count, count))
        raw_id = str(command.get("id") or f"cmd-{index + 1}").strip() or f"cmd-{index + 1}"
        command_id = raw_id
        suffix = 2
        while command_id in seen_ids:
            command_id = f"{raw_id}-{suffix}"
            suffix += 1
        seen_ids.add(command_id)
        area = READ_FUNCTION_AREAS.get(function_code, str(command.get("area") or "raw"))
        request_hex = str(command.get("requestHex") or "").strip()
        if mode == "modbus_read" and not request_hex:
            request_hex = _modbus_request_template(function_code, address, count)
        normalized.append({
            "id": command_id,
            "name": str(command.get("name") or f"FC{function_code:02d} {address}x{count}").strip(),
            "mode": mode,
            "functionCode": function_code,
            "area": area,
            "address": address,
            "count": count,
            "requestHex": request_hex,
            "appendCrc": bool(command.get("appendCrc", True)),
            "expectResponse": bool(command.get("expectResponse", True)),
            "responseMode": str(command.get("responseMode") or ("modbus" if mode == "modbus_read" else "raw")).strip(),
            "responseTimeoutMs": _normalize_optional_timeout(command.get("responseTimeoutMs")),
            "autoPoll": bool(command.get("autoPoll", command.get("enabled", True))),
            "delayAfterMs": max(0, _safe_int(command.get("delayAfterMs"), 200)),
            "sourceGroup": str(command.get("sourceGroup") or "custom").strip() or "custom",
            "decodeMode": str(command.get("decodeMode") or ("catalog" if mode == "modbus_read" else "none")).strip(),
            "catalogItemIds": _normalize_catalog_item_ids(command.get("catalogItemIds")),
        })

    return normalized or deepcopy(default_commands)


def _normalize_catalog_item_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _default_command_name(group_key: str, block: dict[str, Any]) -> str:
    names = [str(item.get("name") or "").strip() for item in block.get("items", [])]
    joined_names = "、".join(name for name in names if name)
    if joined_names:
        return joined_names
    return f"FC{block['functionCode']:02d} 地址 {block['address']} 数量 {block['count']}"


def _modbus_request_template(function_code: int, address: int, count: int) -> str:
    return f"{{slaveId}} {function_code:02X} {address >> 8:02X} {address & 0xFF:02X} {count >> 8:02X} {count & 0xFF:02X}"


def _parse_request_template(value: Any) -> tuple[int, int, int] | None:
    text = str(value or "").replace("{slaveId}", "01").replace("{slave_id}", "01")
    cleaned = "".join(ch for ch in text if ch in "0123456789abcdefABCDEF")
    if len(cleaned) < 12:
        return None
    try:
        data = bytes.fromhex(cleaned[:12])
    except ValueError:
        return None
    function_code = data[1]
    if function_code not in READ_FUNCTION_AREAS:
        return None
    address = int.from_bytes(data[2:4], "big")
    count = int.from_bytes(data[4:6], "big")
    return function_code, address, count


def _normalize_optional_timeout(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return max(50, _safe_int(value, 1200))
