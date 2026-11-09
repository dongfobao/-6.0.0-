from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import live_acquisition_service
from live_acquisition_service import LiveAcquisitionService
from live_modbus_client import ModbusError
from live_register_catalog import PROTOCOL_VERSION_WORD, get_register_item
from modbus_v10_codec import encode_words
from modbus_v10_config import V10ConfigTransaction


class FakeClient:
    calls = []
    coils = {}
    holding = {}
    generation = 10

    def __init__(self, device): self.device = device
    def open(self): self.calls.append(("open", self.device.get("id")))
    def close(self): self.calls.append(("close", self.device.get("id")))
    def read_input_registers(self, address, count):
        values = [0] * count
        if address == 100:
            values[0] = PROTOCOL_VERSION_WORD
            if count >= 16: values[14] = self.generation
        if address == 112 and count == 2:
            values = [self.holding.get(16, 0), self.holding.get(17, 0)]
        return values
    def read_discrete_inputs(self, address, count): return [False] * count
    def read_coils(self, address, count): return [bool(self.coils.get(address + i, False)) for i in range(count)]
    def read_holding_registers(self, address, count): return [int(self.holding.get(address + i, 0)) for i in range(count)]
    def write_single_coil(self, address, value): self.coils[address] = bool(value); self.calls.append(("fc05", address, bool(value)))
    def write_multiple_coils(self, address, values):
        for i, value in enumerate(values): self.coils[address + i] = bool(value)
        self.calls.append(("fc15", address, list(values)))
    def write_single_register(self, address, value): self.holding[address] = int(value); self.generation += 1; self.calls.append(("fc06", address, int(value)))
    def write_multiple_registers(self, address, values):
        for i, value in enumerate(values): self.holding[address + i] = int(value)
        if address != 16: self.generation += 1
        self.calls.append(("fc16", address, list(values)))


class LiveAcquisitionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClient.calls, FakeClient.coils, FakeClient.holding, FakeClient.generation = [], {}, {}, 10
        self.service = LiveAcquisitionService()
        self.slot = self.service._ensure_device_slot({"id": "dev-a", "name": "A", "address": "COM1", "slaveId": 1})
        self.slot["state"]["running"] = True

    def test_protocol_word_is_checked_at_ir100(self) -> None:
        command = next(x for x in self.service._default_polling_commands if x["functionCode"] == 4 and x["address"] == 100)
        block = self.service._command_to_block(command)
        with self.assertRaises(ModbusError): self.service._apply_block_values("dev-a", self.slot, block, [0x0A00] + [0] * 35)
        self.service._apply_block_values("dev-a", self.slot, block, [PROTOCOL_VERSION_WORD] + [0] * 36)
        self.assertFalse(self.slot["protocol_rejected"])

    def test_absolute_humidity_uses_existing_points_and_decodes_nan_as_missing(self) -> None:
        points = {1: (18, 12.77), 2: (22, None), 3: (2, 0.0)}
        for channel, (address, expected) in points.items():
            point_id = f"input_register.sensor_{channel}.humidity"
            point = get_register_item(point_id)
            self.assertEqual(point["address"], address)
            self.assertEqual(point["unit"], "g/m³")
            command = next(x for x in self.service._default_polling_commands
                           if point_id in x["catalogItemIds"])
            block = self.service._command_to_block(command)
            raw = [0] * command["count"]
            offset = address - command["address"]
            raw[offset:offset + 2] = [0x7FC0, 0] if expected is None else encode_words(expected, "float32")
            self.service._apply_block_values("dev-a", self.slot, block, raw)
            self.assertEqual(self.slot["values"][point_id]["value"], expected)

    def test_mandatory_di_semantics_are_decoded_per_row(self) -> None:
        command = next(x for x in self.service._default_polling_commands if x["functionCode"] == 2 and x["address"] == 0)
        block = self.service._command_to_block(command)
        raw = [False] * 20
        raw[1], raw[6], raw[8], raw[17], raw[18], raw[19] = True, True, True, False, False, True
        self.service._apply_block_values("dev-a", self.slot, block, raw)
        values = self.slot["values"]
        self.assertTrue(values["input_register.output.htc1_state"]["value"])
        self.assertTrue(values["discrete_input.breath.inhale"]["value"])
        self.assertTrue(values["discrete_input.alarm.any"]["value"])
        self.assertTrue(values["input_register.sensor_3.read_ok"]["value"])
        self.assertTrue(values["discrete_input.pressure.read_ok"]["value"])
        self.assertFalse(values["discrete_input.flow.read_ok"]["value"])

    def test_runtime_single_coil_uses_fc05_and_readback(self) -> None:
        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            result = self.service.write_value("dev-a", "holding.runtime.remote_heat", True)
        self.assertIn(("fc05", 0, True), FakeClient.calls)
        self.assertTrue(result["runtimeFeedback"]["holding.runtime.remote_heat"])

    def test_runtime_pair_control_uses_fc15_and_complete_pair(self) -> None:
        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            result = self.service.write_value("dev-a", "holding.runtime.htc1_mode", 2)
        self.assertIn(("fc15", 16, [1, 1]), FakeClient.calls)
        self.assertEqual(result["runtimeFeedback"]["holding.runtime.htc1_mode"], 2)

    def test_valve_pair_control_is_read_back(self) -> None:
        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            result = self.service.write_value("dev-a", "holding.runtime.valve_1", 1)
        self.assertIn(("fc15", 24, [1, 0]), FakeClient.calls)
        self.assertEqual(result["runtimeFeedback"]["holding.runtime.valve_1"], 1)

    def test_valve_home_calibration_uses_independent_pulse_coils(self) -> None:
        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            for channel, address in enumerate((8, 9, 10), start=1):
                point_id = f"holding.runtime.valve_{channel}_calibrate"
                result = self.service.write_runtime_control("dev-a", point_id, 1)
                self.assertIn(("fc05", address, True), FakeClient.calls)
                self.assertEqual(result["runtimeFeedback"], {})
                self.assertNotIn(point_id, self.slot["values"])

    def test_persistent_config_uses_hr_and_updates_generation(self) -> None:
        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            result = self.service.stage_config_value("dev-a", "holding.logging.retention_days", 60)
        self.assertIn(("fc06", 10, 60), FakeClient.calls)
        self.assertTrue(result["persisted"])
        self.assertEqual(result["value"], 60)

    def test_rtc_sync_uses_fc16_and_current_time_feedback_without_config_save(self) -> None:
        epoch = 1791446400
        with patch.object(live_acquisition_service, "LiveModbusClient", FakeClient):
            result = self.service.sync_rtc_from_epoch("dev-a", epoch)
        self.assertIn(("fc16", 16, [epoch >> 16, epoch & 0xFFFF]), FakeClient.calls)
        self.assertEqual(result["deviceEpoch"], epoch)
        self.assertEqual(FakeClient.generation, 10)
        self.assertNotIn("transaction", result)

    def test_rtc_sync_rejects_wrong_feedback(self) -> None:
        class WrongRtcClient(FakeClient):
            def read_input_registers(self, address, count):
                return [0, 0] if address == 112 else super().read_input_registers(address, count)

        with patch.object(live_acquisition_service, "LiveModbusClient", WrongRtcClient):
            with self.assertRaisesRegex(ModbusError, "RTC校时回读不一致"):
                self.service.sync_rtc_from_epoch("dev-a", 1791446400)

    def test_schedule_result_exposes_selected_fixed_slot(self) -> None:
        self.slot["selected_schedule_task"] = 2
        self.slot["values"]["holding.schedule.slot_2.start_month"] = {"value": 9, "ts": "now"}
        self.slot["values"]["holding.schedule.slot_2.duration_seconds"] = {"value": 345600, "ts": "now"}
        result = self.service._schedule_result(self.slot)
        by_id = {x["id"]: x for x in result["config"]}
        self.assertEqual(result["taskCount"], 12)
        self.assertEqual(by_id["holding.schedule.selected_task"]["currentValue"], 2)
        self.assertEqual(by_id["holding.schedule.start_month"]["currentValue"], 9)
        self.assertEqual(by_id["holding.schedule.duration_days"]["currentValue"], 4)

    def test_schedule_accepts_falling_stop_above_start_threshold(self) -> None:
        payload = {
            "taskNumber": 1,
            "month": 4,
            "day": 1,
            "hour": 8,
            "minute": 30,
            "durationDays": 4,
            "enabled": True,
            "humidityOverrideEnabled": True,
            "humidityStartThreshold": [10, 10],
            "humidityFallingStopThreshold": [80, 80],
            "humidityPeakDropThreshold": [5, 5],
        }
        with (
            patch.object(live_acquisition_service, "LiveModbusClient", FakeClient),
            patch.object(V10ConfigTransaction, "_wait_for_save", return_value=None) as wait_for_save,
        ):
            result = self.service.stage_schedule_task("dev-a", payload)
        self.assertTrue(result["ok"])
        self.assertTrue(any(call[0:2] == ("fc16", 512) for call in FakeClient.calls))
        self.assertIn(("fc15", 96, [True, True]), FakeClient.calls)
        self.assertEqual(wait_for_save.call_count, 2)
        self.assertTrue(all(call.kwargs.get("allow_unchanged") for call in wait_for_save.call_args_list))

    def test_parameters_and_snapshot_expose_selected_schedule_aliases(self) -> None:
        self.slot["selected_schedule_task"] = 2
        self.slot["values"]["holding.schedule.slot_2.start_month"] = {"value": 9, "ts": "now"}
        parameters = self.service.get_parameters("dev-a")
        parameter_by_id = {item["id"]: item for item in parameters["config"]}
        snapshot = self.service.get_snapshot("dev-a")
        control_by_id = {item["id"]: item for item in snapshot["controls"]}
        self.assertEqual(parameter_by_id["holding.schedule.selected_task"]["currentValue"], 2)
        self.assertEqual(parameter_by_id["holding.schedule.start_month"]["currentValue"], 9)
        self.assertEqual(control_by_id["holding.schedule.selected_task"]["currentValue"], 2)
        self.assertEqual(control_by_id["holding.schedule.start_month"]["currentValue"], 9)

    def test_debug_endpoint_rejects_writes_and_non_catalog_reads(self) -> None:
        device = {"id": "dev-a", "address": "COM1", "slaveId": 1}
        with self.assertRaises(ValueError): self.service.send_debug_frame(device, "01 06 00 0A 00 01", append_crc_bytes=True)
        with self.assertRaises(ValueError): self.service.send_debug_frame(device, "01 03 00 01 00 01", append_crc_bytes=True)


if __name__ == "__main__":
    unittest.main()
