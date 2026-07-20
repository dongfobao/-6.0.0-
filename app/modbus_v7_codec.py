"""YLDQ Modbus V7 大端寄存器编解码。"""

from __future__ import annotations

import math
import struct
from typing import Any, Iterable


class V7CodecError(ValueError):
    pass


def decode_words(words: Iterable[int], data_type: str) -> Any:
    values = [int(word) & 0xFFFF for word in words]
    required = {"bool": 1, "uint16": 1, "int16": 1, "enum16": 1, "bitfield16": 1,
                "uint32": 2, "int32": 2, "float32": 2, "uint64": 4}.get(data_type)
    if required is None:
        raise V7CodecError(f"不支持的数据类型: {data_type}")
    if len(values) != required:
        raise V7CodecError(f"{data_type} 需要 {required} 个寄存器，实际 {len(values)}")
    payload = struct.pack(f">{len(values)}H", *values)
    if data_type == "bool":
        return bool(values[0])
    if data_type in {"uint16", "enum16", "bitfield16"}:
        return values[0]
    if data_type == "int16":
        return struct.unpack(">h", payload)[0]
    if data_type == "uint32":
        return struct.unpack(">I", payload)[0]
    if data_type == "int32":
        return struct.unpack(">i", payload)[0]
    if data_type == "float32":
        return struct.unpack(">f", payload)[0]
    return struct.unpack(">Q", payload)[0]


def encode_words(value: Any, data_type: str) -> list[int]:
    try:
        if data_type == "bool":
            payload = struct.pack(">H", 1 if _as_bool(value) else 0)
        elif data_type in {"uint16", "enum16", "bitfield16"}:
            payload = struct.pack(">H", _bounded_int(value, 0, 0xFFFF))
        elif data_type == "int16":
            payload = struct.pack(">h", _bounded_int(value, -0x8000, 0x7FFF))
        elif data_type == "uint32":
            payload = struct.pack(">I", _bounded_int(value, 0, 0xFFFFFFFF))
        elif data_type == "int32":
            payload = struct.pack(">i", _bounded_int(value, -0x80000000, 0x7FFFFFFF))
        elif data_type == "uint64":
            payload = struct.pack(">Q", _bounded_int(value, 0, 0xFFFFFFFFFFFFFFFF))
        elif data_type == "float32":
            number = float(value)
            if not math.isfinite(number):
                raise V7CodecError("浮点值必须是有限数")
            payload = struct.pack(">f", number)
        else:
            raise V7CodecError(f"不支持的数据类型: {data_type}")
    except (TypeError, ValueError, struct.error) as exc:
        if isinstance(exc, V7CodecError):
            raise
        raise V7CodecError(f"无法编码 {data_type}: {value!r}") from exc
    return list(struct.unpack(f">{len(payload) // 2}H", payload))


def decode_catalog_item(item: dict[str, Any], block_address: int, words: list[int]) -> Any:
    offset = int(item["address"]) - int(block_address)
    length = int(item["wordLength"])
    if offset < 0 or offset + length > len(words):
        raise V7CodecError(f"点 {item['id']} 不在当前数据块内")
    return decode_words(words[offset: offset + length], str(item["dataType"]))


def _bounded_int(value: Any, minimum: int, maximum: int) -> int:
    number = int(value)
    if not minimum <= number <= maximum:
        raise V7CodecError(f"整数超出范围 [{minimum}, {maximum}]: {number}")
    return number


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "yes", "是", "开"}:
            return True
        if normalized in {"0", "false", "off", "no", "否", "关"}:
            return False
        raise V7CodecError(f"无法识别布尔值: {value}")
    return bool(value)
