from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_device_store import _normalize_device_payload
from live_polling_commands import (
    build_default_polling_commands,
    normalize_polling_commands,
)


class LivePollingCommandsTests(unittest.TestCase):
    def test_default_automatic_plan_matches_v9_address_blocks(self) -> None:
        commands = build_default_polling_commands()
        automatic = {
            (item["functionCode"], item["address"], item["count"])
            for item in commands
            if item["autoPoll"]
        }
        self.assertEqual(
            automatic,
            {
                (4, 100, 18),
                (4, 200, 14),
                (4, 300, 38),
                (4, 0, 10),
                (4, 400, 6),
                (4, 500, 7),
                (3, 0, 5),
                (3, 800, 21),
            },
        )
        self.assertTrue(all(item["id"].startswith("v9.") for item in commands))
        guard_command = next(item for item in commands if item["address"] == 800)
        self.assertIn(
            "holding.runtime.valve_guard_reason",
            guard_command["catalogItemIds"],
        )

    def test_configuration_blocks_cover_all_v9_partitions(self) -> None:
        commands = build_default_polling_commands()
        config_commands = [
            item for item in commands if item["sourceGroup"] == "slow"
        ]
        self.assertEqual(
            {item["address"] for item in config_commands},
            {
                100,
                163,
                175,
                187,
                200,
                220,
                300,
                400,
                420,
                430,
                500,
                520,
                600,
                700,
                720,
            },
        )
        self.assertTrue(all(not item["autoPoll"] for item in config_commands))
        expected_counts = {
            187: 6,
            300: 6,
            400: 11,
            420: 8,
            430: 3,
            500: 8,
            520: 7,
            720: 29,
        }
        for address, count in expected_counts.items():
            command = next(
                item for item in config_commands if item["address"] == address
            )
            self.assertEqual(command["count"], count)
        dehumidification = next(
            item for item in config_commands if item["address"] == 400
        )
        self.assertIn(
            "holding.dehumidification.cycle_interval_days",
            dehumidification["catalogItemIds"],
        )
        self.assertIn(
            "holding.dehumidification.force_close_hours",
            dehumidification["catalogItemIds"],
        )
        schedule = next(item for item in config_commands if item["address"] == 720)
        self.assertIn(
            "holding.schedule.humidity_peak_drop_threshold_3",
            schedule["catalogItemIds"],
        )

    def test_non_v9_or_raw_plan_is_replaced(self) -> None:
        old_commands = build_default_polling_commands()
        old_commands[0]["id"] = "v7.standard.fc4.0.10"
        normalized = normalize_polling_commands(old_commands)
        self.assertTrue(all(item["id"].startswith("v9.") for item in normalized))

        raw_commands = normalize_polling_commands(
            [
                {
                    "id": "raw",
                    "mode": "raw_hex",
                    "requestHex": "01 03 00 00 00 01",
                }
            ]
        )
        self.assertTrue(all(item["id"].startswith("v9.") for item in raw_commands))

    def test_device_defaults_to_v9_profile(self) -> None:
        device = _normalize_device_payload(
            {"name": "A", "address": "COM1", "slaveId": 1}
        )
        self.assertEqual(device["deviceType"], "YLDQ-6.0-Modbus-V9")
        self.assertTrue(
            any(
                item["address"] == 400 and item["count"] == 11
                for item in device["pollingCommands"]
            )
        )
        self.assertFalse(
            any(item["functionCode"] == 1 for item in device["pollingCommands"])
        )


if __name__ == "__main__":
    unittest.main()
