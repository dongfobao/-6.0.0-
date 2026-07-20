from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from typing import Any

try:
    import serial
except Exception:  # pragma: no cover - environment dependent
    serial = None


class ModbusError(Exception):
    pass


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def append_crc(data: bytes) -> bytes:
    crc = crc16_modbus(data)
    return data + bytes((crc & 0xFF, (crc >> 8) & 0xFF))


@dataclass
class SerialConfig:
    port: str
    slave_id: int
    baudrate: int
    databits: int
    stopbits: int
    parity: str
    timeout_ms: int
    retry_count: int

    @classmethod
    def from_device(cls, device: dict[str, Any]) -> "SerialConfig":
        return cls(
            port=str(device.get("address") or "").strip(),
            slave_id=max(1, min(247, int(device.get("slaveId") or 1))),
            baudrate=max(1200, int(device.get("baudrate") or 9600)),
            databits=int(device.get("databits") or 8),
            stopbits=int(device.get("stopbits") or 1),
            parity=str(device.get("parity") or "N").upper(),
            timeout_ms=max(100, int(device.get("timeoutMs") or 1200)),
            retry_count=max(0, int(device.get("retryCount") or 0)),
        )


class LiveModbusClient:
    def __init__(self, device: dict[str, Any]) -> None:
        self.config = SerialConfig.from_device(device)
        self._serial: Any | None = None
        self._trace_callback: Any | None = None
        self._trace_seq = 0

    def set_trace_callback(self, callback: Any | None) -> None:
        self._trace_callback = callback

    def set_slave_id(self, slave_id: int) -> None:
        self.config.slave_id = max(1, min(247, int(slave_id)))

    def open(self) -> None:
        if self._serial is not None and getattr(self._serial, "is_open", False):
            return
        if serial is None:
            raise ModbusError("pyserial module is not available")
        try:
            self._serial = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baudrate,
                bytesize=self.config.databits,
                parity=self.config.parity,
                stopbits=self.config.stopbits,
                timeout=self.config.timeout_ms / 1000.0,
                write_timeout=self.config.timeout_ms / 1000.0,
            )
        except Exception as exc:
            raise ModbusError(f"failed to open serial port {self.config.port}: {exc}") from exc

    def close(self) -> None:
        if self._serial is None:
            return
        try:
            self._serial.close()
        except Exception:
            pass
        finally:
            self._serial = None

    def __enter__(self) -> "LiveModbusClient":
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def read_coils(self, address: int, count: int) -> list[bool]:
        return self._read_bits(1, address, count)

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        return self._read_bits(2, address, count)

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        return self._read_registers(3, address, count)

    def read_input_registers(self, address: int, count: int) -> list[int]:
        return self._read_registers(4, address, count)

    def write_single_coil(self, address: int, value: bool) -> None:
        payload = struct.pack(">B B H H", self.config.slave_id, 5, address, 0xFF00 if value else 0x0000)
        response = self._request(payload, minimum_length=8)
        if response[:6] != payload[:6]:
            raise ModbusError("unexpected response payload for write single coil")

    def write_single_register(self, address: int, value: int) -> None:
        payload = struct.pack(">B B H H", self.config.slave_id, 6, address, int(value) & 0xFFFF)
        response = self._request(payload, minimum_length=8)
        if response[:6] != payload[:6]:
            raise ModbusError("unexpected response payload for write single register")

    def write_multiple_registers(self, address: int, values: list[int]) -> None:
        if not values:
            raise ModbusError("register values are required")
        if len(values) > 123:
            raise ModbusError(f"invalid register count: {len(values)}")
        word_count = len(values)
        byte_count = word_count * 2
        payload = struct.pack(">B B H H B", self.config.slave_id, 16, address, word_count, byte_count)
        payload += struct.pack(f">{word_count}H", *[int(value) & 0xFFFF for value in values])
        response = self._request(payload, minimum_length=8)
        expected = struct.pack(">B B H H", self.config.slave_id, 16, address, word_count)
        if response[:6] != expected[:6]:
            raise ModbusError("unexpected response payload for write multiple registers")

    def send_raw_frame(
        self,
        frame: bytes,
        *,
        append_crc_bytes: bool = False,
        expect_response: bool = True,
        response_timeout_ms: int | None = None,
    ) -> bytes | None:
        raw_frame = bytes(frame or b"")
        if not raw_frame:
            raise ModbusError("raw frame is required")
        self.open()
        assert self._serial is not None
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()
        trace_id = self._next_trace_id()
        tx_frame = append_crc(raw_frame) if append_crc_bytes else raw_frame
        self._emit_trace("request", trace_id, tx_frame, 0, summary=f"RAW bytes {len(tx_frame)}")
        self._serial.write(tx_frame)
        self._serial.flush()
        if not expect_response:
            self._emit_trace("sent", trace_id, None, 0, summary="manual send only")
            return None
        try:
            response = self._read_raw_response(response_timeout_ms=response_timeout_ms)
            self._emit_trace("response", trace_id, response, 0, summary=f"RAW bytes {len(response)}")
            return response
        except Exception as exc:
            self._emit_trace("no_response", trace_id, None, 0, error=str(exc))
            raise ModbusError(str(exc)) from exc

    def _read_bits(self, function_code: int, address: int, count: int) -> list[bool]:
        if count < 1 or count > 2000:
            raise ModbusError(f"invalid bit count: {count}")
        payload = struct.pack(">B B H H", self.config.slave_id, function_code, address, count)
        response = self._request(payload, minimum_length=5)
        byte_count = response[2]
        expected_length = 3 + byte_count + 2
        if len(response) != expected_length:
            raise ModbusError(f"unexpected response length for fc={function_code}: {len(response)}")
        values: list[bool] = []
        for offset in range(count):
            byte_index = 3 + (offset // 8)
            bit_index = offset % 8
            values.append(bool((response[byte_index] >> bit_index) & 0x01))
        return values

    def _read_registers(self, function_code: int, address: int, count: int) -> list[int]:
        if count < 1 or count > 125:
            raise ModbusError(f"invalid register count: {count}")
        payload = struct.pack(">B B H H", self.config.slave_id, function_code, address, count)
        response = self._request(payload, minimum_length=5)
        byte_count = response[2]
        expected_bytes = count * 2
        if byte_count != expected_bytes:
            raise ModbusError(
                f"unexpected register byte count for fc={function_code}: expected {expected_bytes}, got {byte_count}"
            )
        expected_length = 3 + byte_count + 2
        if len(response) != expected_length:
            raise ModbusError(f"unexpected response length for fc={function_code}: {len(response)}")
        registers = []
        for index in range(count):
            start = 3 + index * 2
            registers.append(struct.unpack(">H", response[start : start + 2])[0])
        return registers

    def _request(self, payload: bytes, minimum_length: int) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.config.retry_count + 1):
            trace_id = self._next_trace_id()
            response: bytes | None = None
            try:
                self.open()
                assert self._serial is not None
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
                frame = append_crc(payload)
                self._emit_trace("request", trace_id, frame, attempt, summary=self._summarize_request(payload))
                self._serial.write(frame)
                self._serial.flush()
                response = self._read_response(minimum_length)
                self._emit_trace("response", trace_id, response, attempt, summary=self._summarize_response(response))
                self._validate_response(payload, response)
                return response
            except Exception as exc:
                last_error = exc
                if response is None:
                    self._emit_trace("no_response", trace_id, None, attempt, error=str(exc))
                else:
                    self._emit_trace("error", trace_id, response, attempt, error=str(exc))
                self.close()
                if attempt < self.config.retry_count:
                    time.sleep(0.05)
        raise ModbusError(str(last_error) if last_error is not None else "modbus request failed")

    def _read_response(self, minimum_length: int) -> bytes:
        assert self._serial is not None
        deadline = time.monotonic() + (self.config.timeout_ms / 1000.0)
        buffer = bytearray()
        while time.monotonic() < deadline:
            waiting = getattr(self._serial, "in_waiting", 0) or 1
            chunk = self._serial.read(waiting)
            if chunk:
                buffer.extend(chunk)
                if len(buffer) >= minimum_length:
                    if self._is_frame_complete(bytes(buffer)):
                        return bytes(buffer)
            else:
                time.sleep(0.005)
        if buffer:
            return bytes(buffer)
        raise ModbusError("timeout waiting for response")

    def _read_raw_response(self, response_timeout_ms: int | None = None, idle_gap_ms: int = 40) -> bytes:
        assert self._serial is not None
        timeout_ms = max(50, int(response_timeout_ms or self.config.timeout_ms))
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        idle_gap_sec = max(0.01, idle_gap_ms / 1000.0)
        buffer = bytearray()
        last_data_at: float | None = None
        while time.monotonic() < deadline:
            waiting = getattr(self._serial, "in_waiting", 0) or 0
            chunk = self._serial.read(waiting or 1)
            if chunk:
                buffer.extend(chunk)
                last_data_at = time.monotonic()
                continue
            if buffer and last_data_at is not None and (time.monotonic() - last_data_at) >= idle_gap_sec:
                return bytes(buffer)
            time.sleep(0.005)
        if buffer:
            return bytes(buffer)
        raise ModbusError("timeout waiting for response")

    @staticmethod
    def _is_frame_complete(frame: bytes) -> bool:
        if len(frame) < 5:
            return False
        function_code = frame[1]
        if function_code & 0x80:
            return len(frame) >= 5
        if function_code in {5, 6, 15, 16}:
            return len(frame) >= 8
        byte_count = frame[2]
        expected_length = 3 + byte_count + 2
        return len(frame) >= expected_length

    def _validate_response(self, request_payload: bytes, response: bytes) -> None:
        if len(response) < 5:
            raise ModbusError(f"response too short: {len(response)}")
        expected_crc = crc16_modbus(response[:-2])
        actual_crc = response[-2] | (response[-1] << 8)
        if expected_crc != actual_crc:
            raise ModbusError("crc mismatch")
        slave_id = request_payload[0]
        function_code = request_payload[1]
        if response[0] != slave_id:
            raise ModbusError(f"unexpected slave id: {response[0]}")
        if response[1] == (function_code | 0x80):
            raise ModbusError(f"modbus exception code: {response[2]}")
        if response[1] != function_code:
            raise ModbusError(f"unexpected function code: {response[1]}")

    def _next_trace_id(self) -> int:
        self._trace_seq += 1
        return self._trace_seq

    def _emit_trace(
        self,
        kind: str,
        trace_id: int,
        frame: bytes | None,
        attempt: int,
        *,
        summary: str | None = None,
        error: str | None = None,
    ) -> None:
        if self._trace_callback is None:
            return
        self._trace_callback(
            {
                "kind": kind,
                "traceId": trace_id,
                "attempt": attempt,
                "summary": summary,
                "frameHex": frame.hex(" ").upper() if frame is not None else None,
                "error": error,
                "port": self.config.port,
                "slaveId": self.config.slave_id,
            }
        )

    @staticmethod
    def _summarize_request(payload: bytes) -> str:
        if len(payload) < 2:
            return "request"
        fc = payload[1]
        if fc in {1, 2, 3, 4} and len(payload) >= 6:
            address = int.from_bytes(payload[2:4], "big")
            count = int.from_bytes(payload[4:6], "big")
            return f"FC{fc:02d} addr {address} count {count}"
        if fc in {5, 6} and len(payload) >= 6:
            address = int.from_bytes(payload[2:4], "big")
            value = int.from_bytes(payload[4:6], "big")
            return f"FC{fc:02d} addr {address} value {value}"
        if fc in {15, 16} and len(payload) >= 6:
            address = int.from_bytes(payload[2:4], "big")
            count = int.from_bytes(payload[4:6], "big")
            return f"FC{fc:02d} addr {address} count {count}"
        return f"FC{fc:02d}"

    @staticmethod
    def _summarize_response(response: bytes) -> str:
        if len(response) < 2:
            return "response"
        fc = response[1]
        if fc & 0x80 and len(response) >= 3:
            return f"FC{fc & 0x7F:02d} exception {response[2]}"
        if fc in {5, 6, 15, 16} and len(response) >= 6:
            address = int.from_bytes(response[2:4], "big")
            value = int.from_bytes(response[4:6], "big")
            return f"FC{fc:02d} ack {address} / {value}"
        if len(response) >= 3:
            return f"FC{fc:02d} bytes {response[2]}"
        return f"FC{fc:02d}"
