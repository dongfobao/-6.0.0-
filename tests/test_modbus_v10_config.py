from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_register_catalog import get_register_catalog
from modbus_v10_config import ConfigTransactionError, V10ConfigTransaction


class FakeClient:
    def __init__(self) -> None:
        self.protocol = 0x0A00
        self.generation = 7
        self.error = 0
        self.busy = False
        self.failed = False
        self.coils = {32: False}
        self.holding = {10: 30, 260: 0, 261: 86400}

    def read_input_registers(self, address, count):
        words = [0] * count
        words[0] = self.protocol
        if count >= 16:
            words[14], words[15] = self.generation, self.error
        return words

    def read_discrete_inputs(self, address, count): return [self.busy, self.failed]
    def read_coils(self, address, count): return [self.coils.get(address + i, False) for i in range(count)]
    def read_holding_registers(self, address, count): return [self.holding.get(address + i, 0) for i in range(count)]
    def _saved(self): self.generation += 1
    def write_single_coil(self, address, value): self.coils[address] = bool(value); self._saved()
    def write_multiple_coils(self, address, values):
        for i, value in enumerate(values): self.coils[address + i] = bool(value)
        self._saved()
    def write_single_register(self, address, value): self.holding[address] = int(value); self._saved()
    def write_multiple_registers(self, address, values):
        for i, value in enumerate(values): self.holding[address + i] = int(value)
        self._saved()


class ModbusV10ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.by_id = {item["id"]: item for item in get_register_catalog()}

    def test_status_reads_v10_protocol_and_save_flags(self) -> None:
        status = V10ConfigTransaction(FakeClient(), poll_interval_seconds=0).read_status()
        self.assertTrue(status.protocol_ok)
        self.assertEqual(status.generation, 7)
        self.assertEqual(status.state, 0x0005)

    def test_fc05_coil_and_fc06_register_are_saved_and_read_back(self) -> None:
        client = FakeClient()
        transaction = V10ConfigTransaction(client, poll_interval_seconds=0)
        self.assertEqual(transaction.stage_value(self.by_id["holding.dehumidification.enabled"], True), [True])
        self.assertEqual(transaction.stage_value(self.by_id["holding.logging.retention_days"], 60), [60])
        self.assertTrue(client.coils[32])
        self.assertEqual(client.holding[10], 60)
        self.assertEqual(client.generation, 9)

    def test_fc16_multiword_value_is_big_endian_and_saved(self) -> None:
        client = FakeClient()
        words = V10ConfigTransaction(client, poll_interval_seconds=0).stage_value(self.by_id["holding.dehumidification.cycle_interval_seconds"], 86400)
        self.assertEqual(words, [1, 20864])
        self.assertEqual([client.holding[260], client.holding[261]], words)

    def test_rejects_runtime_point_range_and_wrong_protocol(self) -> None:
        client = FakeClient()
        transaction = V10ConfigTransaction(client, poll_interval_seconds=0)
        with self.assertRaises(ConfigTransactionError): transaction.stage_value(self.by_id["holding.runtime.remote_heat"], True)
        with self.assertRaises(ConfigTransactionError): transaction.stage_value(self.by_id["holding.communication.slave_id"], 248)
        client.protocol = 0x0901
        with self.assertRaises(ConfigTransactionError): transaction.read_status()


if __name__ == "__main__":
    unittest.main()
