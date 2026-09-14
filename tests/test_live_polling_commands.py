from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_device_store import _normalize_device_payload
from live_polling_commands import build_default_polling_commands, normalize_polling_commands


class LivePollingCommandsTests(unittest.TestCase):
    def test_automatic_plan_contains_mandatory_and_extended_v10_blocks(self) -> None:
        commands = build_default_polling_commands()
        automatic = {(item["functionCode"], item["address"], item["count"]) for item in commands if item["autoPoll"]}
        self.assertIn((2, 0, 20), automatic)
        self.assertIn((4, 0, 8), automatic)
        self.assertIn((4, 100, 37), automatic)
        self.assertIn((1, 16, 14), automatic)
        self.assertTrue(all(item["id"].startswith("v10.") for item in commands))

    def test_slow_plan_covers_coils_config_and_twelve_schedule_slots(self) -> None:
        commands = build_default_polling_commands()
        slow = [item for item in commands if item["sourceGroup"] == "slow"]
        self.assertTrue(all(not item["autoPoll"] for item in slow))
        blocks = {(x["functionCode"], x["address"], x["count"]) for x in slow}
        self.assertIn((1, 32, 41), blocks)
        self.assertIn((1, 96, 24), blocks)
        for task in range(12):
            self.assertIn((3, 512 + task * 32, 24), blocks)

    def test_non_v10_plan_is_replaced(self) -> None:
        normalized = normalize_polling_commands([{"id": "v9.old", "mode": "modbus_read", "functionCode": 3, "address": 1, "count": 1}])
        self.assertEqual(normalized, build_default_polling_commands())

    def test_device_defaults_to_v10_profile(self) -> None:
        device = _normalize_device_payload({"name": "A", "address": "COM1", "slaveId": 1})
        self.assertEqual(device["deviceType"], "YLDQ-6.0-Modbus-V10")
        self.assertTrue(any(item["functionCode"] == 1 for item in device["pollingCommands"]))


if __name__ == "__main__":
    unittest.main()
