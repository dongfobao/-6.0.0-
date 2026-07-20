import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_device_store import export_live_devices_json, import_live_devices_payload


class LiveDeviceStoreTests(unittest.TestCase):
    def test_export_live_devices_json_returns_normalized_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "live_devices.json"
            store_path.write_text(
                json.dumps(
                    {
                        "devices": [
                            {
                                "id": "dev-1",
                                "name": "设备A",
                                "address": "COM7",
                                "slaveId": 2,
                            }
                        ],
                        "selectedDeviceId": "dev-1",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exported = json.loads(export_live_devices_json(store_path))

            self.assertEqual(exported["selectedDeviceId"], "dev-1")
            self.assertEqual(exported["devices"][0]["name"], "设备A")
            self.assertEqual(exported["devices"][0]["slaveId"], 2)
            self.assertIn("profiles", exported)

    def test_import_live_devices_payload_normalizes_and_persists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "live_devices.json"

            imported = import_live_devices_payload(
                store_path,
                {
                    "devices": [
                        {
                            "id": "dev-2",
                            "name": "设备B",
                            "address": "COM9",
                            "slaveId": 6,
                            "pollingSettings": {
                                "fast": {"intervalMs": 50},
                            },
                        }
                    ],
                    "selectedDeviceId": "missing-device",
                },
            )

            self.assertEqual(imported["selectedDeviceId"], "dev-2")
            self.assertEqual(imported["devices"][0]["slaveId"], 6)
            self.assertEqual(imported["devices"][0]["pollingSettings"]["fast"]["intervalMs"], 100)
            saved = json.loads(store_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["selectedDeviceId"], "dev-2")


if __name__ == "__main__":
    unittest.main()
