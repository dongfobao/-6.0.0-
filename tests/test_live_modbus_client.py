from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_modbus_client import LiveModbusClient, ModbusError, SerialConfig, append_crc


class _FakeSerial:
    is_open = True

    def reset_input_buffer(self):
        return None

    def reset_output_buffer(self):
        return None

    def write(self, data):
        return len(data)

    def flush(self):
        return None

    def close(self):
        self.is_open = False


class LiveModbusClientTests(unittest.TestCase):
    def _client(self) -> LiveModbusClient:
        return LiveModbusClient({"address": "COM1", "slaveId": 1})

    def test_serial_config_rejects_empty_port_and_zero_values(self):
        with self.assertRaises(ModbusError):
            SerialConfig.from_device({"address": "", "slaveId": 1})
        with self.assertRaises(ModbusError):
            SerialConfig.from_device({"address": "COM1", "slaveId": 0})
        with self.assertRaises(ModbusError):
            SerialConfig.from_device({"address": "COM1", "timeoutMs": 0})

    def test_register_writes_reject_wrapping_and_fractional_values(self):
        client = self._client()
        client._request = lambda payload, minimum_length: append_crc(payload)
        for value in (-1, 65536, 1.5):
            with self.assertRaises(ModbusError):
                client.write_single_register(1, value)
        with self.assertRaises(ModbusError):
            client.write_multiple_registers(1, [1, -1])

    def test_register_writes_reject_responses_with_trailing_bytes(self):
        client = self._client()
        client._request = lambda payload, minimum_length: payload[:6] + b"\x00\x00\x00\x00"
        with self.assertRaises(ModbusError):
            client.write_single_register(1, 2)
        with self.assertRaises(ModbusError):
            client.write_multiple_registers(1, [2, 3])

    def test_fc02_rejects_wrong_byte_count(self):
        client = self._client()
        client._request = lambda payload, minimum_length: b"\x01\x02\x01\x00\x00\x00"
        with self.assertRaises(ModbusError):
            client.read_discrete_inputs(0, 9)

    def test_raw_response_requires_crc_slave_function_and_length(self):
        request = bytes.fromhex("01 03 00 00 00 01")
        client = self._client()
        client._serial = _FakeSerial()
        traces = []
        client.set_trace_callback(traces.append)

        client._read_raw_response = lambda **_: bytes.fromhex("01 03 02 00 01 00 00")
        with self.assertRaises(ModbusError):
            client.send_raw_frame(request, append_crc_bytes=True)
        self.assertEqual(traces[-1]["kind"], "error")

        client._read_raw_response = lambda **_: append_crc(bytes.fromhex("02 03 02 00 01"))
        with self.assertRaises(ModbusError):
            client.send_raw_frame(request, append_crc_bytes=True)


if __name__ == "__main__":
    unittest.main()
