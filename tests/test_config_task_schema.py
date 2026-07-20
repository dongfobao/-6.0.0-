from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from dashboard_server import CONFIG_SCHEMA, build_config_snapshot, normalize_task_array


class ConfigTaskSchemaTests(unittest.TestCase):
    def test_output_online_schema_uses_current_firmware_keys(self) -> None:
        fields = {
            field["path"]
            for section in CONFIG_SCHEMA
            if section.get("key") == "outputs"
            for field in section.get("fields", [])
            if str(field.get("path", "")).startswith("outOnline.")
        }

        self.assertEqual(
            fields,
            {
                "outOnline.HeatChannel1_Online",
                "outOnline.HeatChannel2_Online",
                "outOnline.Valve_Online",
                "outOnline.Antifreeze_Online",
                "outOnline.AlarmOutput_Online",
            },
        )

    def test_task_schema_matches_expected_fields_exactly(self) -> None:
        task_field = next(
            field
            for section in CONFIG_SCHEMA
            if section.get("key") == "tasks"
            for field in section.get("fields", [])
            if field.get("path") == "TaskArray"
        )
        item_keys = [item["key"] for item in task_field["item_schema"]]
        self.assertEqual(
            item_keys,
            [
                "name",
                "StartTime",
                "delay",
                "HumidityValue.HThreshold",
                "HumidityValue.LThreshold",
                "RespiratoryRate.HeatOnThreshold",
                "RespiratoryRate.HeatOffThreshold",
            ],
        )

    def test_normalize_task_array_preserves_nested_override_structure(self) -> None:
        task_field = next(
            field
            for section in CONFIG_SCHEMA
            if section.get("key") == "tasks"
            for field in section.get("fields", [])
            if field.get("path") == "TaskArray"
        )
        normalized = normalize_task_array(
            [
                {
                    "name": "AutoParamOverride1",
                    "StartTime": "05/28-16:59",
                    "delay": 60,
                    "HumidityValue": {"HThreshold": 20, "LThreshold": 18},
                    "RespiratoryRate": {"HeatOnThreshold": -8, "HeatOffThreshold": 8},
                }
            ],
            task_field,
        )
        self.assertEqual(normalized[0]["delay"], 60)
        self.assertEqual(normalized[0]["HumidityValue"]["HThreshold"], 20)
        self.assertEqual(normalized[0]["HumidityValue"]["LThreshold"], 18)
        self.assertEqual(normalized[0]["RespiratoryRate"]["HeatOnThreshold"], -8)
        self.assertEqual(normalized[0]["RespiratoryRate"]["HeatOffThreshold"], 8)

    def test_build_config_snapshot_exposes_task_override_sections(self) -> None:
        snapshot = build_config_snapshot(
            {
                "TaskArray": [
                    {
                        "name": "AutoParamOverride1",
                        "StartTime": "05/28-16:59",
                        "delay": 60,
                        "HumidityValue": {"HThreshold": 20},
                        "RespiratoryRate": {"HeatOnThreshold": -8},
                    }
                ]
            }
        )
        self.assertEqual(set(snapshot["tasks"][0].keys()), {"name", "start_time", "delay_sec", "humidity", "respiratory"})
        self.assertEqual(snapshot["tasks"][0]["delay_sec"], 60)
        self.assertEqual(snapshot["tasks"][0]["humidity"]["HThreshold"], 20)
        self.assertEqual(snapshot["tasks"][0]["respiratory"]["HeatOnThreshold"], -8)


if __name__ == "__main__":
    unittest.main()
