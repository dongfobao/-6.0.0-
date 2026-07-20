from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_device_store import _normalize_device_payload
from live_polling_commands import build_default_polling_commands, normalize_polling_commands


class LivePollingCommandsTests(unittest.TestCase):
    def test_default_commands_include_parameter_commands_without_auto_poll(self) -> None:
        commands = build_default_polling_commands()

        self.assertGreaterEqual(len(commands), 8)
        self.assertTrue(any(item["sourceGroup"] == "slow" for item in commands))
        self.assertTrue(all(item["autoPoll"] for item in commands if item["sourceGroup"] != "slow"))
        self.assertTrue(all(not item["autoPoll"] for item in commands if item["sourceGroup"] == "slow"))
        self.assertTrue(any(item["functionCode"] == 3 and item["address"] == 0 and item["count"] == 28 for item in commands))
        self.assertTrue(any(item["functionCode"] == 3 and item["address"] == 30 and item["count"] == 123 for item in commands))
        self.assertTrue(any(item["name"] == "总加热状态" for item in commands))
        self.assertTrue(any("呼气状态、吸气状态、通道一加热状态" in item["name"] for item in commands))

    def test_device_normalization_adds_default_command_table(self) -> None:
        device = _normalize_device_payload({"name": "A", "address": "COM1", "slaveId": 1})

        self.assertIn("pollingCommands", device)
        self.assertTrue(any(item["sourceGroup"] == "slow" and not item["autoPoll"] for item in device["pollingCommands"]))
        self.assertTrue(any(item["functionCode"] == 1 and item["address"] == 0 and item["count"] == 11 for item in device["pollingCommands"]))
        self.assertTrue(any(item["functionCode"] == 3 and item["address"] == 0 and item["count"] == 28 for item in device["pollingCommands"]))

    def test_device_normalization_refreshes_legacy_generated_default_commands(self) -> None:
        device = _normalize_device_payload(
            {
                "name": "A",
                "address": "COM1",
                "slaveId": 1,
                "pollingProfile": "default-yldq",
                "pollingCommands": [
                    {
                        "id": "default.slow.fc1.0.10",
                        "name": "old coils",
                        "mode": "modbus_read",
                        "functionCode": 1,
                        "area": "coil",
                        "address": 0,
                        "count": 10,
                        "catalogItemIds": ["coil.drain_online", "coil.cht_online"],
                    },
                    {
                        "id": "default.slow.fc3.0.10",
                        "name": "old holding",
                        "mode": "modbus_read",
                        "functionCode": 3,
                        "area": "holding_register",
                        "address": 0,
                        "count": 10,
                    },
                ],
            }
        )

        self.assertTrue(any(item["functionCode"] == 1 and item["address"] == 0 and item["count"] == 11 for item in device["pollingCommands"]))
        self.assertTrue(any(item["functionCode"] == 3 and item["address"] == 0 and item["count"] == 28 for item in device["pollingCommands"]))
        catalog_ids = {
            item_id
            for command in device["pollingCommands"]
            for item_id in command.get("catalogItemIds", [])
        }
        self.assertIn("coil.alarm_output_online", catalog_ids)
        self.assertIn("holding.exhale_timeout_min_sec", catalog_ids)
        self.assertIn("holding.no_change_alarm_time_sec", catalog_ids)
        self.assertIn("holding.exhale_timeout_sec", catalog_ids)
        self.assertIn("holding.heat_evidence_interval_sec", catalog_ids)
        self.assertIn("holding.heat_evidence_count", catalog_ids)
        self.assertIn("holding.humidity_offset", catalog_ids)
        self.assertIn("holding.respiratory_offset", catalog_ids)
        self.assertIn("holding.humidity_heat_evidence_interval_sec", catalog_ids)
        self.assertIn("holding.humidity_heat_evidence_count", catalog_ids)
        self.assertNotIn("coil.drain_online", catalog_ids)
        self.assertNotIn("coil.cht_online", catalog_ids)

    def test_normalize_command_accepts_raw_hex_script(self) -> None:
        commands = normalize_polling_commands([
            {
                "id": "custom-read",
                "name": "custom",
                "mode": "raw_hex",
                "requestHex": "{slaveId} 03 00 00 00 01",
                "appendCrc": True,
                "expectResponse": True,
                "autoPoll": True,
                "delayAfterMs": 250,
            }
        ])

        self.assertEqual(commands[0]["mode"], "raw_hex")
        self.assertEqual(commands[0]["requestHex"], "{slaveId} 03 00 00 00 01")
        self.assertTrue(commands[0]["autoPoll"])


if __name__ == "__main__":
    unittest.main()
