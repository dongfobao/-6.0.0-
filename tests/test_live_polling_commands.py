from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_device_store import _normalize_device_payload
from live_polling_commands import build_default_polling_commands, normalize_polling_commands


class LivePollingCommandsTests(unittest.TestCase):
    def test_default_automatic_plan_matches_v7_address_blocks(self) -> None:
        commands = build_default_polling_commands()
        automatic = {(item["functionCode"], item["address"], item["count"]) for item in commands if item["autoPoll"]}
        self.assertEqual(automatic, {
            (4, 100, 18), (4, 200, 14), (4, 300, 38),
            (4, 0, 10), (4, 400, 6), (4, 500, 7),
            (3, 0, 5), (3, 800, 17),
        })
        self.assertTrue(all(item["functionCode"] in {2, 3, 4} for item in commands))
        self.assertTrue(all(item["mode"] == "modbus_read" for item in commands))

    def test_configuration_blocks_are_manual_refresh_only(self) -> None:
        commands = build_default_polling_commands()
        config_commands = [item for item in commands if item["sourceGroup"] == "slow"]
        self.assertEqual({item["address"] for item in config_commands}, {100, 200, 220, 300, 400, 500, 600, 700})
        self.assertTrue(all(not item["autoPoll"] for item in config_commands))

    def test_old_or_raw_plan_is_rejected_instead_of_migrated(self) -> None:
        commands = normalize_polling_commands([{
            "id": "old.coils", "mode": "modbus_read", "functionCode": 1,
            "address": 0, "count": 11,
        }])
        self.assertTrue(all(item["id"].startswith("v7.") for item in commands))
        raw_commands = normalize_polling_commands([{
            "id": "raw", "mode": "raw_hex", "requestHex": "01 03 00 00 00 01",
        }])
        self.assertTrue(all(item["id"].startswith("v7.") for item in raw_commands))

    def test_device_defaults_to_v7_profile(self) -> None:
        device = _normalize_device_payload({"name": "A", "address": "COM1", "slaveId": 1})
        self.assertEqual(device["deviceType"], "YLDQ-6.0-Modbus-V7")
        self.assertTrue(any(item["address"] == 100 and item["count"] == 18 for item in device["pollingCommands"]))
        self.assertFalse(any(item["functionCode"] == 1 for item in device["pollingCommands"]))


if __name__ == "__main__":
    unittest.main()
