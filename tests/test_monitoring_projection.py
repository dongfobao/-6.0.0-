from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from monitoring_projection import build_monitoring_snapshot


def item(point_id, value, name="点", **extra):
    return {"id": point_id, "name": name, "currentValue": value, "updatedAt": "2026-07-20 12:00:00", **extra}


class MonitoringProjectionTests(unittest.TestCase):
    def test_projects_three_sensors_and_three_valves(self):
        metrics = []
        for channel in range(1, 4):
            prefix = f"input_register.sensor_{channel}"
            metrics.extend([
                item(f"{prefix}.temperature", 20.0 + channel),
                item(f"{prefix}.humidity", 50.0 + channel),
                item(f"{prefix}.status", 0), item(f"{prefix}.read_ok", True),
            ])
            valve = f"input_register.valve_{channel}"
            for offset, key in enumerate(("display_state", "actuator_state", "position", "fault_reason", "current_adc", "control_source")):
                metrics.append(item(f"{valve}.{key}", offset))
        result = build_monitoring_snapshot({"deviceId": "dev-1", "metrics": metrics, "session": {}})
        self.assertEqual(len(result["environmentChannels"]), 3)
        self.assertEqual(result["environmentChannels"][2]["temperature"]["value"], 23.0)
        self.assertEqual(len(result["valves"]), 3)
        self.assertEqual(result["valves"][1]["position"]["value"], 2)

    def test_alarm_summary_detects_any_nonzero_group(self):
        metrics = [
            item("input_register.alarm.active_low", 0),
            item("input_register.alarm.active_high", 4),
            item("input_register.alarm.latched", 0),
        ]
        result = build_monitoring_snapshot({"metrics": metrics, "session": {}})
        self.assertTrue(result["alarms"]["active"])

    def test_enum_value_uses_display_label(self):
        metrics = [item("input_register.breath_state", 1, enumValues={0: "呼气", 1: "吸气"})]
        result = build_monitoring_snapshot({"metrics": metrics, "session": {}})
        self.assertEqual(result["process"]["breathState"]["displayValue"], "吸气")


if __name__ == "__main__":
    unittest.main()
