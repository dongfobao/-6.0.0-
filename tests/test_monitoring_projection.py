from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from monitoring_projection import build_monitoring_snapshot


def item(point_id, value, **extra):
    return {"id": point_id, "name": point_id, "currentValue": value, "updatedAt": "2026-09-14 12:00:00", **extra}


class MonitoringProjectionTests(unittest.TestCase):
    def test_projects_v10_sensors_valves_and_alarm_bits(self) -> None:
        metrics = []
        statuses = [item("discrete_input.alarm.any", True), item("discrete_input.alarm.sensor_1_fault", True), item("discrete_input.alarm.htc1_fault", True)]
        for channel in range(1, 4):
            metrics += [item(f"input_register.sensor_{channel}.temperature", 20 + channel), item(f"input_register.sensor_{channel}.humidity", 50 + channel)]
            statuses += [item(f"input_register.sensor_{channel}.read_ok", True)]
            base = f"discrete_input.valve_{channel}"
            statuses += [item(f"{base}.home_not_reached", channel == 2), item(f"{base}.work_not_reached", channel != 2), item(f"{base}.moving", False), item(f"{base}.fault", False), item(f"{base}.unknown", False), item(f"{base}.disabled", False)]
        result = build_monitoring_snapshot({"deviceId": "dev-1", "metrics": metrics, "statuses": statuses, "session": {}})
        self.assertEqual(len(result["environmentChannels"]), 3)
        self.assertEqual(result["environmentChannels"][2]["temperature"]["value"], 23)
        self.assertEqual(result["valves"][1]["position"]["value"], 1)
        self.assertTrue(result["alarms"]["active"])
        self.assertTrue(result["alarms"]["sensorModules"]["t1"])
        self.assertTrue(result["alarms"]["equipmentModules"]["heater"])

    def test_runtime_valve_diagnostics_use_v10_ir_points(self) -> None:
        controls = [item("holding.runtime.valve_1", 2, enumValues={2: "到工作位"})]
        metrics = [item("input_register.valve_1.fault_reason", 8, enumValues={8: "开路"}), item("input_register.valve_1.control_source", 1, enumValues={1: "远程"}), item("input_register.valve_1.remote_seconds", 600), item("input_register.runtime.valve_guard_reason", 3, enumValues={3: "故障重试"}), item("input_register.runtime.valve_guard_remaining_seconds", 42), item("input_register.runtime.valve_action_count", 5), item("input_register.runtime.valve_action_limit", 6)]
        result = build_monitoring_snapshot({"metrics": metrics, "controls": controls, "session": {}})
        valve = result["runtimeValves"][0]
        self.assertEqual(valve["command"]["displayValue"], "到工作位")
        self.assertEqual(valve["faultReason"]["displayValue"], "开路")
        self.assertEqual(valve["effectiveSource"]["displayValue"], "远程")
        self.assertEqual(valve["remoteSeconds"]["value"], 600)
        self.assertTrue(result["valveGuard"]["active"])

    def test_breath_enum_uses_catalog_label(self) -> None:
        result = build_monitoring_snapshot({"metrics": [item("input_register.breath_state", 1, enumValues={0: "呼气", 1: "吸气"})], "session": {}})
        self.assertEqual(result["process"]["breathState"]["displayValue"], "吸气")

    def test_schedule_plan_uses_selected_slot_aliases(self) -> None:
        controls = [
            item("holding.schedule.task_count", 12),
            item("holding.schedule.selected_task", 2),
            item("holding.schedule.enabled", True),
            item("holding.schedule.start_month", 9),
            item("holding.schedule.start_day", 15),
        ]
        result = build_monitoring_snapshot({"controls": controls, "session": {}})
        self.assertEqual(result["schedulePlan"]["taskCount"]["value"], 12)
        self.assertEqual(result["schedulePlan"]["selectedTask"]["value"], 2)
        self.assertTrue(result["schedulePlan"]["enabled"]["value"])
        self.assertEqual(result["schedulePlan"]["startMonth"]["value"], 9)


if __name__ == "__main__":
    unittest.main()
