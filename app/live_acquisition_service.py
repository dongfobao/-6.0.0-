from __future__ import annotations

import threading
import time
from collections import deque
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import re
from typing import Any

from live_modbus_client import LiveModbusClient, ModbusError, append_crc
from live_polling_commands import build_default_polling_commands, normalize_polling_commands
from live_register_catalog import PROTOCOL_VERSION_WORD, get_register_catalog
from live_session_recorder import LiveSessionRecorder
from modbus_v7_codec import decode_words, encode_words
from modbus_v7_config import V7ConfigTransaction


HISTORY_POINT_IDS = (
    "input_register.sensor_1.temperature",
    "input_register.sensor_1.humidity",
    "input_register.sensor_2.temperature",
    "input_register.sensor_2.humidity",
    "input_register.sensor_3.temperature",
    "input_register.sensor_3.humidity",
    "input_register.pressure",
    "input_register.flow",
)

_TIME_CONFIG_UNIT_SECONDS = {
    "holding.flow.no_change_alarm_days": 86400,
    "holding.valve_route.restart_protection_days": 86400,
    "holding.valve_route.force_close_days": 86400,
    "holding.valve_route.cooling_delay_hours": 3600,
    "holding.control.close_delay_hours": 3600,
}


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(sep=" ") if dt else None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _device_port_key(device: dict[str, Any]) -> str:
    address = str(device.get("address") or "").strip()
    return address.upper()


class LiveAcquisitionService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._io_lock = threading.RLock()
        self._catalog = [item for item in get_register_catalog() if item.get("readable")]
        self._catalog_by_id = {item["id"]: dict(item) for item in self._catalog}
        self._default_polling_commands = build_default_polling_commands(self._catalog)
        self._global_state: dict[str, Any] = self._empty_global_state()
        self._device_slots: dict[str, dict[str, Any]] = {}
        self._port_runners: dict[str, dict[str, Any]] = {}
        self._traffic_log: deque[dict[str, Any]] = deque(maxlen=4000)
        self._traffic_id = 0

    @staticmethod
    def _empty_device_slot(device: dict[str, Any]) -> dict[str, Any]:
        return {
            "config": deepcopy(device),
            "values": {},
            "history": {
                point_id.removeprefix("input_register."): deque(maxlen=7200)
                for point_id in HISTORY_POINT_IDS
            },
            "events": deque(maxlen=240),
            "traffic": deque(maxlen=1000),
            "recorder": None,
            "state": LiveAcquisitionService._empty_device_state(device),
            "event_seq": 0,
            "traffic_seq": 0,
        }

    @staticmethod
    def _empty_device_state(device: dict[str, Any]) -> dict[str, Any]:
        return {
            "running": False,
            "device_id": device.get("id"),
            "device_name": device.get("name"),
            "started_at": None,
            "last_error": None,
            "last_error_at": None,
            "last_success_at": None,
            "last_attempt_at": None,
            "error_count": 0,
            "consecutive_error_count": 0,
            "request_count": 0,
            "status_stale_after_ms": 15000,
            "communication_health": "idle",
            "communication_text": "待采集",
            "sample_counts": {
                "metrics": 0,
                "statuses": 0,
                "controls": 0,
                "parameters": 0,
                "history": 0,
            },
            "last_snapshot_at": None,
            "session_dir": None,
        }

    @staticmethod
    def _empty_global_state() -> dict[str, Any]:
        return {
            "running": False,
            "device_count": 0,
            "device_ids": [],
        }

    def _ensure_device_slot(self, device: dict[str, Any]) -> dict[str, Any]:
        device_id = str(device.get("id") or "")
        if not device_id:
            raise ValueError("device must have an id")
        with self._lock:
            if device_id not in self._device_slots:
                self._device_slots[device_id] = self._empty_device_slot(device)
            else:
                self._device_slots[device_id]["config"] = deepcopy(device)
            return self._device_slots[device_id]

    def _get_device_slot(self, device_id: str | None) -> dict[str, Any] | None:
        if not device_id:
            return None
        with self._lock:
            return self._device_slots.get(device_id)

    def _get_device_slot_required(self, device_id: str) -> dict[str, Any]:
        slot = self._get_device_slot(device_id)
        if slot is None:
            raise KeyError(f"no live session for device: {device_id}")
        return slot

    def start_all(
        self,
        devices: list[dict[str, Any]],
        session_root: Path | str | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.stop_all()
        enabled_devices = [d for d in devices if bool(d.get("enabled", True))]
        if not enabled_devices:
            raise ValueError("no enabled devices to start")

        port_groups: dict[str, list[dict[str, Any]]] = {}
        for device in enabled_devices:
            device_id = str(device.get("id") or "")
            if not device_id:
                continue
            port_key = _device_port_key(device)
            port_groups.setdefault(port_key, []).append(device)

        with self._lock:
            self._device_slots.clear()
            self._port_runners.clear()
            started_at = _now()

            for device in enabled_devices:
                device_id = str(device.get("id") or "")
                slot = self._ensure_device_slot(device)
                port_key = _device_port_key(device)
                same_port_count = len(port_groups.get(port_key) or [])
                session_root_path = Path(session_root or ".")
                slot["recorder"] = LiveSessionRecorder(session_root_path, deepcopy(device), config_snapshot=config_snapshot)
                slot["state"].update({
                    "running": True,
                    "device_id": device_id,
                    "device_name": device.get("name"),
                    "started_at": _iso(started_at),
                    "session_dir": str(slot["recorder"].session_dir),
                    "status_stale_after_ms": self._estimate_status_stale_after_ms(device, same_port_count),
                    "communication_health": "starting",
                    "communication_text": "等待首次数据",
                })
                slot["events"].append({
                    "id": slot["event_seq"] + 1,
                    "ts": _iso(_now()),
                    "type": "session_started",
                    "message": f"session started for {device.get('name') or device_id}",
                    "details": {"device_id": device_id},
                })
                slot["event_seq"] += 1

            for port_key, port_devices in port_groups.items():
                stop_event = threading.Event()
                runner: dict[str, Any] = {
                    "thread": None,
                    "stop_event": stop_event,
                    "client": None,
                    "device_ids": [str(d.get("id")) for d in port_devices],
                    "device_index": 0,
                    "port_key": port_key,
                }
                self._port_runners[port_key] = runner

            for port_key, port_devices in port_groups.items():
                runner = self._port_runners[port_key]
                runner["thread"] = threading.Thread(
                    target=self._run_port_loop,
                    args=(port_key, port_devices, runner["stop_event"]),
                    name=f"live-acq-{port_key}",
                    daemon=True,
                )
                runner["thread"].start()

            device_ids = [str(d.get("id")) for d in enabled_devices]
            self._global_state = {
                "running": True,
                "device_count": len(enabled_devices),
                "device_ids": device_ids,
            }
            return deepcopy(self._global_state)

    def stop_all(self) -> dict[str, Any]:
        runners: dict[str, dict[str, Any]] = {}
        with self._lock:
            runners = dict(self._port_runners)

        for port_key, runner in runners.items():
            runner["stop_event"].set()

        for port_key, runner in runners.items():
            thread = runner.get("thread")
            if thread is not None and thread.is_alive():
                thread.join(timeout=10.0)

        with self._lock:
            for port_key, runner in runners.items():
                thread = runner.get("thread")
                if thread is not None and thread.is_alive():
                    continue
                client = runner.get("client")
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass

            for device_id, slot in list(self._device_slots.items()):
                slot["state"]["running"] = False
                slot["events"].append({
                    "id": slot["event_seq"] + 1,
                    "ts": _iso(_now()),
                    "type": "session_stopped",
                    "message": "session stopped by api",
                })
                slot["event_seq"] += 1
                if slot["recorder"] is not None:
                    slot["recorder"].finalize(status="stopped")

            self._port_runners.clear()
            self._global_state["running"] = False
            self._global_state["device_count"] = 0
            self._global_state["device_ids"] = []
            return deepcopy(self._global_state)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._global_state)

    def get_device_status(self, device_id: str | None = None) -> dict[str, Any]:
        if device_id:
            slot = self._get_device_slot(device_id)
            if slot is None:
                return {"running": False, "device_id": device_id}
            with self._lock:
                return self._state_with_health(slot)
        with self._lock:
            return {device_id: self._state_with_health(slot) for device_id, slot in self._device_slots.items()}

    def _state_with_health(self, slot: dict[str, Any]) -> dict[str, Any]:
        state = deepcopy(slot["state"])
        health, text = self._compute_health(state, _now())
        state["communication_health"] = health
        state["communication_text"] = text
        return state

    @staticmethod
    def _compute_health(state: dict[str, Any], now: datetime) -> tuple[str, str]:
        if not state.get("running"):
            return "idle", "待采集"
        last_success = _parse_iso(state.get("last_success_at"))
        last_error = _parse_iso(state.get("last_error_at"))
        stale_after_ms = max(15000, _safe_int(state.get("status_stale_after_ms"), 15000))
        consecutive_errors = max(0, _safe_int(state.get("consecutive_error_count"), 0))
        has_error = bool(state.get("last_error"))

        if last_success is not None:
            age_ms = (now - last_success).total_seconds() * 1000.0
            if age_ms <= stale_after_ms:
                return "ok", "收到数据"
            if consecutive_errors >= 3:
                return "error", "连续通信异常"
            if has_error and last_error is not None:
                return "warn", "部分轮询异常"
            return "pending", "等待下一轮数据"

        if consecutive_errors >= 3:
            return "error", "连续通信异常"
        if has_error:
            return "warn", "等待重试"
        return "starting", "等待首次数据"

    @staticmethod
    def _estimate_status_stale_after_ms(device: dict[str, Any], same_port_count: int) -> int:
        commands = [item for item in normalize_polling_commands(device.get("pollingCommands")) if item.get("autoPoll")]
        timeout_ms = max(100, _safe_int(device.get("timeoutMs"), 1200))
        retry_count = max(0, _safe_int(device.get("retryCount"), 0))
        port_count = max(1, same_port_count)
        worst_request_ms = timeout_ms * (retry_count + 1)
        per_device_delay_ms = sum(max(0, _safe_int(item.get("delayAfterMs"), 0)) for item in commands)
        estimated_cycle_ms = (worst_request_ms * max(1, len(commands)) * port_count) + (per_device_delay_ms * port_count)
        return max(15000, min(120000, int(estimated_cycle_ms)))

    def get_snapshot(self, device_id: str | None = None) -> dict[str, Any]:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return {
                "deviceId": device_id,
                "snapshotAt": None,
                "ts": None,
                "metrics": [],
                "statuses": [],
                "controls": [],
                "session": {"running": False},
            }
        with self._lock:
            metrics = [self._catalog_item_with_value(item, slot["values"]) for item in self._catalog if item.get("area") == "input_register"]
            statuses = [self._catalog_item_with_value(item, slot["values"]) for item in self._catalog if item.get("area") == "discrete_input"]
            controls = [
                self._catalog_item_with_value(item, slot["values"])
                for item in self._catalog
                if item.get("group") in {"control", "config", "task", "runtime_control", "diagnostic"}
            ]
            return {
                "deviceId": device_id,
                "snapshotAt": slot["state"].get("last_snapshot_at"),
                "ts": slot["state"].get("last_snapshot_at"),
                "metrics": metrics,
                "statuses": statuses,
                "controls": controls,
                "session": self._state_with_health(slot),
            }

    def get_series(
        self,
        device_id: str | None = None,
        window_ms: int = 300000,
        limit: int = 300,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> dict[str, Any]:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return {"rows": [], "byMetric": {}, "range": {"start": start_at, "end": end_at}}
        start_time = _parse_iso(start_at)
        end_time = _parse_iso(end_at)
        if start_time is not None and end_time is not None and end_time < start_time:
            raise ValueError("曲线结束时间不能早于开始时间")
        cutoff = start_time.timestamp() if start_time is not None else time.time() - max(1000, window_ms) / 1000.0
        end_epoch = end_time.timestamp() if end_time is not None else float("inf")
        capped_limit = max(1, min(limit, 2000))
        with self._lock:
            by_metric: dict[str, list[dict[str, Any]]] = {}
            for key, rows in slot["history"].items():
                filtered = [dict(row) for row in rows if cutoff <= row["epoch"] <= end_epoch]
                by_metric[key] = filtered[-capped_limit:]

            aggregated: dict[str, dict[str, Any]] = {}
            for metric_key, rows in by_metric.items():
                for row in rows:
                    ts = str(row.get("ts") or "")
                    if not ts:
                        continue
                    entry = aggregated.setdefault(ts, {"ts": ts})
                    entry[metric_key] = row.get("value")
            merged_rows = [aggregated[key] for key in sorted(aggregated.keys())]
            return {
                "rows": merged_rows[-capped_limit:],
                "byMetric": by_metric,
                "range": {
                    "start": _iso(start_time) if start_time is not None else None,
                    "end": _iso(end_time) if end_time is not None else None,
                },
            }

    def get_events(self, device_id: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return []
        capped_limit = max(1, min(limit, 240))
        with self._lock:
            return [dict(item) for item in list(slot["events"])[-capped_limit:]]

    def get_command_traffic(self, device_id: str | None = None, limit: int = 160) -> list[dict[str, Any]]:
        capped_limit = max(1, min(limit, 1000))
        with self._lock:
            if device_id:
                return [dict(item) for item in list(self._traffic_log) if item.get("deviceId") == device_id][-capped_limit:]
            return [dict(item) for item in list(self._traffic_log)[-capped_limit:]]

    def clear_command_traffic(self) -> dict[str, Any]:
        with self._lock:
            self._traffic_log.clear()
            for slot in self._device_slots.values():
                slot["traffic"].clear()
            return {"ok": True, "message": "traffic log cleared"}

    def get_parameters(self, device_id: str | None = None, include_cached: bool = True) -> dict[str, list[dict[str, Any]]]:
        slot = self._get_device_slot(device_id)
        values = slot["values"] if slot is not None else {}
        with self._lock:
            builder = (lambda item: self._catalog_item_with_value(item, values)) if include_cached else self._catalog_item_without_value
            return {
                "config": [
                    builder(item) for item in self._catalog
                    if item.get("area") == "holding_register" and 100 <= int(item.get("address") or 0) < 800
                ],
                "runtime": [builder(item) for item in self._catalog if item.get("group") == "runtime_control"],
                "diagnostic": [builder(item) for item in self._catalog if item.get("group") == "diagnostic"],
                "transaction": [builder(item) for item in self._catalog if item.get("group") == "config_transaction"],
            }

    def write_runtime_control(self, device_id: str, item_id: str, value: Any) -> dict[str, Any]:
        item = self._catalog_by_id.get(item_id)
        if item is None or item.get("group") != "runtime_control":
            raise ValueError(f"不是即时运行控制点: {item_id}")
        return self.write_value(device_id, item_id, value)

    def stage_config_value(self, device_id: str, item_id: str, value: Any) -> dict[str, Any]:
        with self._lock:
            item = dict(self._catalog_by_id.get(item_id) or {})
            slot = self._get_device_slot(device_id)
        if not item:
            raise KeyError(f"未知配置点: {item_id}")
        address = int(item.get("address") or 0)
        if item.get("area") != "holding_register" or not 100 <= address < 800 or not item.get("writable"):
            raise ValueError(f"不是可暂存配置点: {item_id}")
        if slot is None or not slot["state"].get("running"):
            raise ValueError("设备采集会话尚未运行")

        device = deepcopy(slot["config"])
        V7ConfigTransaction._validate_value_range(item, value)
        wire_item, wire_value = self._config_value_to_wire(item, value, slot["values"])
        port_key = _device_port_key(device)
        with self._io_lock:
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                words = V7ConfigTransaction(client).stage_value(wire_item, wire_value)
                decoded = decode_words(words, str(item["dataType"]))
            finally:
                client.close()

        timestamp = _iso(_now())
        with self._lock:
            slot["values"][item_id] = {"value": decoded, "ts": timestamp}
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"], "ts": timestamp, "type": "config_staged",
                "message": f"配置已暂存: {item_id}", "details": {"itemId": item_id, "value": decoded},
            })
        return {"ok": True, "itemId": item_id, "value": self._config_value_from_wire(item, decoded, slot["values"]), "wireValue": decoded, "words": words, "staged": True}

    def execute_config_transaction(self, device_id: str, action: str) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        if not slot["state"].get("running"):
            raise ValueError("设备采集会话尚未运行")
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"commit", "discard"}:
            raise ValueError(f"不支持的配置事务动作: {action}")

        device = deepcopy(slot["config"])
        port_key = _device_port_key(device)
        with self._io_lock:
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                transaction = V7ConfigTransaction(client)
                status = transaction.commit() if normalized_action == "commit" else transaction.discard()
            finally:
                client.close()

        payload = asdict(status)
        timestamp = _iso(_now())
        with self._lock:
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"], "ts": timestamp, "type": f"config_{normalized_action}",
                "message": "配置已提交" if normalized_action == "commit" else "配置暂存已放弃",
                "details": payload,
            })
        return {"ok": True, "action": normalized_action, "status": payload}

    def _close_runner_client_for_port(self, port_key: str) -> None:
        client = None
        with self._lock:
            runner = self._port_runners.get(port_key)
            if runner is not None:
                client = runner.get("client")
                runner["client"] = None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    def _open_manual_client(self, device: dict[str, Any], device_id: str) -> LiveModbusClient:
        client = LiveModbusClient(device)
        if hasattr(client, "set_trace_callback"):
            client.set_trace_callback(lambda p, d=deepcopy(device): self._record_command_trace(device_id, p, device_override=d))
        client.open()
        return client

    def send_debug_frame(
        self,
        device: dict[str, Any],
        request_hex: str,
        *,
        append_crc_bytes: bool = False,
        expect_response: bool = True,
        response_timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        device_id = str(device.get("id") or "")
        if not device_id:
            raise ValueError("device must have an id")
        request_bytes = self._parse_debug_hex(request_hex)
        port_key = _device_port_key(device)
        with self._io_lock:
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                response = client.send_raw_frame(
                    request_bytes,
                    append_crc_bytes=append_crc_bytes,
                    expect_response=expect_response,
                    response_timeout_ms=response_timeout_ms,
                )
            finally:
                client.close()
        return {
            "ok": True,
            "message": expect_response and "debug frame sent" or "debug frame sent without response",
            "requestHex": (append_crc(request_bytes) if append_crc_bytes else request_bytes).hex(" ").upper(),
            "responseHex": response.hex(" ").upper() if response else "",
            "deviceId": device_id,
            "deviceName": device.get("name"),
            "port": device.get("address"),
            "slaveId": device.get("slaveId"),
            "status": expect_response and (response and "ok" or "no_response") or "sent",
        }

    def write_value(self, device_id: str, item_id: str, value: Any) -> dict[str, Any]:
        with self._lock:
            item = dict(self._catalog_by_id.get(item_id) or {})
            slot = self._get_device_slot(device_id)
        if not item:
            raise KeyError(f"unknown live register: {item_id}")
        if not item.get("writable"):
            raise ValueError(f"register is read-only: {item_id}")
        if slot is None or not slot["state"].get("running"):
            raise ValueError("live acquisition session is not running for this device")

        device = deepcopy(slot["config"])
        encoded_words, decoded_value = self._encode_write_value(item, value)
        runtime_feedback: dict[str, Any] = {}

        port_key = _device_port_key(device)
        with self._io_lock:
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                area = str(item.get("area") or "")
                address = int(item.get("address") or 0)
                if area == "holding_register":
                    if len(encoded_words) == 1:
                        client.write_single_register(address, encoded_words[0])
                    else:
                        client.write_multiple_registers(address, encoded_words)
                else:
                    raise ValueError(f"unsupported writable area: {area}")
                if re.fullmatch(r"holding\.runtime\.valve_[1-3]", item_id):
                    runtime_feedback = self._read_runtime_valve_feedback(client)
                    confirmed = runtime_feedback.get(item_id)
                    if confirmed is None or int(confirmed) != int(decoded_value):
                        raise ModbusError(f"阀门命令回读不一致: 写入 {decoded_value}, 回读 {confirmed}")
            finally:
                client.close()

        timestamp = _iso(_now())
        with self._lock:
            slot["values"][item_id] = {"value": decoded_value, "ts": timestamp}
            for feedback_id, feedback_value in runtime_feedback.items():
                slot["values"][feedback_id] = {"value": feedback_value, "ts": timestamp}
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": timestamp,
                "type": "write_success",
                "message": f"wrote {item_id} = {decoded_value}",
                "details": {"itemId": item_id, "value": decoded_value},
            })
            self._log_recorder_for_slot(slot, "I", f"write {item_id} = {decoded_value}")
            row = self._catalog_item_with_value(item, slot["values"])
            return {
                "ok": True,
                "implemented": True,
                "message": f"live value written: {item_id}",
                "item": row,
                "runtimeFeedback": runtime_feedback,
                "session": deepcopy(slot["state"]),
            }

    def _read_runtime_valve_feedback(self, client: LiveModbusClient) -> dict[str, Any]:
        start_address = 804
        words = client.read_holding_registers(start_address, 13)
        feedback: dict[str, Any] = {}
        for item in self._catalog:
            address = int(item.get("address") or -1)
            if item.get("area") != "holding_register" or address < start_address or address > 816:
                continue
            offset = address - start_address
            word_length = int(item.get("wordLength") or 1)
            if offset + word_length > len(words):
                continue
            feedback[str(item["id"])] = self._decode_value(item, words[offset:offset + word_length])
        return feedback

    def get_session_meta(self, device_id: str | None = None) -> dict[str, Any]:
        slot = self._get_device_slot(device_id)
        if slot is None or slot["recorder"] is None:
            return {"available": False, "sessionDir": None, "lastSnapshot": None, "session": {"running": False}}
        with self._lock:
            return {
                "available": True,
                "sessionDir": str(slot["recorder"].session_dir),
                "lastSnapshot": deepcopy(slot["recorder"].last_written_snapshot),
                "session": deepcopy(slot["state"]),
            }

    def export_session(self, device_id: str, export_root: Path | str) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        with self._lock:
            if slot["recorder"] is None:
                raise ValueError(f"no live session recorded for device: {device_id}")
            exported_dir = slot["recorder"].export_to(Path(export_root))
            self._log_recorder_for_slot(slot, "I", f"session exported to {exported_dir}")
            return {
                "sessionDir": str(slot["recorder"].session_dir),
                "exportDir": str(exported_dir),
                "deviceId": device_id,
                "deviceName": slot["config"].get("name"),
            }

    def _catalog_item_with_value(self, item: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        row = dict(item)
        cached = values.get(item["id"]) or {}
        wire_value = cached.get("value")
        row["currentValue"] = self._config_value_from_wire(item, wire_value, values)
        row["value"] = row["currentValue"]
        if item.get("id") in _TIME_CONFIG_UNIT_SECONDS:
            row["wireValue"] = wire_value
            row["legacySecondsWireFormat"] = self._uses_legacy_seconds_wire_format(values)
        row["updatedAt"] = cached.get("ts")
        return row

    def _uses_legacy_seconds_wire_format(self, values: dict[str, Any]) -> bool:
        """旧下位机虽标记为 V7，但仍以秒传输天/小时配置；以量程外原始值识别。"""
        for point_id in _TIME_CONFIG_UNIT_SECONDS:
            raw_value = (values.get(point_id) or {}).get("value")
            maximum = (self._catalog_by_id.get(point_id) or {}).get("maximum")
            if raw_value is None or maximum is None:
                continue
            try:
                if int(raw_value) > int(maximum):
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _config_value_from_wire(self, item: dict[str, Any], wire_value: Any, values: dict[str, Any]) -> Any:
        scale = _TIME_CONFIG_UNIT_SECONDS.get(str(item.get("id") or ""))
        if wire_value is None or scale is None or not self._uses_legacy_seconds_wire_format(values):
            return wire_value
        converted = int(wire_value) / scale
        return int(converted) if converted.is_integer() else converted

    def _config_value_to_wire(self, item: dict[str, Any], value: Any, values: dict[str, Any]) -> tuple[dict[str, Any], Any]:
        scale = _TIME_CONFIG_UNIT_SECONDS.get(str(item.get("id") or ""))
        if scale is None or not self._uses_legacy_seconds_wire_format(values):
            return item, value
        number = float(value)
        if not number.is_integer():
            raise ValueError(f"{item.get('name', item.get('id'))} 只能填写整数{item.get('unit', '')}")
        wire_item = dict(item)
        wire_item.pop("minimum", None)
        wire_item.pop("maximum", None)
        return wire_item, int(number) * scale

    @staticmethod
    def _catalog_item_without_value(item: dict[str, Any]) -> dict[str, Any]:
        row = dict(item)
        row["currentValue"] = None
        row["value"] = None
        row["updatedAt"] = None
        return row

    def _record_command_trace(self, device_id: str, payload: dict[str, Any], device_override: dict[str, Any] | None = None) -> None:
        slot = self._get_device_slot(device_id)
        kind = str(payload.get("kind") or "")
        trace_id = int(payload.get("traceId") or 0)
        timestamp = _iso(_now())
        device = deepcopy(device_override or (slot["config"] if slot is not None else {}))
        with self._lock:
            if kind == "request":
                entry = {
                    "id": self._next_traffic_id(),
                    "traceId": trace_id,
                    "deviceId": device.get("id"),
                    "deviceName": device.get("name"),
                    "port": payload.get("port"),
                    "slaveId": payload.get("slaveId"),
                    "sentAt": timestamp,
                    "replyAt": None,
                    "requestHex": payload.get("frameHex"),
                    "responseHex": None,
                    "requestSummary": payload.get("summary"),
                    "responseSummary": None,
                    "status": "pending",
                    "attempt": int(payload.get("attempt") or 0),
                    "error": None,
                }
                self._traffic_log.append(entry)
                if slot is not None:
                    slot["traffic"].append(entry)
                return
            target = None
            for row in reversed(self._traffic_log):
                if int(row.get("traceId") or 0) == trace_id and str(row.get("deviceId") or "") == str(device_id):
                    target = row
                    break
            if target is None:
                return
            if kind == "response":
                target["replyAt"] = timestamp
                target["responseHex"] = payload.get("frameHex")
                target["responseSummary"] = payload.get("summary")
                target["status"] = "ok"
                target["error"] = None
            elif kind == "sent":
                target["replyAt"] = timestamp
                target["status"] = "sent"
                target["responseSummary"] = payload.get("summary")
                target["error"] = None
            elif kind == "no_response":
                target["replyAt"] = timestamp
                target["status"] = "no_response"
                target["error"] = payload.get("error")
            elif kind == "error":
                target["replyAt"] = timestamp
                target["responseHex"] = payload.get("frameHex")
                target["responseSummary"] = payload.get("summary")
                target["status"] = "error"
                target["error"] = payload.get("error")
            if slot is not None:
                self._write_traffic_to_disk(slot, dict(target))

    def _write_traffic_to_disk(self, slot: dict[str, Any], entry: dict[str, Any]) -> None:
        if slot["recorder"] is not None:
            slot["recorder"].record_traffic_entry(entry)

    def _log_recorder_for_slot(self, slot: dict[str, Any], level: str, message: str) -> None:
        if slot["recorder"] is not None:
            slot["recorder"].record_log(level, _now(), message)

    def _run_port_loop(
        self,
        port_key: str,
        devices: list[dict[str, Any]],
        stop_event: threading.Event,
    ) -> None:
        device_ids = [str(d.get("id")) for d in devices]
        if not device_ids:
            return
        commands_by_device: dict[str, list[dict[str, Any]]] = {}
        command_indexes: dict[str, int] = {}
        for device in devices:
            device_id = str(device.get("id") or "")
            if device_id:
                commands = [item for item in normalize_polling_commands(device.get("pollingCommands"), self._catalog) if item.get("autoPoll")]
                commands_by_device[device_id] = commands
                command_indexes[device_id] = 0

        current_device = devices[0]
        current_device_id = str(current_device.get("id") or "")
        client: LiveModbusClient | None = None
        last_open_error: str | None = None

        def _format_error_message(prefix: str, exc: Exception | None = None) -> str:
            detail = str(exc).strip() if exc is not None else ""
            if not detail or detail == prefix:
                return prefix
            return f"{prefix}: {detail}"

        def open_for(device: dict[str, Any]) -> LiveModbusClient | None:
            nonlocal last_open_error
            try:
                c = LiveModbusClient(device)
                dev_id = str(device.get("id") or "")
                c.set_trace_callback(lambda p, did=dev_id: self._record_command_trace(did, p))
                c.open()
                last_open_error = None
                return c
            except Exception as exc:
                last_open_error = str(exc).strip() or exc.__class__.__name__
                return None

        def ensure_client_for(device: dict[str, Any]) -> LiveModbusClient | None:
            nonlocal client
            if client is not None and getattr(client, "_serial", None) is not None:
                expected_slave = max(1, min(247, int(device.get("slaveId") or 1)))
                if client.config.slave_id != expected_slave:
                    client.set_slave_id(expected_slave)
                dev_id = str(device.get("id") or "")
                client.set_trace_callback(lambda p, did=dev_id: self._record_command_trace(did, p))
                return client
            client = open_for(device)
            if client is not None:
                with self._lock:
                    runner = self._port_runners.get(port_key)
                    if runner is not None:
                        runner["client"] = client
            return client

        def switch_device():
            nonlocal current_device, current_device_id, client
            with self._lock:
                runner = self._port_runners.get(port_key)
                if runner is None:
                    return
                old_index = runner["device_index"]
                runner["device_index"] = (old_index + 1) % len(device_ids)
            new_index = (old_index + 1) % len(devices)
            current_device = devices[new_index]
            current_device_id = str(current_device.get("id") or "")
            if client is not None:
                client.set_slave_id(max(1, min(247, int(current_device.get("slaveId") or 1))))

        try:
            while not stop_event.is_set():
                device_commands = commands_by_device.get(current_device_id) or []
                if not device_commands:
                    switch_device()
                    stop_event.wait(0.1)
                    continue

                command_index = command_indexes.get(current_device_id, 0) % len(device_commands)
                command = device_commands[command_index]
                command_indexes[current_device_id] = (command_index + 1) % len(device_commands)

                # 串口打开也必须与手动报文共用同一把锁，否则手动调试关闭轮询客户端后，
                # 轮询线程可能在手动帧尚未完成时抢先重新打开 COM 口。
                with self._io_lock:
                    c = ensure_client_for(current_device)
                if c is None:
                    self._record_device_error(
                        current_device_id,
                        _format_error_message("serial open failed", RuntimeError(last_open_error) if last_open_error else None),
                        "serial_open_failed",
                        error=last_open_error,
                    )
                    self._record_open_failure_traffic(current_device_id)
                    switch_device()
                    stop_event.wait(0.5)
                    continue

                command_ok = True
                try:
                    with self._io_lock:
                        if c is None or getattr(c, "_serial", None) is None:
                            c = ensure_client_for(current_device)
                        if c is None:
                            raise RuntimeError("serial reopen failed")
                        self._poll_command(current_device_id, c, command, stop_event)
                    self._save_checkpoint_if_due(current_device_id)
                except Exception as exc:
                    if c is not None:
                        c.close()
                    client = None
                    with self._lock:
                        runner = self._port_runners.get(port_key)
                        if runner is not None:
                            runner["client"] = None
                    command_label = command.get("name") or command.get("id") or "command"
                    self._record_device_error(
                        current_device_id,
                        _format_error_message(f"read failed for {command_label}", exc),
                        "read_failed",
                        command=command.get("id"),
                        error=str(exc).strip() or exc.__class__.__name__,
                    )
                    self._record_read_failure_traffic(current_device_id, str(command_label))
                    command_ok = False

                if command_ok:
                    delay_ms = max(0, _safe_int(command.get("delayAfterMs"), 0))
                    if delay_ms and stop_event.wait(min(delay_ms / 1000.0, 5.0)):
                        break
                    switch_device()
                else:
                    switch_device()
                    stop_event.wait(0.25)
        finally:
            if client is not None:
                client.close()
            with self._lock:
                runner = self._port_runners.get(port_key)
                if runner is not None:
                    runner["client"] = None
                for device_id in device_ids:
                    slot = self._device_slots.get(device_id)
                    if slot is not None:
                        slot["state"]["running"] = False
                        if slot["recorder"] is not None:
                            slot["recorder"].finalize(status="stopped")

    def _record_device_error(self, device_id: str, message: str, event_type: str, **details: Any) -> None:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return
        with self._lock:
            slot["state"]["last_error_at"] = _iso(_now())
            slot["state"]["last_error"] = message
            slot["state"]["error_count"] = int(slot["state"].get("error_count") or 0) + 1
            slot["state"]["consecutive_error_count"] = int(slot["state"].get("consecutive_error_count") or 0) + 1
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": _iso(_now()),
                "type": event_type,
                "message": message,
                "details": details,
            })
            self._log_recorder_for_slot(slot, "E", message)

    def _record_open_failure_traffic(self, device_id: str) -> None:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return
        timestamp = _iso(_now())
        device = slot["config"]
        port = str(device.get("address") or "").upper()
        slave_id = device.get("slaveId")
        with self._lock:
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": timestamp,
                "type": "serial_open_failed",
                "message": f"open {port} failed",
                "details": {"port": port, "slaveId": slave_id},
            })

    def _record_read_failure_traffic(self, device_id: str, group_key: str) -> None:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return
        timestamp = _iso(_now())
        device = slot["config"]
        port = str(device.get("address") or "").upper()
        slave_id = device.get("slaveId")
        with self._lock:
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": timestamp,
                "type": "read_failed",
                "message": f"poll {group_key} failed",
                "details": {"group": group_key, "port": port, "slaveId": slave_id},
            })

    def _record_command_success_event(self, slot: dict[str, Any], command: dict[str, Any], successful_blocks: int) -> None:
        now = _now()
        with self._lock:
            slot["state"]["last_success_at"] = _iso(now)
            slot["state"]["last_error"] = None
            slot["state"]["last_error_at"] = None
            slot["state"]["consecutive_error_count"] = 0
            slot["state"]["last_snapshot_at"] = _iso(now)
            self._recompute_sample_counts(slot)
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": _iso(now),
                "type": "read_success",
                "message": f"polled {command.get('name') or command.get('id') or 'command'}",
                "details": {"commandId": command.get("id"), "blockCount": successful_blocks},
            })

    def _next_traffic_id(self) -> int:
        self._traffic_id += 1
        return self._traffic_id

    @staticmethod
    def _parse_debug_hex(request_hex: str) -> bytes:
        cleaned = re.sub(r"(0x|[^0-9a-fA-F])", "", str(request_hex or ""), flags=re.IGNORECASE)
        if not cleaned:
            raise ValueError("requestHex is required")
        if len(cleaned) % 2 != 0:
            raise ValueError("requestHex must contain an even number of hex digits")
        try:
            return bytes.fromhex(cleaned)
        except ValueError as exc:
            raise ValueError("requestHex contains invalid hex bytes") from exc

    def _poll_group(self, device_id: str, client: LiveModbusClient, group: dict[str, Any], stop_event: threading.Event | None = None) -> None:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return
        successful_blocks = 0
        for block in group["blocks"]:
            if stop_event is not None and stop_event.is_set():
                break
            with self._lock:
                slot["state"]["request_count"] = int(slot["state"].get("request_count") or 0) + 1
                slot["state"]["last_attempt_at"] = _iso(_now())
            values = self._read_block(client, block)
            self._apply_block_values(device_id, slot, block, values)
            successful_blocks += 1
        if successful_blocks:
            now = _now()
            with self._lock:
                slot["state"]["last_success_at"] = _iso(now)
                slot["state"]["last_error"] = None
                slot["state"]["last_error_at"] = None
                slot["state"]["consecutive_error_count"] = 0
                slot["state"]["last_snapshot_at"] = _iso(now)
                self._recompute_sample_counts(slot)
                slot["event_seq"] += 1
                slot["events"].append({
                    "id": slot["event_seq"],
                    "ts": _iso(now),
                    "type": "read_success",
                    "message": f"polled {group['key']} ({successful_blocks} blocks)",
                    "details": {"group": group["key"], "blockCount": successful_blocks},
                })

    def _poll_command(
        self,
        device_id: str,
        client: LiveModbusClient,
        command: dict[str, Any],
        stop_event: threading.Event | None = None,
    ) -> None:
        slot = self._get_device_slot(device_id)
        if slot is None or (stop_event is not None and stop_event.is_set()):
            return
        with self._lock:
            slot["state"]["request_count"] = int(slot["state"].get("request_count") or 0) + 1
            slot["state"]["last_attempt_at"] = _iso(_now())
        block = self._command_to_block(command)
        values = self._read_block(client, block)
        if block["items"] and str(command.get("decodeMode") or "catalog") == "catalog":
            self._apply_block_values(device_id, slot, block, values)
        self._record_command_success_event(slot, command, 1)

    def _command_to_block(self, command: dict[str, Any]) -> dict[str, Any]:
        function_code = _safe_int(command.get("functionCode"), 0)
        address = max(0, _safe_int(command.get("address"), 0))
        count = max(1, _safe_int(command.get("count"), 1))
        area_by_function = {2: "discrete_input", 3: "holding_register", 4: "input_register"}
        area = area_by_function.get(function_code)
        if area is None:
            raise ValueError(f"unsupported polling command function code: {function_code}")
        catalog_item_ids = [str(item) for item in command.get("catalogItemIds") or []]
        items = [dict(self._catalog_by_id[item_id]) for item_id in catalog_item_ids if item_id in self._catalog_by_id]
        return {
            "function_code": function_code,
            "area": area,
            "start": address,
            "end": address + count - 1,
            "count": count,
            "items": items,
        }

    def _read_block(self, client: LiveModbusClient, block: dict[str, Any]) -> list[Any]:
        function_code = block["function_code"]
        address = block["start"]
        count = block["count"]
        if function_code == 2:
            return client.read_discrete_inputs(address, count)
        if function_code == 3:
            return client.read_holding_registers(address, count)
        if function_code == 4:
            return client.read_input_registers(address, count)
        raise ModbusError(f"unsupported function code: {function_code}")

    def _apply_block_values(self, device_id: str, slot: dict[str, Any], block: dict[str, Any], values: list[Any]) -> None:
        timestamp = _iso(_now())
        epoch = time.time()
        updates: list[tuple[str, Any]] = []
        for item in block["items"]:
            start = int(item["address"]) - block["start"]
            word_length = int(item.get("wordLength") or 1)
            chunk = values[start : start + word_length]
            decoded = self._decode_value(item, chunk)
            if item["id"] in {"input_register.system.protocol_version", "holding.config.protocol_version"}:
                if decoded != PROTOCOL_VERSION_WORD:
                    raise ModbusError(
                        f"Modbus 协议版本不匹配: 期望 0x{PROTOCOL_VERSION_WORD:04X}, 实际 0x{int(decoded or 0):04X}"
                    )
            updates.append((item["id"], decoded))
        with self._lock:
            for item_id, decoded in updates:
                slot["values"][item_id] = {"value": decoded, "ts": timestamp}
                if item_id.startswith("input_register."):
                    metric_key = item_id.split(".", 1)[1]
                    if metric_key in slot["history"] and decoded is not None:
                        slot["history"][metric_key].append({
                            "ts": timestamp,
                            "value": decoded,
                            "epoch": epoch,
                        })
            self._save_to_recorder(slot, device_id, timestamp)

    def _save_to_recorder(self, slot: dict[str, Any], device_id: str, timestamp: str) -> None:
        if slot["recorder"] is None:
            return
        try:
            snapshot_ts = datetime.fromisoformat(timestamp)
        except ValueError:
            return

        analog: dict[str, float] = {}
        source_keys = {
            "pressure": "pressure",
            "temperature": "sensor_1.temperature",
            "flow": "flow",
            "humidity": "sensor_1.humidity",
        }
        for key, source_key in source_keys.items():
            cached = slot["values"].get(f"input_register.{source_key}") or {}
            analog[key] = float(cached.get("value") or 0.0)

        try:
            slot["recorder"].record_environment_snapshot(snapshot_ts, analog)
        except Exception:
            self._log_recorder_for_slot(slot, "E", f"env snapshot write failed for {device_id}")

    def _save_checkpoint_if_due(self, device_id: str) -> None:
        with self._lock:
            slot = self._device_slots.get(device_id)
            if slot is None or slot.get("recorder") is None:
                return
            try:
                slot["recorder"].save_checkpoint(slot["state"])
            except Exception:
                pass

    def _recompute_sample_counts(self, slot: dict[str, Any]) -> None:
        values = slot["values"]
        metrics = sum(1 for item in self._catalog if item.get("area") == "input_register" and item["id"] in values)
        statuses = sum(1 for item in self._catalog if item.get("area") == "discrete_input" and item["id"] in values)
        controls = sum(1 for item in self._catalog if item.get("group") == "control" and item["id"] in values)
        parameters = sum(
            1 for item in self._catalog if item.get("group") in {"control", "config", "task"} and item["id"] in values
        )
        history = sum(len(rows) for rows in slot["history"].values())
        slot["state"]["sample_counts"] = {
            "metrics": metrics,
            "statuses": statuses,
            "controls": controls,
            "parameters": parameters,
            "history": history,
        }

    @staticmethod
    def _encode_write_value(item: dict[str, Any], value: Any) -> tuple[list[int], Any]:
        data_type = str(item.get("dataType") or "")
        words = encode_words(value, data_type)
        decoded = decode_words(words, data_type)
        if isinstance(decoded, float):
            decoded = round(decoded, 4)
        return words, decoded

    @staticmethod
    def _decode_value(item: dict[str, Any], raw_values: list[Any]) -> Any:
        area = str(item.get("area") or "")
        if area == "discrete_input":
            return bool(raw_values[0]) if raw_values else None
        if not raw_values:
            return None
        word_length = int(item.get("wordLength") or 1)
        if len(raw_values) < word_length:
            return None
        value = decode_words([int(word) for word in raw_values[:word_length]], str(item.get("dataType") or "uint16"))
        return round(value, 4) if isinstance(value, float) else value

    def _build_group_schedule(self, device: dict[str, Any]) -> list[dict[str, Any]]:
        settings = device.get("pollingSettings") if isinstance(device.get("pollingSettings"), dict) else {}
        readable_items = [dict(item) for item in self._catalog if item.get("readable")]
        grouped_items: list[dict[str, Any]] = []
        for group_key in ("fast", "standard"):
            group_settings = settings.get(group_key) if isinstance(settings.get(group_key), dict) else {}
            interval_ms = max(100, _safe_int(group_settings.get("intervalMs"), 1000))
            items = [item for item in readable_items if item.get("pollGroup") == group_key]
            grouped_items.append({
                "key": group_key,
                "interval_ms": interval_ms,
                "next_due": time.monotonic(),
                "blocks": self._build_blocks(items),
            })
        return [group for group in grouped_items if group["blocks"]]

    def poll_slow_group(self, device_id: str) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        if not slot["state"].get("running"):
            raise ValueError("live acquisition session is not running for this device")
        device = deepcopy(slot["config"])
        parameter_commands = [
            item
            for item in normalize_polling_commands(device.get("pollingCommands"), self._catalog)
            if item.get("sourceGroup") == "slow" or str(item.get("name") or "").startswith("参数")
        ]
        if not parameter_commands:
            return {"ok": True, "message": "no parameter polling commands", "blockCount": 0}
        port_key = _device_port_key(device)
        with self._io_lock:
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                for command in parameter_commands:
                    self._poll_command(device_id, client, command)
                    delay_ms = max(0, _safe_int(command.get("delayAfterMs"), 0))
                    if delay_ms:
                        time.sleep(min(delay_ms / 1000.0, 5.0))
            finally:
                client.close()
        now = _now()
        with self._lock:
            slot["state"]["last_success_at"] = _iso(now)
            slot["state"]["last_error"] = None
            slot["state"]["last_error_at"] = None
            slot["state"]["consecutive_error_count"] = 0
            slot["state"]["last_snapshot_at"] = _iso(now)
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": _iso(now),
                "type": "read_success",
                "message": f"manual poll parameters ({len(parameter_commands)} commands)",
                "details": {"group": "parameters", "blockCount": len(parameter_commands)},
            })
        return {
            "ok": True,
            "message": f"polled {len(parameter_commands)} parameter commands",
            "blockCount": len(parameter_commands),
        }

    def _build_blocks(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sorted_items = sorted(
            items,
            key=lambda item: (
                int(item.get("functionCode", [0])[0]),
                str(item.get("area") or ""),
                int(item.get("address") or 0),
            ),
        )
        blocks: list[dict[str, Any]] = []
        for item in sorted_items:
            function_code = int(item.get("functionCode", [0])[0])
            area = str(item.get("area") or "")
            item_start = int(item.get("address") or 0)
            item_end = int(item.get("addressEnd") or (item_start + int(item.get("wordLength") or 1) - 1))
            max_count = 2000 if function_code in {1, 2} else 125
            if not blocks:
                blocks.append(self._new_block(function_code, area, item_start, item_end, item))
                continue
            last_block = blocks[-1]
            if last_block["function_code"] != function_code or last_block["area"] != area:
                blocks.append(self._new_block(function_code, area, item_start, item_end, item))
                continue
            new_count = item_end - last_block["start"] + 1
            if item_start > last_block["end"] + 1 or new_count > max_count:
                blocks.append(self._new_block(function_code, area, item_start, item_end, item))
                continue
            last_block["end"] = max(last_block["end"], item_end)
            last_block["count"] = last_block["end"] - last_block["start"] + 1
            last_block["items"].append(item)
        return blocks

    @staticmethod
    def _new_block(function_code: int, area: str, start: int, end: int, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "function_code": function_code,
            "area": area,
            "start": start,
            "end": end,
            "count": end - start + 1,
            "items": [item],
        }


_SERVICE_SINGLETON = LiveAcquisitionService()


def get_live_acquisition_service() -> LiveAcquisitionService:
    return _SERVICE_SINGLETON
_TIME_CONFIG_UNIT_SECONDS = {
    "holding.flow.no_change_alarm_days": 86400,
    "holding.valve_route.restart_protection_days": 86400,
    "holding.valve_route.force_close_days": 86400,
    "holding.valve_route.cooling_delay_hours": 3600,
    "holding.control.close_delay_hours": 3600,
}
