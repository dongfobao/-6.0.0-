from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_register_catalog import (
    PROTOCOL_VERSION_WORD,
    get_register_catalog,
    get_register_catalog_summary,
)


class LiveRegisterCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = get_register_catalog()
        self.by_id = {item["id"]: item for item in self.catalog}

    def test_catalog_is_v9_only_and_has_unique_points(self) -> None:
        self.assertEqual(PROTOCOL_VERSION_WORD, 0x0900)
        self.assertEqual(len(self.catalog), len(self.by_id))
        self.assertEqual(get_register_catalog_summary()["protocolVersion"], "9.0")
        self.assertTrue(
            all(item["sourceOfTruth"] == "firmware-v9" for item in self.catalog)
        )
        self.assertFalse(any("valve_route" in item["id"] for item in self.catalog))
        self.assertFalse(any("humidity_control_" in item["id"] for item in self.catalog))

    def test_input_registers_match_firmware_map(self) -> None:
        self.assertEqual(
            (self.by_id["input_register.system.display_temperature"]["address"],
             self.by_id["input_register.system.display_temperature"]["addressEnd"]),
            (6, 7),
        )
        self.assertEqual(
            (self.by_id["input_register.system.display_humidity"]["address"],
             self.by_id["input_register.system.display_humidity"]["addressEnd"]),
            (8, 9),
        )
        for channel, base in enumerate((100, 106, 112), start=1):
            prefix = f"input_register.sensor_{channel}"
            self.assertEqual(self.by_id[f"{prefix}.temperature"]["address"], base)
            self.assertEqual(self.by_id[f"{prefix}.humidity"]["address"], base + 2)
            self.assertEqual(self.by_id[f"{prefix}.status"]["address"], base + 4)
            self.assertEqual(self.by_id[f"{prefix}.read_ok"]["address"], base + 5)
        for channel, base in enumerate((320, 326, 332), start=1):
            prefix = f"input_register.valve_{channel}"
            self.assertEqual(self.by_id[f"{prefix}.display_state"]["address"], base)
            self.assertEqual(self.by_id[f"{prefix}.control_source"]["address"], base + 5)
            self.assertEqual(
                self.by_id[f"{prefix}.actuator_state"]["enumValues"],
                {0: "空闲", 1: "运动中", 2: "故障", 3: "禁用", 65535: "不可用"},
            )
            self.assertEqual(
                self.by_id[f"{prefix}.position"]["enumValues"],
                {0: "原位", 1: "工作位", 2: "未知", 65535: "不可用"},
            )
            self.assertEqual(self.by_id[f"{prefix}.position"]["unit"], "")

        for group, address in enumerate((400, 402, 404)):
            self.assertEqual(
                self.by_id[f"input_register.alarm.error_group_{group}"]["address"],
                address,
            )

    def test_sensor_configuration_matches_v9_fields(self) -> None:
        self.assertEqual(self.by_id["holding.sensor_1.enabled"]["address"], 100)
        self.assertEqual(
            self.by_id["holding.sensor_1.humidity_start_threshold"]["address"],
            111,
        )
        self.assertEqual(
            self.by_id["holding.sensor_3.humidity_falling_stop_threshold"]["address"],
            155,
        )
        for channel, base in enumerate((187, 189, 191), start=1):
            item = self.by_id[
                f"holding.sensor_{channel}.humidity_peak_drop_threshold"
            ]
            self.assertEqual(item["address"], base)
            self.assertEqual(item["addressEnd"], base + 1)
            self.assertEqual(item["minimum"], 0.01)
        self.assertNotIn("holding.sensor_1.humidity_control_high", self.by_id)
        self.assertNotIn("holding.sensor_1.humidity_control_low", self.by_id)
        self.assertEqual(
            self.by_id["holding.sensor_1.threshold_confirm_interval_seconds"][
                "configKey"
            ],
            "sensors.humidityTemperature[0].thresholdConfirmIntervalSeconds",
        )
        self.assertEqual(
            self.by_id["holding.sensor_1.threshold_confirm_count"]["configKey"],
            "sensors.humidityTemperature[0].thresholdConfirmCount",
        )

    def test_flow_and_valve_settings_match_v9(self) -> None:
        flow = self.by_id["holding.flow.no_change_alarm_days"]
        self.assertEqual((flow["address"], flow["addressEnd"]), (227, 228))
        self.assertEqual(flow["dataType"], "uint32")
        self.assertEqual(flow["unit"], "天")
        for channel, base in enumerate((300, 302, 304), start=1):
            self.assertEqual(
                self.by_id[f"holding.valve_{channel}.enabled"]["address"], base
            )
            self.assertEqual(
                self.by_id[f"holding.valve_{channel}.home_high_level"]["address"],
                base + 1,
            )

    def test_dehumidification_fields_use_current_addresses_and_units(self) -> None:
        expected = {
            "holding.dehumidification.enabled": (400, "bool", ""),
            "holding.dehumidification.mode": (401, "enum16", ""),
            "holding.dehumidification.cycle_interval_days": (402, "uint32", "天"),
            "holding.dehumidification.post_heating_cooling_hours": (
                404,
                "uint32",
                "小时",
            ),
            "holding.dehumidification.force_close_hours": (
                406,
                "uint32",
                "小时",
            ),
            "holding.dehumidification.idle_position_upper": (408, "enum16", ""),
            "holding.dehumidification.idle_position_left": (409, "enum16", ""),
            "holding.dehumidification.idle_position_right": (410, "enum16", ""),
        }
        for point_id, (address, data_type, unit) in expected.items():
            item = self.by_id[point_id]
            self.assertEqual(item["address"], address)
            self.assertEqual(item["dataType"], data_type)
            self.assertEqual(item["unit"], unit)
        self.assertEqual(
            self.by_id["holding.dehumidification.mode"]["enumValues"],
            {0: "单管", 1: "双管"},
        )
        self.assertEqual(
            self.by_id["holding.dehumidification.mode"]["configKey"],
            "control.dehumidification.mode",
        )
        self.assertEqual(
            self.by_id["holding.dehumidification.force_close_hours"]["minimum"],
            1,
        )

    def test_antifreeze_fault_outputs_and_time_units_match_v9(self) -> None:
        self.assertEqual(self.by_id["holding.antifreeze.enabled"]["address"], 420)
        self.assertEqual(
            self.by_id["holding.antifreeze.close_delay_hours"]["address"], 426
        )
        self.assertEqual(
            self.by_id["holding.antifreeze.close_delay_hours"]["unit"], "小时"
        )
        self.assertEqual(
            self.by_id["holding.sensor_fault.flow_action"]["address"], 432
        )
        self.assertEqual(
            self.by_id["holding.sensor_fault.flow_action"]["enumValues"][3],
            "报警停热并回安全位",
        )
        self.assertEqual(self.by_id["holding.output.htc1_enabled"]["address"], 500)
        self.assertEqual(self.by_id["holding.logging.sensor_interval"]["unit"], "秒")
        self.assertEqual(
            self.by_id["holding.communication.baudrate"]["allowedValues"],
            [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200],
        )

    def test_schedule_uses_three_current_humidity_parameters(self) -> None:
        self.assertEqual(
            self.by_id["holding.schedule.humidity_start_threshold_3"]["addressEnd"],
            735,
        )
        self.assertEqual(
            self.by_id[
                "holding.schedule.humidity_falling_stop_threshold_3"
            ]["addressEnd"],
            741,
        )
        self.assertEqual(
            self.by_id["holding.schedule.humidity_peak_drop_threshold_3"][
                "addressEnd"
            ],
            747,
        )
        self.assertEqual(self.by_id["holding.schedule.operation"]["address"], 748)
        self.assertNotIn("holding.schedule.humidity_high_1", self.by_id)
        self.assertNotIn("holding.schedule.humidity_low_1", self.by_id)

    def test_runtime_and_diagnostics_remain_separate(self) -> None:
        self.assertEqual(self.by_id["holding.config.command"]["address"], 3)
        self.assertEqual(self.by_id["holding.runtime.remote_heat"]["address"], 800)
        self.assertEqual(self.by_id["holding.runtime.reset"]["address"], 807)
        self.assertEqual(self.by_id["holding.runtime.valve_guard_reason"]["address"], 817)
        self.assertEqual(self.by_id["holding.runtime.valve_action_limit"]["address"], 820)
        expected = {0: "自动", 1: "远程", 2: "安全保护", 3: "周期维护"}
        self.assertEqual(
            self.by_id["input_register.valve_1.control_source"]["enumValues"],
            expected,
        )


if __name__ == "__main__":
    unittest.main()
