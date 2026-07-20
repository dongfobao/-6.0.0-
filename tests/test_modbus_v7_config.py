from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from modbus_v7_config import COMMAND_COMMIT, COMMAND_DISCARD, ConfigTransactionError, V7ConfigTransaction


class FakeClient:
    def __init__(self) -> None:
        self.words = {0: 0x0700, 1: 1, 2: 9, 3: 0, 4: 0}
        self.writes: list[tuple[int, list[int]]] = []

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        return [self.words.get(address + offset, 0) for offset in range(count)]

    def write_single_register(self, address: int, value: int) -> None:
        self.write_multiple_registers(address, [value])

    def write_multiple_registers(self, address: int, values: list[int]) -> None:
        self.writes.append((address, list(values)))
        for offset, value in enumerate(values):
            self.words[address + offset] = value


class ModbusV7ConfigTests(unittest.TestCase):
    def test_stage_readback_and_commit(self) -> None:
        client = FakeClient()
        transaction = V7ConfigTransaction(client)
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
            V7ConfigTransaction(client).read_status()

    def test_runtime_control_cannot_enter_config_transaction(self) -> None:
        client = FakeClient()
        item = {"id": "holding.runtime.remote_heat", "area": "holding_register", "address": 800,
                "dataType": "bool", "writable": True}
        with self.assertRaises(ConfigTransactionError):
            V7ConfigTransaction(client).stage_value(item, True)


if __name__ == "__main__":
    unittest.main()
