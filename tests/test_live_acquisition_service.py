import threading
import time
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import live_acquisition_service
from live_acquisition_service import LiveAcquisitionService
from live_modbus_client import ModbusError


class SlowStopService(LiveAcquisitionService):
    def __init__(self):
        super().__init__()
        self.started_device_ids = []

    def _run_port_loop(self, port_key, devices, stop_event):
        for d in devices:
            self.started_device_ids.append(str(d.get("id")))
        if devices and str(devices[0].get("id")) == "old":
            stop_event.wait()
            time.sleep(2.2)
        else:
            stop_event.wait()


class LiveAcquisitionServiceTests(unittest.TestCase):
    def test_protocol_mismatch_stops_v7_decoding(self):
        service = LiveAcquisitionService()
        slot = service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        command = next(item for item in service._default_polling_commands if item["address"] == 0 and item["functionCode"] == 4)
        block = service._command_to_block(command)

        with self.assertRaises(ModbusError):
            service._apply_block_values("dev-a", slot, block, [0x0600] + [0] * 9)

    def test_restarting_waits_for_old_poller_before_new_session(self):
        service = SlowStopService()
        service.start_all([{"id": "old", "name": "old", "address": "COM1", "enabled": True}])
        time.sleep(0.2)

        service.start_all([{"id": "new", "name": "new", "address": "COM1", "enabled": True}])
        time.sleep(0.35)

        status = service.get_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["device_ids"], ["new"])
        self.assertEqual(service.started_device_ids, ["old", "new"])

        service.stop_all()

    def test_write_value_updates_runtime_control_register(self):
        calls = []

        class FakeClient:
            def __init__(self, device):
                self.device = device

            def open(self):
                calls.append(("open", self.device["id"]))

            def close(self):
                calls.append(("close", self.device["id"]))

            def write_single_register(self, address, value):
                calls.append(("register", address, value))

        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        service._device_slots["dev-a"]["state"]["running"] = True

        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            payload = service.write_value("dev-a", "holding.runtime.remote_heat", True)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["currentValue"], True)
        self.assertIn(("register", 800, 1), calls)

    def test_valve_command_is_read_back_before_success(self):
        calls = []

        class FakeClient:
            def __init__(self, device):
                self.device = device

            def open(self):
                pass

            def close(self):
                pass

            def write_single_register(self, address, value):
                calls.append(("write", address, value))

            def read_holding_registers(self, address, count):
                calls.append(("read", address, count))
                return [2, 0, 0, 0, 0, 2, 600, 0, 0, 0, 0, 0, 0]

        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        service._device_slots["dev-a"]["state"]["running"] = True

        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            payload = service.write_value("dev-a", "holding.runtime.valve_1", 2)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["runtimeFeedback"]["holding.runtime.valve_1"], 2)
        self.assertIn(("write", 804, 2), calls)
        self.assertIn(("read", 804, 13), calls)

    def test_write_value_uses_multi_register_write_for_float32(self):
        calls = []

        class FakeClient:
            def __init__(self, device):
                self.device = device

            def open(self):
                pass

            def close(self):
                pass

            def write_multiple_registers(self, address, values):
                calls.append((address, values))

        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        service._device_slots["dev-a"]["state"]["running"] = True

        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            payload = service.write_value("dev-a", "holding.sensor_1.temperature_offset", 12.5)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["currentValue"], 12.5)
        self.assertEqual(calls[0][0], 103)
        self.assertEqual(calls[0][1], [0x4148, 0x0000])

    def test_stage_config_value_uses_v7_transaction_and_readback(self):
        class ConfigClient:
            def __init__(self):
                self.words = {}

            def write_single_register(self, address, value):
                self.words[address] = value

            def write_multiple_registers(self, address, values):
                for offset, value in enumerate(values):
                    self.words[address + offset] = value

            def read_holding_registers(self, address, count):
                return [self.words.get(address + offset, 0) for offset in range(count)]

            def close(self):
                pass

        service = LiveAcquisitionService()
        slot = service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        slot["state"]["running"] = True
        client = ConfigClient()

        with patch.object(service, "_open_manual_client", return_value=client):
            result = service.stage_config_value("dev-a", "holding.sensor_1.temperature_offset", 12.5)

        self.assertTrue(result["staged"])
        self.assertEqual(result["words"], [0x4148, 0x0000])
        self.assertEqual(client.words[103], 0x4148)

    def test_execute_config_commit_uses_firmware_magic(self):
        calls = []

        class ConfigClient:
            def write_single_register(self, address, value):
                calls.append((address, value))

            def read_holding_registers(self, address, count):
                return [0x0700, 0, 11, 0xC6A6, 0]

            def close(self):
                pass

        service = LiveAcquisitionService()
        slot = service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        slot["state"]["running"] = True

        with patch.object(service, "_open_manual_client", return_value=ConfigClient()):
            result = service.execute_config_transaction("dev-a", "commit")

        self.assertEqual(calls, [(3, 0xC6A6)])
        self.assertEqual(result["status"]["generation"], 11)

    def test_write_value_opens_target_device_client_instead_of_reusing_port_runner(self):
        calls = []

        class ActiveClient:
            def __init__(self):
                self._serial = object()

            def close(self):
                self._serial = None
                calls.append(("active-close",))

        class TargetClient:
            def __init__(self, device):
                self.device = device
                self._serial = None

            def set_trace_callback(self, callback):
                self.callback = callback

            def open(self):
                self._serial = object()
                calls.append(("target-open", self.device["id"], self.device["slaveId"]))

            def close(self):
                self._serial = None
                calls.append(("target-close", self.device["id"]))

            def write_single_register(self, address, value):
                calls.append(("target-write", self.device["id"], self.device["slaveId"], address, value))

        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1", "slaveId": 2})
        service._device_slots["dev-a"]["state"]["running"] = True
        service._port_runners["COM1"] = {"client": ActiveClient(), "device_ids": ["dev-a", "dev-b"]}

        with patch.object(live_acquisition_service, "LiveModbusClient", TargetClient):
            payload = service.write_value("dev-a", "holding.sensor_1.modbus_address", 55)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["item"]["currentValue"], 55)
        self.assertIn(("active-close",), calls)
        self.assertIn(("target-open", "dev-a", 2), calls)
        self.assertIn(("target-write", "dev-a", 2, 102, 55), calls)
        self.assertIn(("target-close", "dev-a"), calls)
        self.assertIsNone(service._port_runners["COM1"]["client"])

    def test_poll_slow_group_opens_target_device_client_immediately(self):
        calls = []

        class ActiveClient:
            def __init__(self):
                self._serial = object()

            def close(self):
                self._serial = None
                calls.append(("active-close",))

        class TargetClient:
            def __init__(self, device):
                self.device = device
                self._serial = None

            def set_trace_callback(self, callback):
                self.callback = callback

            def open(self):
                self._serial = object()
                calls.append(("target-open", self.device["id"], self.device["slaveId"]))

            def close(self):
                self._serial = None
                calls.append(("target-close", self.device["id"]))

            def read_holding_registers(self, address, count):
                calls.append(("target-read-holding", self.device["id"], self.device["slaveId"], address, count))
                return [0] * count

        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1", "slaveId": 2})
        service._device_slots["dev-a"]["state"]["running"] = True
        service._port_runners["COM1"] = {"client": ActiveClient(), "device_ids": ["dev-a", "dev-b"]}

        with patch.object(live_acquisition_service, "LiveModbusClient", TargetClient):
            payload = service.poll_slow_group("dev-a")

        self.assertTrue(payload["ok"])
        self.assertIn(("active-close",), calls)
        self.assertIn(("target-open", "dev-a", 2), calls)
        self.assertTrue(any(call[:3] == ("target-read-holding", "dev-a", 2) for call in calls))
        self.assertIn(("target-close", "dev-a"), calls)
        self.assertIsNone(service._port_runners["COM1"]["client"])

    def test_send_debug_frame_records_global_traffic(self):
        calls = []

        class FakeClient:
            def __init__(self, device):
                self.device = device
                self.callback = None
                self._serial = None

            def set_trace_callback(self, callback):
                self.callback = callback

            def open(self):
                self._serial = object()
                calls.append(("open", self.device["id"]))

            def close(self):
                self._serial = None
                calls.append(("close", self.device["id"]))

            def send_raw_frame(self, payload, *, append_crc_bytes=False, expect_response=True, response_timeout_ms=None):
                calls.append(("raw", self.device["id"], payload, append_crc_bytes, expect_response, response_timeout_ms))
                if self.callback is not None:
                    self.callback({
                        "kind": "request",
                        "traceId": 7,
                        "attempt": 0,
                        "summary": "RAW bytes 6",
                        "frameHex": bytes(payload).hex(" ").upper(),
                        "port": self.device["address"],
                        "slaveId": self.device["slaveId"],
                    })
                    self.callback({
                        "kind": "response",
                        "traceId": 7,
                        "attempt": 0,
                        "summary": "RAW bytes 5",
                        "frameHex": "01 03 02 00 2A",
                        "port": self.device["address"],
                        "slaveId": self.device["slaveId"],
                    })
                return bytes.fromhex("01 03 02 00 2A")

        service = LiveAcquisitionService()
        device = {"id": "dev-a", "name": "A", "address": "COM1", "slaveId": 2}

        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            payload = service.send_debug_frame(device, "01 03 00 00 00 01", append_crc_bytes=False, expect_response=True, response_timeout_ms=900)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["responseHex"], "01 03 02 00 2A")
        traffic = service.get_command_traffic(limit=20)
        self.assertEqual(len(traffic), 1)
        self.assertEqual(traffic[0]["deviceId"], "dev-a")
        self.assertEqual(traffic[0]["status"], "ok")
        self.assertIn(("raw", "dev-a", bytes.fromhex("010300000001"), False, True, 900), calls)

    def test_run_port_loop_surfaces_modbus_error_details_in_last_error(self):
        class FailingClient:
            def __init__(self, device):
                self.device = device
                self.config = type("Config", (), {"slave_id": int(device.get("slaveId") or 1)})()
                self._serial = None

            def set_trace_callback(self, callback):
                self.callback = callback

            def open(self):
                self._serial = object()

            def close(self):
                self._serial = None

            def read_holding_registers(self, address, count):
                raise ModbusError("crc mismatch")

        service = LiveAcquisitionService()
        device = {
            "id": "dev-a",
            "name": "A",
            "address": "COM1",
            "slaveId": 2,
            "pollingCommands": [
                {
                    "id": "fast",
                    "name": "fast",
                    "autoPoll": True,
                    "functionCode": 3,
                    "address": 1,
                    "count": 1,
                }
            ],
        }
        service._ensure_device_slot(device)
        service._port_runners["COM1"] = {"client": None, "device_ids": ["dev-a"], "device_index": 0}
        stop_event = threading.Event()

        def stop_soon():
            time.sleep(0.15)
            stop_event.set()

        stopper = threading.Thread(target=stop_soon)
        stopper.start()
        try:
            with patch.object(live_acquisition_service, "LiveModbusClient", FailingClient):
                service._run_port_loop("COM1", [device], stop_event)
        finally:
            stopper.join()

        state = service._device_slots["dev-a"]["state"]
        self.assertEqual(state["last_error"], "read failed for fast: crc mismatch")
        self.assertEqual(state["consecutive_error_count"], 1)

    def test_clear_command_traffic_resets_global_log(self):
        service = LiveAcquisitionService()
        service._record_command_trace(
            "dev-a",
            {
                "kind": "request",
                "traceId": 1,
                "attempt": 0,
                "summary": "RAW bytes 2",
                "frameHex": "01 03",
                "port": "COM1",
                "slaveId": 1,
            },
            device_override={"id": "dev-a", "name": "A", "address": "COM1", "slaveId": 1},
        )

        self.assertEqual(len(service.get_command_traffic(limit=10)), 1)
        service.clear_command_traffic()
        self.assertEqual(service.get_command_traffic(limit=10), [])

    def test_command_traffic_marks_missing_reply_and_keeps_latest_1000(self):
        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})

        for index in range(1005):
            service._record_command_trace(
                "dev-a",
                {
                    "kind": "request",
                    "traceId": index + 1,
                    "attempt": 0,
                    "summary": f"FC03 addr {index}",
                    "frameHex": f"{index:04X}",
                    "port": "COM1",
                    "slaveId": 1,
                },
            )
        service._record_command_trace(
            "dev-a",
            {
                "kind": "no_response",
                "traceId": 1005,
                "attempt": 0,
                "error": "timeout waiting for response",
                "port": "COM1",
                "slaveId": 1,
            },
        )

        rows = service.get_command_traffic(device_id="dev-a", limit=1000)
        self.assertEqual(len(rows), 1000)
        self.assertEqual(rows[0]["traceId"], 6)
        self.assertEqual(rows[-1]["traceId"], 1005)
        self.assertEqual(rows[-1]["status"], "no_response")
        self.assertEqual(rows[-1]["error"], "timeout waiting for response")

    def test_start_all_enabled_devices(self):
        service = LiveAcquisitionService()
        devices = [
            {"id": "dev-a", "name": "A", "address": "COM1", "enabled": True},
            {"id": "dev-b", "name": "B", "address": "COM1", "enabled": False},
            {"id": "dev-c", "name": "C", "address": "COM7", "enabled": True},
        ]
        try:
            state = service.start_all(devices)
            self.assertTrue(state["running"])
            self.assertEqual(state["device_count"], 2)
            self.assertEqual(sorted(state["device_ids"]), ["dev-a", "dev-c"])

            status = service.get_status()
            self.assertTrue(status["running"])

            with self._lock_context(service) as _:
                self.assertIn("COM1", service._port_runners)
                self.assertIn("COM7", service._port_runners)
                self.assertEqual(service._port_runners["COM1"]["device_ids"], ["dev-a"])
                self.assertEqual(service._port_runners["COM7"]["device_ids"], ["dev-c"])
        finally:
            service.stop_all()

    def test_same_port_devices_sequential_in_runner(self):
        service = LiveAcquisitionService()
        devices = [
            {"id": "dev-1", "name": "D1", "address": "COM1", "enabled": True},
            {"id": "dev-2", "name": "D2", "address": "COM1", "enabled": True},
        ]
        try:
            service.start_all(devices)
            with self._lock_context(service) as _:
                self.assertEqual(len(service._port_runners), 1)
                runner = service._port_runners["COM1"]
                self.assertEqual(runner["device_ids"], ["dev-1", "dev-2"])
        finally:
            service.stop_all()

    def test_status_stale_window_scales_for_many_devices_on_one_port(self):
        device = {
            "id": "dev-a",
            "address": "COM1",
            "timeoutMs": 1200,
            "retryCount": 2,
            "pollingSettings": {
                "fast": {"intervalMs": 100},
                "standard": {"intervalMs": 200},
            },
        }

        stale_after_ms = LiveAcquisitionService._estimate_status_stale_after_ms(device, same_port_count=10)

        self.assertGreaterEqual(stale_after_ms, 72000)

    def test_health_does_not_mark_stale_success_as_error_without_consecutive_failures(self):
        state = {
            "running": True,
            "last_success_at": (datetime.now() - timedelta(seconds=20)).isoformat(sep=" "),
            "last_error": None,
            "last_error_at": None,
            "consecutive_error_count": 0,
            "status_stale_after_ms": 15000,
        }

        health, text = LiveAcquisitionService._compute_health(state, datetime.now())

        self.assertEqual(health, "pending")
        self.assertEqual(text, "等待下一轮数据")

    def test_health_marks_consecutive_failures_as_error(self):
        state = {
            "running": True,
            "last_success_at": (datetime.now() - timedelta(seconds=60)).isoformat(sep=" "),
            "last_error": "read failed for fast",
            "last_error_at": datetime.now().isoformat(sep=" "),
            "consecutive_error_count": 3,
            "status_stale_after_ms": 15000,
        }

        health, text = LiveAcquisitionService._compute_health(state, datetime.now())

        self.assertEqual(health, "error")
        self.assertEqual(text, "连续通信异常")

    def test_snapshot_returns_device_specific_data(self):
        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        service._device_slots["dev-a"]["values"]["input_register.temperature"] = {"value": 25.5, "ts": "2025-01-01 12:00:00"}
        service._device_slots["dev-a"]["state"]["last_snapshot_at"] = "2025-01-01 12:00:00"
        service._device_slots["dev-a"]["state"].update({
            "running": True,
            "last_success_at": datetime.now().isoformat(sep=" "),
            "consecutive_error_count": 0,
        })

        snapshot = service.get_snapshot(device_id="dev-a")
        self.assertEqual(snapshot["deviceId"], "dev-a")
        self.assertGreater(len(snapshot["metrics"]), 0)
        self.assertEqual(snapshot["session"]["communication_health"], "ok")

        snapshot_none = service.get_snapshot(device_id="dev-b")
        self.assertEqual(snapshot_none["metrics"], [])
        self.assertEqual(snapshot_none["deviceId"], "dev-b")

    def test_series_returns_device_specific_data(self):
        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        service._device_slots["dev-a"]["history"]["sensor_1.temperature"].append({
            "ts": "2025-01-01 12:00:00",
            "value": 25.5,
            "epoch": time.time(),
        })
        service._device_slots["dev-a"]["history"]["sensor_3.humidity"].append({
            "ts": "2025-01-01 12:00:00",
            "value": 63.5,
            "epoch": time.time(),
        })

        series = service.get_series(device_id="dev-a", window_ms=60000)
        self.assertGreater(len(series["rows"]), 0)
        self.assertEqual(series["byMetric"]["sensor_3.humidity"][0]["value"], 63.5)

        series_none = service.get_series(device_id="dev-b")
        self.assertEqual(series_none["rows"], [])

    def test_series_accepts_an_arbitrary_time_range(self):
        service = LiveAcquisitionService()
        service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1"})
        history = service._device_slots["dev-a"]["history"]["pressure"]
        history.extend([
            {"ts": "2026-07-20 10:00:00", "value": 1.0, "epoch": datetime(2026, 7, 20, 10, 0, 0).timestamp()},
            {"ts": "2026-07-20 11:00:00", "value": 2.0, "epoch": datetime(2026, 7, 20, 11, 0, 0).timestamp()},
            {"ts": "2026-07-20 12:00:00", "value": 3.0, "epoch": datetime(2026, 7, 20, 12, 0, 0).timestamp()},
        ])

        series = service.get_series(
            "dev-a",
            start_at="2026-07-20 10:30:00",
            end_at="2026-07-20 11:30:00",
        )

        self.assertEqual([row["value"] for row in series["byMetric"]["pressure"]], [2.0])
        self.assertEqual(series["range"]["start"], "2026-07-20 10:30:00")

    @staticmethod
    def _lock_context(service):
        return service._lock


if __name__ == "__main__":
    unittest.main()
