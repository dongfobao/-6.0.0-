from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_register_catalog import get_register_catalog


class LiveRegisterCatalogTests(unittest.TestCase):
    def test_respiratory_registers_use_new_config_keys(self) -> None:
        catalog = get_register_catalog()
        by_address = {
            item["address"]: item
            for item in catalog
            if item.get("area") == "holding_register" and item.get("address") in {8, 9, 10, 11, 13, 15, 17, 18, 20, 23, 25, 150, 152}
        }

        self.assertEqual(by_address[8]["configKey"], "RespiratoryRate.HeatOnThreshold")
        self.assertEqual(by_address[9]["configKey"], "RespiratoryRate.HeatOffThreshold")
        self.assertEqual(by_address[10]["configKey"], "RespiratoryRate.ExhaleTimeoutMinSec")
        self.assertEqual(by_address[11]["configKey"], "RespiratoryRate.NoChangeAlarmTimeSec")
        self.assertEqual(by_address[11]["addressEnd"], 12)
        self.assertEqual(by_address[13]["configKey"], "RespiratoryRate.ExhaleTimeoutSec")
        self.assertEqual(by_address[13]["addressEnd"], 14)
        self.assertEqual(by_address[15]["configKey"], "RespiratoryRate.HeatEvidenceIntervalSec")
        self.assertEqual(by_address[15]["addressEnd"], 16)
        self.assertEqual(by_address[17]["configKey"], "RespiratoryRate.HeatEvidenceCount")
        self.assertEqual(by_address[18]["configKey"], "HumidityValue.offset")
        self.assertEqual(by_address[18]["addressEnd"], 19)
        self.assertEqual(by_address[18]["dataType"], "float32")
        self.assertEqual(by_address[20]["configKey"], "RespiratoryRate.offset")
        self.assertEqual(by_address[20]["addressEnd"], 21)
        self.assertEqual(by_address[20]["dataType"], "float32")
        self.assertEqual(by_address[23]["configKey"], "RespiratoryRate.DERangeLT")
        self.assertEqual(by_address[25]["configKey"], "RespiratoryRate.DERangeHT")
        self.assertEqual(by_address[150]["configKey"], "HumidityValue.HeatEvidenceIntervalSec")
        self.assertEqual(by_address[150]["addressEnd"], 151)
        self.assertEqual(by_address[150]["dataType"], "uint32")
        self.assertEqual(by_address[152]["configKey"], "HumidityValue.HeatEvidenceCount")
        self.assertEqual(by_address[152]["dataType"], "uint16")

    def test_output_online_coils_follow_firmware_config_keys(self) -> None:
        catalog = get_register_catalog()
        by_address = {
            item["address"]: item
            for item in catalog
            if item.get("area") == "coil" and item.get("address") in {6, 7, 8, 9, 10}
        }

        self.assertEqual(by_address[6]["configKey"], "outOnline.HeatChannel1_Online")
        self.assertEqual(by_address[7]["configKey"], "outOnline.HeatChannel2_Online")
        self.assertEqual(by_address[8]["configKey"], "outOnline.Valve_Online")
        self.assertEqual(by_address[9]["configKey"], "outOnline.Antifreeze_Online")
        self.assertEqual(by_address[10]["configKey"], "outOnline.AlarmOutput_Online")

        config_keys = {item.get("configKey") for item in catalog}
        self.assertNotIn("outOnline.HTC1_Online", config_keys)
        self.assertNotIn("outOnline.HTC2_Online", config_keys)
        self.assertNotIn("outOnline.CHT_Online", config_keys)
        self.assertNotIn("outOnline.DRAIN_Online", config_keys)

    def test_output_state_inputs_follow_firmware_device_order(self) -> None:
        catalog = get_register_catalog()
        by_address = {
            item["address"]: item
            for item in catalog
            if item.get("area") == "discrete_input" and item.get("address") in {13, 14}
        }

        self.assertEqual(by_address[13]["id"], "input.valve_state")
        self.assertEqual(by_address[14]["id"], "input.antifreeze_state")

    def test_task_registers_follow_firmware_modbus_layout(self) -> None:
        catalog = get_register_catalog()
        by_id = {item["id"]: item for item in catalog}
        config_keys = {item.get("configKey") for item in catalog}

        self.assertEqual(by_id["holding.task_count"]["address"], 27)

        self.assertEqual(by_id["holding.task0_start_month"]["address"], 30)
        self.assertFalse(by_id["holding.task0_start_month"]["writable"])
        self.assertEqual(by_id["holding.task0_delay"]["address"], 34)
        self.assertEqual(by_id["holding.task0_delay"]["addressEnd"], 35)
        self.assertEqual(by_id["holding.task0_humidity_high"]["address"], 36)
        self.assertEqual(by_id["holding.task0_humidity_low"]["address"], 37)
        self.assertEqual(by_id["holding.task0_respiratory_on"]["address"], 38)
        self.assertEqual(by_id["holding.task0_respiratory_off"]["address"], 39)

        self.assertEqual(by_id["holding.task1_delay"]["address"], 44)
        self.assertEqual(by_id["holding.task2_delay"]["address"], 54)

        self.assertNotIn("TaskArray[0].cycleTime", config_keys)
        self.assertNotIn("TaskArray[1].cycleTime", config_keys)
        self.assertNotIn("TaskArray[2].cycleTime", config_keys)
        self.assertNotIn("holding.task0_cycle", by_id)
        self.assertNotIn("holding.task1_cycle", by_id)
        self.assertNotIn("holding.task2_cycle", by_id)


if __name__ == "__main__":
    unittest.main()
