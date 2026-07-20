import tempfile
import sys
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_session_recorder import LiveSessionRecorder


class LiveSessionRecorderTests(unittest.TestCase):
    def test_recorder_writes_analysis_compatible_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            recorder = LiveSessionRecorder(
                Path(tmp_dir),
                {"id": "dev-1", "name": "设备A"},
                config_snapshot={"ver": "1.0"},
            )
            recorder.record_environment_snapshot(
                datetime(2026, 5, 22, 12, 0, 0),
                {"pressure": 1.2, "temperature": 25.0, "flow": -1.5, "humidity": 44.0},
            )
            recorder.record_log("I", datetime(2026, 5, 22, 12, 0, 1), "session started")
            recorder.finalize()

            self.assertTrue((recorder.session_dir / "config.json").exists())
            self.assertTrue(recorder.env_path.exists())
            self.assertTrue(recorder.breath_path.exists())
            self.assertTrue(recorder.run_path.exists())
            self.assertFalse(recorder.raw_path.exists())
            self.assertIn("[2026-05-22 12:00:00],/* 1.20,25.00,-1.50,44.00 */", recorder.env_path.read_text(encoding="utf-8"))
            self.assertIn("2026-05-22 12:00:00,0,-1.50,0.0,1", recorder.breath_path.read_text(encoding="utf-8"))
            self.assertIn("I/YLDQ [2026-05-22 12:00:01] session started", recorder.run_path.read_text(encoding="utf-8"))

    def test_export_groups_sessions_by_device_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            recorder = LiveSessionRecorder(
                root / "sessions",
                {"id": "dev-1", "name": "设备A"},
                config_snapshot={"ver": "1.0"},
            )
            recorder.finalize()

            exported_dir = recorder.export_to(root / "exports")

            self.assertEqual(exported_dir.parent.name, "设备A__dev_1")
            self.assertTrue((exported_dir / "config.json").exists())


    def test_export_omits_raw_and_traffic_debug_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            recorder = LiveSessionRecorder(
                root / "sessions",
                {"id": "dev-1", "name": "璁惧A"},
                config_snapshot={"ver": "1.0"},
            )
            recorder.record_environment_snapshot(
                datetime(2026, 5, 22, 12, 0, 0),
                {"pressure": 1.2, "temperature": 25.0, "flow": -1.5, "humidity": 44.0},
            )
            recorder.record_raw_snapshot(
                datetime(2026, 5, 22, 12, 0, 0),
                {"Pressure": 123, "Flow": -4.5},
            )
            recorder.record_traffic_entry({"seq": 1, "requestHex": "01 03 00 00 00 01"})
            recorder.finalize()

            exported_dir = recorder.export_to(root / "exports")

            self.assertTrue((exported_dir / "data_0").exists())
            self.assertTrue(any((exported_dir / "data_0").glob("log_*.csv")))
            self.assertFalse(any((exported_dir / "data_0").glob("raw_*.csv")))
            self.assertFalse((exported_dir / "traffic").exists())

    def test_export_rejects_target_inside_session_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            recorder = LiveSessionRecorder(
                root / "sessions",
                {"id": "dev-1", "name": "璁惧A"},
                config_snapshot={"ver": "1.0"},
            )
            recorder.finalize()

            with self.assertRaises(ValueError):
                recorder.export_to(recorder.session_dir / "nested_export")

    def test_traffic_file_is_created_only_for_abnormal_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            recorder = LiveSessionRecorder(
                Path(tmp_dir),
                {"id": "dev-1", "name": "璁惧A"},
                config_snapshot={"ver": "1.0"},
            )

            recorder.record_traffic_entry({"status": "ok", "traceId": 1})
            self.assertFalse(recorder.traffic_path.exists())

            recorder.record_traffic_entry({"status": "no_response", "traceId": 2, "error": "timeout"})
            self.assertTrue(recorder.traffic_path.exists())
            content = recorder.traffic_path.read_text(encoding="utf-8")
            self.assertIn('"traceId": 2', content)
            self.assertNotIn('"traceId": 1', content)


if __name__ == "__main__":
    unittest.main()
