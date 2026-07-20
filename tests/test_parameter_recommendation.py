from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from unittest.mock import patch

from parameter_recommendation import (  # noqa: E402
    build_parameter_recommendation_payload,
    build_parameter_recommendations,
)


class ParameterRecommendationTests(unittest.TestCase):
    def test_returns_threshold_recommendations_with_high_confidence(self) -> None:
        config = {
            "Temperature": {"HThreshold": 40, "LThreshold": 5},
            "HumidityValue": {"HThreshold": 85, "LThreshold": 15},
            "PressureValue": {"HThreshold": 25, "LThreshold": -10},
            "RespiratoryRate": {"HeatOnThreshold": -6, "HeatOffThreshold": 2},
        }
        history = {
            "environment_rows": [
                {"temperature": 21.0, "humidity": 40.0, "pressure": 1.2, "flow": 4.0},
                {"temperature": 23.0, "humidity": 43.0, "pressure": 1.1, "flow": 5.0},
                {"temperature": 24.0, "humidity": 44.0, "pressure": 1.4, "flow": 5.2},
            ],
            "breath_rows": [
                {"flow_rate": 3.0, "elapsed_since_change": 10.0, "state": 1, "rhythm": 0},
                {"flow_rate": -2.8, "elapsed_since_change": 12.0, "state": 0, "rhythm": 1},
                {"flow_rate": 2.2, "elapsed_since_change": 11.0, "state": 1, "rhythm": 0},
            ],
            "run_rows": [],
        }
        result = build_parameter_recommendations(config=config, history=history, strategy="balanced")
        paths = {item["parameter_path"]: item for item in result}
        self.assertIn("Temperature.HThreshold", paths)
        self.assertEqual(paths["Temperature.HThreshold"]["confidence"], "high")
        self.assertEqual(paths["Temperature.HThreshold"]["strategy"], "balanced")
        self.assertIn("RespiratoryRate.HeatOnThreshold", paths)
        self.assertEqual(paths["RespiratoryRate.HeatOnThreshold"]["recommended_value"], -4)
        self.assertIn("RespiratoryRate.HeatOffThreshold", paths)
        self.assertEqual(paths["RespiratoryRate.HeatOffThreshold"]["recommended_value"], -1)

    def test_marks_task_delay_as_low_confidence(self) -> None:
        config = {
            "TaskArray": [{"name": "HTC1", "delay": 120}],
            "TaskCount": 1,
        }
        history = {"environment_rows": [], "breath_rows": [], "run_rows": []}
        result = build_parameter_recommendations(config=config, history=history, strategy="balanced")
        low_confidence = [item for item in result if item["confidence"] == "low"]
        self.assertTrue(low_confidence)
        self.assertTrue(any(item["parameter_path"] == "TaskArray[0].delay" for item in low_confidence))

    def test_payload_groups_recommendations_by_confidence(self) -> None:
        config = {"Temperature": {"HThreshold": 40}}
        history = {
            "environment_rows": [
                {"temperature": 22.0, "humidity": 44.0, "pressure": 1.0},
                {"temperature": 23.5, "humidity": 45.0, "pressure": 1.2},
                {"temperature": 24.2, "humidity": 46.0, "pressure": 1.1},
            ],
            "breath_rows": [],
            "run_rows": [],
        }
        payload = build_parameter_recommendation_payload(config=config, history=history)
        self.assertIn("recommendations", payload)
        self.assertIn("summary", payload)
        self.assertGreaterEqual(payload["summary"]["high_confidence_count"], 1)

    def test_recommends_current_time_from_system_time_plus_30_seconds(self) -> None:
        config = {"curDateTime": "2026-01-01 00:00:00"}
        history = {"environment_rows": [], "breath_rows": [], "run_rows": []}
        with patch("parameter_recommendation.time.time", return_value=1767225570):
            result = build_parameter_recommendations(config=config, history=history, strategy="balanced")
        paths = {item["parameter_path"]: item for item in result}
        self.assertIn("curDateTime", paths)
        self.assertEqual(paths["curDateTime"]["recommended_value"], "2026-01-01 08:00:00")

    def test_recommends_double_switch_as_half_of_breath_evidence_interval(self) -> None:
        config = {
            "DoubleSwitch": 20,
            "RespiratoryRate": {"DERangeHT": 3, "DERangeLT": -3, "HeatEvidenceIntervalSec": 30},
        }
        history = {
            "environment_rows": [],
            "breath_rows": [
                {"flow_rate": 3.0, "elapsed_since_change": 10.0, "state": 1, "rhythm": 0},
                {"flow_rate": -2.8, "elapsed_since_change": 12.0, "state": 0, "rhythm": 1},
                {"flow_rate": 2.2, "elapsed_since_change": 11.0, "state": 1, "rhythm": 0},
            ],
            "run_rows": [],
        }
        result = build_parameter_recommendations(config=config, history=history, strategy="balanced")
        paths = {item["parameter_path"]: item for item in result}
        self.assertIn("RespiratoryRate.HeatEvidenceIntervalSec", paths)
        self.assertIn("DoubleSwitch", paths)
        expected = max(int(round(float(paths["RespiratoryRate.HeatEvidenceIntervalSec"]["recommended_value"]) / 2.0)), 1)
        self.assertEqual(paths["DoubleSwitch"]["recommended_value"], expected)


if __name__ == "__main__":
    unittest.main()
