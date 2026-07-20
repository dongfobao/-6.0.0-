from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from dashboard_server import (
    _build_live_device_context,
    _build_live_meta_projection,
    _build_live_parameters_projection,
    _build_live_series_projection,
    _build_live_snapshot_projection,
    _project_live_session,
)


def build_service_status(running: bool = True, device_id: str | None = "dev-a") -> dict:
    return {
        "running": running,
        "device_ids": [device_id] if device_id else [],
        "started_at": "2026-05-22 10:00:00",
        "last_error": None,
        "last_success_at": "2026-05-22 10:00:05",
        "error_count": 0,
        "request_count": 5,
        "sample_counts": {
            "metrics": 4,
            "statuses": 3,
            "controls": 2,
            "parameters": 7,
            "history": 12,
        },
        "last_snapshot_at": "2026-05-22 10:00:05",
        "session_dir": "C:/tmp/session",
    }


class LiveDashboardProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.devices_payload = {
            "selectedDeviceId": "dev-b",
            "devices": [
                {"id": "dev-a", "name": "Device A"},
                {"id": "dev-b", "name": "Device B"},
            ],
        }

    def test_context_marks_mismatch_when_selected_and_session_device_differ(self) -> None:
        context = _build_live_device_context(self.devices_payload, build_service_status(), requested_device_id="dev-b")
        self.assertFalse(context["matchesSelectedDevice"])
        self.assertFalse(context["activeMatchesSelectedDevice"])
        self.assertEqual(context["selectedDevice"]["name"], "Device B")
        self.assertEqual(context["activeDeviceId"], "dev-a")

    def test_project_session_clears_runtime_state_for_mismatched_device(self) -> None:
        service_status = build_service_status()
        context = _build_live_device_context(self.devices_payload, service_status, requested_device_id="dev-b")
        projected = _project_live_session(service_status, context)
        self.assertFalse(projected["running"])
        self.assertEqual(projected["device_id"], "dev-b")
        self.assertEqual(projected["request_count"], 0)
        self.assertEqual(projected["sample_counts"]["history"], 0)

    def test_snapshot_series_and_meta_project_empty_for_mismatched_device(self) -> None:
        service_status = build_service_status()
        context = _build_live_device_context(self.devices_payload, service_status, requested_device_id="dev-b")

        snapshot = _build_live_snapshot_projection(
            {
                "deviceId": "dev-a",
                "ts": "2026-05-22 10:00:05",
                "metrics": [{"id": "pressure"}],
                "statuses": [{"id": "ok"}],
                "controls": [],
                "session": service_status,
            },
            service_status,
            context,
        )
        series = _build_live_series_projection(
            {"rows": [{"ts": "2026-05-22 10:00:05", "pressure": 1.0}], "byMetric": {"pressure": [{"value": 1.0}]}},
            context,
        )
        meta = _build_live_meta_projection(
            {"available": True, "sessionDir": "C:/tmp/session", "lastSnapshot": {"pressure": 1.0}, "session": service_status},
            service_status,
            context,
        )

        self.assertEqual(snapshot["metrics"], [])
        self.assertEqual(series["rows"], [])
        self.assertFalse(meta["available"])

    def test_parameters_projection_keeps_catalog_when_sections_are_provided(self) -> None:
        service_status = build_service_status(running=False, device_id=None)
        context = _build_live_device_context(self.devices_payload, service_status, requested_device_id="dev-b")
        parameters = _build_live_parameters_projection({"control": [{"id": "x"}], "config": [], "task": []}, context)
        self.assertEqual(parameters["sections"]["control"][0]["id"], "x")
        self.assertFalse(parameters["matchesSelectedDevice"])

    def test_projection_keeps_live_data_for_matching_device(self) -> None:
        service_status = build_service_status()
        context = _build_live_device_context(self.devices_payload, service_status, requested_device_id="dev-a")
        snapshot = _build_live_snapshot_projection(
            {
                "deviceId": "dev-a",
                "ts": "2026-05-22 10:00:05",
                "metrics": [{"id": "pressure"}],
                "statuses": [],
                "controls": [],
                "session": service_status,
            },
            service_status,
            context,
        )

        self.assertTrue(context["matchesSelectedDevice"])
        self.assertTrue(snapshot["matchesSelectedDevice"])
        self.assertEqual(snapshot["device"]["name"], "Device A")
        self.assertEqual(snapshot["metrics"][0]["id"], "pressure")


if __name__ == "__main__":
    unittest.main()
