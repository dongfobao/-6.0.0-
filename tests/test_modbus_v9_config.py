from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from modbus_v9_config import (
    COMMAND_COMMIT,
    COMMAND_DISCARD,
    ERROR_SAVE_PENDING,
    ConfigTransactionError,
    V9ConfigTransaction,
)


class FakeClient:
    def __init__(self) -> None:
        self.words = {0: 0x0900, 1: 1, 2: 9, 3: 0, 4: 0}
        self.writes: list[tuple[int, list[int]]] = []

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        return [self.words.get(address + offset, 0) for offset in range(count)]

    def write_single_register(self, address: int, value: int) -> None:
        self.write_multiple_registers(address, [value])

    def write_multiple_registers(self, address: int, values: list[int]) -> None:
        self.writes.append((address, list(values)))
        for offset, value in enumerate(values):
            self.words[address + offset] = value
        if address == 3 and values == [COMMAND_COMMIT]:
            self.words[1] = 0x0005
            self.words[2] += 1
            self.words[3] = 0


class ModbusV9ConfigTests(unittest.TestCase):
    def test_stage_readback_and_commit(self) -> None:
        client = FakeClient()
        transaction = V9ConfigTransaction(client)
        item = {"id": "holding.test", "area": "holding_register", "address": 100,
                "dataType": "float32", "writable": True}
        words = transaction.stage_value(item, 12.5)
        self.assertEqual(client.read_holding_registers(100, 2), words)
        transaction.commit()
        self.assertEqual(client.writes[-1], (3, [COMMAND_COMMIT]))
        self.assertEqual(COMMAND_COMMIT, 0xC6A6)
        self.assertEqual(COMMAND_DISCARD, 0xD15C)

    def test_protocol_mismatch_is_rejected(self) -> None:
        client = FakeClient()
        client.words[0] = 0x0600
        with self.assertRaises(ConfigTransactionError):
            V9ConfigTransaction(client).read_status()

    def test_runtime_control_cannot_enter_config_transaction(self) -> None:
        client = FakeClient()
        item = {"id": "holding.runtime.remote_heat", "area": "holding_register", "address": 800,
                "dataType": "bool", "writable": True}
        with self.assertRaises(ConfigTransactionError):
            V9ConfigTransaction(client).stage_value(item, True)

    def test_new_time_unit_range_is_enforced_before_write(self) -> None:
        client = FakeClient()
        item = {
            "id": "holding.dehumidification.post_heating_cooling_hours",
            "name": "停热后设备冷却时间",
            "area": "holding_register",
            "address": 404,
            "dataType": "uint32",
            "unit": "小时",
            "minimum": 0,
            "maximum": 8760,
            "writable": True,
        }
        with self.assertRaisesRegex(ConfigTransactionError, "不能大于 8760小时"):
            V9ConfigTransaction(client).stage_value(item, 8761)
        self.assertEqual(client.writes, [])

        words = V9ConfigTransaction(client).stage_value(item, 24)
        self.assertEqual(client.read_holding_registers(404, 2), words)

    def test_commit_waits_for_persistence_failure(self) -> None:
        client = FakeClient()
        original_write = client.write_single_register

        def fail_commit(address: int, value: int) -> None:
            original_write(address, value)
            if address == 3 and value == COMMAND_COMMIT:
                client.words[1] = 0x0003
                client.words[2] = 9
                client.words[4] = 3

        client.write_single_register = fail_commit  # type: ignore[method-assign]
        transaction = V9ConfigTransaction(
            client, commit_timeout_seconds=0.1, poll_interval_seconds=0
        )
        with self.assertRaisesRegex(ConfigTransactionError, "错误码: 3"):
            transaction.commit()

    def test_commit_waits_while_save_is_pending(self) -> None:
        class PendingClient(FakeClient):
            def __init__(self) -> None:
                super().__init__()
                self.commit_started = False
                self.pending_status_reads = 0

            def write_multiple_registers(self, address: int, values: list[int]) -> None:
                self.writes.append((address, list(values)))
                for offset, value in enumerate(values):
                    self.words[address + offset] = value
                if address == 3 and values == [COMMAND_COMMIT]:
                    self.commit_started = True
                    self.words[1] = 0x0003
                    self.words[3] = 0
                    self.words[4] = ERROR_SAVE_PENDING

            def read_holding_registers(self, address: int, count: int) -> list[int]:
                result = super().read_holding_registers(address, count)
                if (
                    self.commit_started
                    and address == 0
                    and count == 5
                    and self.words[4] == ERROR_SAVE_PENDING
                ):
                    self.pending_status_reads += 1
                    self.words[1] = 0x0005
                    self.words[2] += 1
                    self.words[4] = 0
                return result

        client = PendingClient()
        status = V9ConfigTransaction(
            client, commit_timeout_seconds=0.1, poll_interval_seconds=0
        ).commit()

        self.assertEqual(client.pending_status_reads, 1)
        self.assertEqual(status.error, 0)
        self.assertEqual(status.generation, 10)
        self.assertTrue(status.state & 0x0004)

    def test_baudrate_rejects_nonstandard_value(self) -> None:
        client = FakeClient()
        item = {
            "id": "holding.communication.baudrate",
            "name": "通信波特率",
            "area": "holding_register",
            "address": 701,
            "dataType": "uint32",
            "unit": "bit/s",
            "allowedValues": [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200],
            "writable": True,
        }
        with self.assertRaisesRegex(ConfigTransactionError, "只支持"):
            V9ConfigTransaction(client).stage_value(item, 12345)


if __name__ == "__main__":
    unittest.main()
