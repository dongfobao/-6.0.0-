from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from simulation_engine import (  # noqa: E402
    ExhaleTracker,
    SimulationParams,
    _dynamic_timeout_sec,
    _record_exhale_interval,
    run_simulation,
)


class SimulationEngineTests(unittest.TestCase):
    def test_humidity_and_breath_evidence_open_then_low_humidity_closes(self) -> None:
        config = {
            "HumidityValue": {
                "HThreshold": 40,
                "LThreshold": 37,
                "Priority": True,
                "HeatEvidenceIntervalSec": 180,
                "HeatEvidenceCount": 2,
            },
            "RespiratoryRate": {
                "HeatOnThreshold": -4,
                "HeatOffThreshold": 1,
                "HeatEvidenceIntervalSec": 180,
                "HeatEvidenceCount": 2,
                "ExhaleTimeoutMinSec": 900,
                "ExhaleTimeoutSec": 2400,
                "infor": {"Priority": True},
            },
            "Temperature": {"LThreshold": -5},
        }
        environment_rows = [
            {"ts": "2026-06-22T00:00:00", "humidity": 45, "temperature": 20, "pressure": 0, "flow": 0},
            {"ts": "2026-06-22T00:04:00", "humidity": 45, "temperature": 20, "pressure": 0, "flow": 0},
            {"ts": "2026-06-22T00:10:00", "humidity": 30, "temperature": 20, "pressure": 0, "flow": 0},
            {"ts": "2026-06-22T00:14:00", "humidity": 30, "temperature": 20, "pressure": 0, "flow": 0},
        ]
        breath_rows = [
            {"ts": "2026-06-22T00:00:10", "flow_rate": -5, "state": 0, "rhythm": 2},
            {"ts": "2026-06-22T00:03:10", "flow_rate": -5, "state": 0, "rhythm": 0},
            {"ts": "2026-06-22T00:06:10", "flow_rate": -5, "state": 0, "rhythm": 0},
        ]

        result = run_simulation(environment_rows, breath_rows, config)

        self.assertEqual(result["summary"]["segments"], 1)
        self.assertEqual([item["type"] for item in result["actions"]], ["heat_on", "heat_off"])
        self.assertEqual(result["actions"][0]["ts"], "2026-06-22T00:03:10")
        self.assertEqual(result["actions"][1]["ts"], "2026-06-22T00:13:00")

    def test_exhale_timeout_min_only_clamps_final_timeout(self) -> None:
        tracker = ExhaleTracker()
        params = SimulationParams(exhale_timeout_min_sec=60, exhale_timeout_sec=1000)

        _record_exhale_interval(tracker, 57, 60, 0)

        self.assertEqual(tracker.predicted_interval_sec, 60)
        self.assertEqual(tracker.recovery_floor_sec, 0)
        self.assertEqual(_dynamic_timeout_sec(tracker, params), 90)

    def test_near_timeout_exhale_raises_target_by_thirty_percent(self) -> None:
        tracker = ExhaleTracker()
        params = SimulationParams(exhale_timeout_min_sec=300, exhale_timeout_sec=1000)

        _record_exhale_interval(tracker, 60, 60, 0)
        self.assertEqual(_dynamic_timeout_sec(tracker, params), 300)

        _record_exhale_interval(tracker, 295, 60, 300)

        self.assertEqual(tracker.recovery_floor_sec, 390)
        self.assertEqual(_dynamic_timeout_sec(tracker, params), 390)

    def test_non_near_timeout_interval_clears_recovery_floor(self) -> None:
        tracker = ExhaleTracker(recovery_floor_sec=390)
        params = SimulationParams(exhale_timeout_min_sec=300, exhale_timeout_sec=1000)

        _record_exhale_interval(tracker, 100, 60, 390)

        self.assertEqual(tracker.recovery_floor_sec, 0)
        self.assertEqual(_dynamic_timeout_sec(tracker, params), 300)


if __name__ == "__main__":
    unittest.main()
