from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_register_catalog import PROTOCOL_VERSION_WORD, get_register_catalog, get_register_catalog_summary


class LiveRegisterCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = get_register_catalog()
        self.by_id = {item["id"]: item for item in self.catalog}

    def test_catalog_is_v7_only_and_has_unique_points(self) -> None:
        self.assertEqual(PROTOCOL_VERSION_WORD, 0x0700)
        self.assertEqual(len(self.catalog), len(self.by_id))
        self.assertFalse(any(item["area"] == "coil" for item in self.catalog))
        self.assertFalse(any(1 in item["functionCode"] or 5 in item["functionCode"] for item in self.catalog))
        self.assertEqual(get_register_catalog_summary()["protocolVersion"], "7.0")

    def test_three_temperature_humidity_channels_match_firmware_map(self) -> None:
        for channel, base in enumerate((100, 106, 112), start=1):
            prefix = f"input_register.sensor_{channel}"
            self.assertEqual(self.by_id[f"{prefix}.temperature"]["address"], base)
            self.assertEqual(self.by_id[f"{prefix}.humidity"]["address"], base + 2)
            self.assertEqual(self.by_id[f"{prefix}.status"]["address"], base + 4)
            self.assertEqual(self.by_id[f"{prefix}.read_ok"]["address"], base + 5)

    def test_three_valves_expose_full_work_state(self) -> None:
        for channel, base in enumerate((320, 326, 332), start=1):
            prefix = f"input_register.valve_{channel}"
            self.assertEqual(self.by_id[f"{prefix}.display_state"]["address"], base)
            self.assertEqual(self.by_id[f"{prefix}.actuator_state"]["address"], base + 1)
            self.assertEqual(self.by_id[f"{prefix}.position"]["address"], base + 2)
            self.assertEqual(self.by_id[f"{prefix}.fault_reason"]["address"], base + 3)
            self.assertEqual(self.by_id[f"{prefix}.current_adc"]["address"], base + 4)
            self.assertEqual(self.by_id[f"{prefix}.control_source"]["address"], base + 5)

    def test_multiword_values_follow_big_endian_word_lengths(self) -> None:
        self.assertNotIn("input_register.temperature", self.by_id)
        self.assertNotIn("input_register.humidity", self.by_id)
        self.assertEqual(self.by_id["input_register.output.htc1_open_count"]["address"], 308)
        self.assertEqual(self.by_id["input_register.output.htc1_open_count"]["wordLength"], 4)
        self.assertEqual(self.by_id["input_register.communication.failure_count"]["wordLength"], 2)

    def test_config_and_runtime_regions_are_separate(self) -> None:
        self.assertEqual(self.by_id["holding.config.command"]["address"], 3)
        self.assertEqual(self.by_id["holding.config.generation"]["address"], 2)
        self.assertEqual(self.by_id["holding.config.error"]["address"], 4)
        self.assertEqual(self.by_id["holding.runtime.remote_heat"]["address"], 800)
        self.assertEqual(self.by_id["holding.runtime.valve_3"]["address"], 806)
        self.assertFalse(self.by_id["holding.runtime.valve_1_diagnostic_fault"]["writable"])

    def test_configuration_field_offsets_match_v7_document(self) -> None:
        self.assertEqual(self.by_id["holding.sensor_1.online"]["address"], 100)
        self.assertEqual(self.by_id["holding.sensor_1.temperature_offset"]["address"], 103)
        self.assertEqual(self.by_id["holding.sensor_3.humidity_alarm_enabled"]["address"], 162)
        self.assertEqual(self.by_id["holding.pressure.offset"]["address"], 201)
        self.assertEqual(self.by_id["holding.flow.no_change_alarm_days"]["address"], 227)
        self.assertEqual(self.by_id["holding.flow.no_change_alarm_days"]["unit"], "天")
        self.assertEqual(self.by_id["holding.flow.no_change_alarm_days"]["maximum"], 365)
        self.assertEqual(self.by_id["holding.flow.no_change_alarm_days"]["configKey"], "sensors.flow.noChangeAlarmDays")
        self.assertEqual(self.by_id["holding.valve_route.restart_protection_days"]["wordLength"], 2)
        self.assertEqual(self.by_id["holding.valve_route.mode"]["configKey"], "control.valveRouting.mode")
        self.assertEqual(self.by_id["holding.valve_route.restart_protection_days"]["unit"], "天")
        self.assertEqual(self.by_id["holding.valve_route.force_close_days"]["unit"], "天")
        self.assertEqual(self.by_id["holding.valve_route.cooling_delay_hours"]["address"], 306)
        self.assertEqual(self.by_id["holding.valve_route.cooling_delay_hours"]["addressEnd"], 307)
        self.assertEqual(self.by_id["holding.valve_route.cooling_delay_hours"]["unit"], "小时")
        self.assertEqual(self.by_id["holding.valve_route.cooling_delay_hours"]["maximum"], 8760)
        self.assertEqual(self.by_id["holding.control.close_delay_hours"]["unit"], "小时")
        self.assertEqual(self.by_id["holding.control.close_delay_hours"]["configKey"], "control.antifreeze.closeDelayHours")
        self.assertNotIn("holding.flow.no_change_alarm_seconds", self.by_id)
        self.assertNotIn("holding.valve_route.force_close_seconds", self.by_id)
        self.assertEqual(self.by_id["holding.communication.baudrate"]["addressEnd"], 702)


if __name__ == "__main__":
    unittest.main()
