"""V10配置写入与持久化确认。V10无暂存区，每次合法写入立即提交保存。"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Protocol

from live_register_catalog import PROTOCOL_VERSION_WORD
from modbus_v10_codec import encode_words

ERROR_SAVE_PENDING = 5
ERROR_DESCRIPTIONS = {1: "配置加载失败", 2: "配置校验失败", 3: "配置持久化失败", 4: "运行命令失败", 5: "配置仍在保存中"}


class RegisterClient(Protocol):
    def read_discrete_inputs(self, address: int, count: int) -> list[bool]: ...
    def read_coils(self, address: int, count: int) -> list[bool]: ...
    def read_holding_registers(self, address: int, count: int) -> list[int]: ...
    def read_input_registers(self, address: int, count: int) -> list[int]: ...
    def write_single_coil(self, address: int, value: bool | int) -> None: ...
    def write_multiple_coils(self, address: int, values: list[bool | int]) -> None: ...
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


class V10ConfigTransaction:
    def __init__(self, client: RegisterClient, *, commit_timeout_seconds: float = 20.0, poll_interval_seconds: float = 0.1) -> None:
        self.client = client
        self.commit_timeout_seconds = max(0.1, float(commit_timeout_seconds))
        self.poll_interval_seconds = max(0.0, float(poll_interval_seconds))

    def read_status(self) -> ConfigStatus:
        words = self.client.read_input_registers(100, 16)
        if len(words) != 16:
            raise ConfigTransactionError("V10状态响应长度错误")
        protocol, generation, error = int(words[0]), int(words[14]), int(words[15])
        save_busy, save_failed = self.client.read_discrete_inputs(49, 2)
        if protocol != PROTOCOL_VERSION_WORD:
            raise ConfigTransactionError(f"协议版本不匹配: 期望0x{PROTOCOL_VERSION_WORD:04X}，实际0x{protocol:04X}")
        state = 0x0001 | (0x0002 if save_busy else 0) | (0x0004 if not save_busy and not save_failed and error == 0 else 0)
        return ConfigStatus(protocol, state, generation, 0, error if error else (3 if save_failed else 0))

    def stage_value(self, item: dict[str, Any], value: Any) -> list[int | bool]:
        if item.get("area") not in {"coil", "holding_register"} or not item.get("writable"):
            raise ConfigTransactionError(f"点不可写: {item.get('id')}")
        if item.get("group") == "runtime_control" or item.get("group") == "time_sync":
            raise ConfigTransactionError("该点不是持久化配置")
        self._validate_value_range(item, value)
        before = self.read_status()
        address = int(item["address"])
        area = str(item["area"])
        if area == "coil":
            bits = [bool(value)]
            self.client.write_single_coil(address, bits[0])
            readback = self.client.read_coils(address, 1)
            if list(readback) != bits:
                raise ConfigTransactionError(f"配置回读不一致: {item.get('id')}")
            wire: list[int | bool] = bits
        else:
            words = encode_words(value, str(item["dataType"]))
            if len(words) == 1: self.client.write_single_register(address, words[0])
            else: self.client.write_multiple_registers(address, words)
            if self.client.read_holding_registers(address, len(words)) != words:
                raise ConfigTransactionError(f"配置回读不一致: {item.get('id')}")
            wire = words
        # 固件对相同配置做幂等处理，不重复擦写存储，此时代次保持不变。
        self._wait_for_save(before.generation, allow_unchanged=True)
        return wire

    def commit(self) -> ConfigStatus:
        return self._wait_for_save(None)

    def discard(self) -> ConfigStatus:
        # V10不存在暂存区；界面的取消只放弃尚未发送的本地编辑。
        return self.read_status()

    def _wait_for_save(self, previous_generation: int | None, *, allow_unchanged: bool = False) -> ConfigStatus:
        deadline = time.monotonic() + self.commit_timeout_seconds
        while True:
            status = self.read_status()
            if status.error not in {0, ERROR_SAVE_PENDING}:
                raise ConfigTransactionError(self._error_message(status.error))
            if not (status.state & 0x0002) and (
                previous_generation is None
                or status.generation != previous_generation
                or allow_unchanged
            ):
                return status
            if time.monotonic() >= deadline:
                raise ConfigTransactionError("配置保存超时，未收到DI49清零和配置代次更新")
            time.sleep(self.poll_interval_seconds)

    @staticmethod
    def _validate_value_range(item: dict[str, Any], value: Any) -> None:
        minimum, maximum, allowed = item.get("minimum"), item.get("maximum"), item.get("allowedValues")
        if minimum is None and maximum is None and not allowed: return
        try: number = float(value)
        except (TypeError, ValueError) as exc: raise ConfigTransactionError(f"参数不是有效数字: {item.get('id')}") from exc
        unit = str(item.get("unit") or "")
        if allowed and number not in {float(x) for x in allowed}:
            raise ConfigTransactionError(f"{item.get('name', item.get('id'))}只支持: {'、'.join(str(x) for x in allowed)}{unit}")
        if minimum is not None and number < float(minimum): raise ConfigTransactionError(f"{item.get('name', item.get('id'))}不能小于 {minimum}{unit}")
        if maximum is not None and number > float(maximum): raise ConfigTransactionError(f"{item.get('name', item.get('id'))}不能大于 {maximum}{unit}")

    @staticmethod
    def _error_message(error: int) -> str:
        return f"配置保存失败，错误码: {int(error)}（{ERROR_DESCRIPTIONS.get(int(error), '未知错误')}）"
