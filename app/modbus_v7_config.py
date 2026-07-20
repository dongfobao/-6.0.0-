"""V7 配置暂存、校验与提交事务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from live_register_catalog import PROTOCOL_VERSION_WORD
from modbus_v7_codec import encode_words


CONFIG_STATUS_ADDRESS = 0
CONFIG_STATUS_COUNT = 5
CONFIG_COMMAND_ADDRESS = 3
COMMAND_COMMIT = 0xC6A6
COMMAND_DISCARD = 0xD15C


class RegisterClient(Protocol):
    def read_holding_registers(self, address: int, count: int) -> list[int]: ...
    def write_single_register(self, address: int, value: int) -> None: ...
    def write_multiple_registers(self, address: int, values: list[int]) -> None: ...


class ConfigTransactionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfigStatus:
    protocol_word: int
    state: int
    generation: int
    command: int
    error: int

    @property
    def protocol_ok(self) -> bool:
        return self.protocol_word == PROTOCOL_VERSION_WORD


class V7ConfigTransaction:
    def __init__(self, client: RegisterClient) -> None:
        self.client = client

    def read_status(self) -> ConfigStatus:
        words = self.client.read_holding_registers(CONFIG_STATUS_ADDRESS, CONFIG_STATUS_COUNT)
        if len(words) != CONFIG_STATUS_COUNT:
            raise ConfigTransactionError("配置状态响应长度错误")
        status = ConfigStatus(*(int(word) & 0xFFFF for word in words))
        if not status.protocol_ok:
            raise ConfigTransactionError(
                f"协议版本不匹配: 期望 0x{PROTOCOL_VERSION_WORD:04X}, 实际 0x{status.protocol_word:04X}"
            )
        return status

    def stage_value(self, item: dict[str, Any], value: Any) -> list[int]:
        if item.get("area") != "holding_register" or not item.get("writable"):
            raise ConfigTransactionError(f"点不可写: {item.get('id')}")
        address = int(item["address"])
        if address < 100 or address >= 800:
            raise ConfigTransactionError("配置事务只允许写入 100-799 配置区")
        self._validate_value_range(item, value)
        words = encode_words(value, str(item["dataType"]))
        if len(words) == 1:
            self.client.write_single_register(address, words[0])
        else:
            self.client.write_multiple_registers(address, words)
        readback = self.client.read_holding_registers(address, len(words))
        if list(readback) != words:
            raise ConfigTransactionError(f"配置回读不一致: {item.get('id')}")
        return words

    @staticmethod
    def _validate_value_range(item: dict[str, Any], value: Any) -> None:
        minimum = item.get("minimum")
        maximum = item.get("maximum")
        if minimum is None and maximum is None:
            return
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise ConfigTransactionError(f"参数不是有效数字: {item.get('id')}") from exc
        unit = str(item.get("unit") or "")
        if minimum is not None and numeric_value < float(minimum):
            raise ConfigTransactionError(
                f"{item.get('name', item.get('id'))}不能小于 {minimum}{unit}"
            )
        if maximum is not None and numeric_value > float(maximum):
            raise ConfigTransactionError(
                f"{item.get('name', item.get('id'))}不能大于 {maximum}{unit}"
            )

    def commit(self) -> ConfigStatus:
        status = self._command(COMMAND_COMMIT)
        if status.error:
            raise ConfigTransactionError(f"配置提交失败，错误码: {status.error}")
        return status

    def discard(self) -> ConfigStatus:
        return self._command(COMMAND_DISCARD)

    def _command(self, command: int) -> ConfigStatus:
        self.client.write_single_register(CONFIG_COMMAND_ADDRESS, command)
        return self.read_status()
