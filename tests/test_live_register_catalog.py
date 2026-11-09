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

    def test_v10_catalog_is_unique_and_complete(self) -> None:
        summary = get_register_catalog_summary()
        self.assertEqual(PROTOCOL_VERSION_WORD, 0x0A01)
        self.assertEqual(summary["protocolVersion"], "10.1")
        self.assertEqual(summary["areas"], {"discrete_input": 68, "input_register": 72, "coil": 71, "holding_register": 181})
        for address, suffix in ((269, "humidity_start_threshold"),
                                (271, "humidity_falling_stop_threshold"),
                                (273, "humidity_peak_drop_threshold"),
                                (275, "threshold_confirm_interval_seconds"),
                                (277, "threshold_confirm_count")):
            self.assertEqual(self.by_id[f"holding.dehumidification.{suffix}"]["address"], address)
        self.assertNotIn("holding.sensor_1.humidity_start_threshold", self.by_id)
        self.assertNotIn("holding.sensor_2.threshold_confirm_count", self.by_id)
        for suffix in ("humidity_start_threshold", "humidity_falling_stop_threshold",
                       "humidity_peak_drop_threshold"):
            self.assertNotIn(f"holding.sensor_3.{suffix}", self.by_id)
        self.assertEqual(len(self.catalog), len(self.by_id))
        self.assertTrue(all(item["sourceOfTruth"] == "station-modbus-v10" for item in self.catalog))

    def test_mandatory_grid_points_match_document(self) -> None:
        self.assertEqual(self.by_id["input_register.output.total_heat_state"]["address"], 0)
        self.assertEqual(self.by_id["discrete_input.alarm.breath_no_change"]["address"], 16)
        self.assertEqual(self.by_id["input_register.sensor_3.read_ok"]["address"], 17)
        for point_id in ("input_register.sensor_3.read_ok", "discrete_input.pressure.read_ok", "discrete_input.flow.read_ok"):
            self.assertTrue(self.by_id[point_id]["invertBoolean"])
        self.assertEqual((self.by_id["input_register.sensor_3.humidity"]["address"], self.by_id["input_register.flow"]["addressEnd"]), (2, 7))

    def test_four_areas_do_not_cross(self) -> None:
        self.assertEqual(self.by_id["holding.runtime.remote_heat"]["area"], "coil")
        self.assertEqual(self.by_id["holding.communication.slave_id"]["area"], "holding_register")
        self.assertEqual(self.by_id["discrete_input.valve_1.home_not_reached"]["area"], "discrete_input")
        self.assertEqual(self.by_id["input_register.valve_1.current_adc"]["area"], "input_register")
        self.assertEqual(self.by_id["input_register.system.protocol_version"]["address"], 100)

    def test_pair_controls_require_fc15(self) -> None:
        for point_id in ("holding.runtime.htc1_mode", "holding.runtime.htc2_mode", "holding.runtime.antifreeze_mode", "holding.runtime.valve_1", "holding.runtime.valve_2", "holding.runtime.valve_3"):
            item = self.by_id[point_id]
            self.assertEqual(item["area"], "coil")
            self.assertEqual(item["wordLength"], 2)
            self.assertEqual(item["dataType"], "control_pair")
            self.assertEqual(item["functionCode"], [1, 15])

    def test_fixed_schedule_slots_match_v10_layout(self) -> None:
        for task in range(1, 13):
            base = 512 + (task - 1) * 32
            self.assertEqual(self.by_id[f"holding.schedule.slot_{task}.enabled"]["address"], 96 + (task - 1) * 2)
            self.assertEqual(self.by_id[f"holding.schedule.slot_{task}.start_month"]["address"], base)
            self.assertEqual(self.by_id[f"holding.schedule.slot_{task}.humidity_peak_drop_threshold_2"]["addressEnd"], base + 21)
            for suffix in ("humidity_start_threshold", "humidity_falling_stop_threshold",
                           "humidity_peak_drop_threshold"):
                self.assertNotIn(f"holding.schedule.slot_{task}.{suffix}_3", self.by_id)

    def test_business_duration_units_keep_seconds_on_wire(self) -> None:
        expected = {
            "holding.flow.no_change_alarm_seconds": (86400, "天", 365),
            "holding.dehumidification.cycle_interval_seconds": (86400, "天", 365),
            "holding.dehumidification.post_heating_cooling_seconds": (3600, "小时", 8760),
            "holding.dehumidification.force_close_seconds": (3600, "小时", 8760),
            "holding.antifreeze.close_delay_seconds": (3600, "小时", 8760),
        }
        for item_id, (scale, unit, maximum) in expected.items():
            item = self.by_id[item_id]
            self.assertEqual(item["unit"], "s")
            self.assertEqual(item["displayScale"], scale)
            self.assertEqual(item["displayUnit"], unit)
            self.assertEqual(item["displayMaximum"], maximum)


if __name__ == "__main__":
    unittest.main()
