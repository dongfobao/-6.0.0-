from __future__ import annotations

import threading
import time
import csv
from functools import wraps
import math
from collections import deque
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable

from live_modbus_client import LiveModbusClient, ModbusError, append_crc
from live_polling_commands import build_default_polling_commands, normalize_polling_commands
from live_register_catalog import PROTOCOL_VERSION_WORD, get_register_catalog, get_register_item
from live_session_recorder import LiveSessionRecorder
from modbus_v9_codec import decode_words, encode_words
from modbus_v9_config import V9ConfigTransaction


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

HISTORY_RAW_MAX_POINTS = 28800
HISTORY_ARCHIVE_MAX_POINTS = 7 * 24 * 60
HISTORY_RETENTION_SECONDS = 7 * 24 * 60 * 60
SCHEDULE_BASE_ADDRESS = int(get_register_item("holding.schedule.selected_task")["address"])
SCHEDULE_DATA_WORD_COUNT = 28
SCHEDULE_WINDOW_WORD_COUNT = 29
SCHEDULE_OPERATION_ADDRESS = int(get_register_item("holding.schedule.operation")["address"])
SCHEDULE_MAX_TASKS = 12
SCHEDULE_OPERATION_ADD = 1
SCHEDULE_OPERATION_DELETE_SELECTED = 2
CONFIG_REGION_START = int(get_register_item("holding.sensor_1.enabled")["address"])
RUNTIME_REGION_START = int(get_register_item("holding.runtime.remote_heat")["address"])
RUNTIME_CONTROL_END = int(get_register_item("holding.runtime.reset")["addressEnd"])


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(sep=" ") if dt else None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _strict_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} 必须是整数")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{field_name} 必须是整数")
    return int(number)


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


def _serialized_lifecycle(method: Any) -> Any:
    @wraps(method)
    def wrapped(self: "LiveAcquisitionService", *args: Any, **kwargs: Any) -> Any:
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)
    return wrapped


class LiveAcquisitionService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._port_io_locks_guard = threading.Lock()
        self._port_io_locks: dict[str, threading.RLock] = {}
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
                point_id.removeprefix("input_register."): deque(maxlen=HISTORY_RAW_MAX_POINTS)
                for point_id in HISTORY_POINT_IDS
            },
            "history_archive": {
                point_id.removeprefix("input_register."): deque(maxlen=HISTORY_ARCHIVE_MAX_POINTS)
                for point_id in HISTORY_POINT_IDS
            },
            "events": deque(maxlen=240),
            "traffic": deque(maxlen=1000),
            "pending_connection_profile": {},
            "recorder": None,
            "state": LiveAcquisitionService._empty_device_state(device),
            "event_seq": 0,
            "traffic_seq": 0,
            "protocol_rejected": False,
            "active_failures": set(),
        }

    def _port_io_lock(self, port_key: str) -> threading.RLock:
        with self._port_io_locks_guard:
            return self._port_io_locks.setdefault(port_key, threading.RLock())

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
            "recording_error": None,
            "finalization_pending": False,
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
        with self._lifecycle_lock:
            return self._start_all_locked(devices, session_root, config_snapshot)

    def _start_all_locked(
        self,
        devices: list[dict[str, Any]],
        session_root: Path | str | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        enabled_devices = [
            d for d in devices
            if d.get("enabled", True) is True or d.get("enabled", True) == 1
        ]
        if not enabled_devices:
            raise ValueError("no enabled devices to start")
        invalid_devices = [device for device in enabled_devices if not str(device.get("id") or "").strip()]
        if invalid_devices:
            raise ValueError("every enabled device must have a non-empty id")
        device_ids = [str(device.get("id")) for device in enabled_devices]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("设备 ID 不能重复")
        endpoints = [(_device_port_key(device), _safe_int(device.get("slaveId"), 1)) for device in enabled_devices]
        if any(not port or not 1 <= slave_id <= 247 for port, slave_id in endpoints):
            raise ValueError("设备串口和从站地址无效")
        if len(endpoints) != len(set(endpoints)):
            raise ValueError("同一串口上的从站地址不能重复")

        port_groups: dict[str, list[dict[str, Any]]] = {}
        for device in enabled_devices:
            device_id = str(device.get("id") or "")
            port_groups.setdefault(_device_port_key(device), []).append(device)

        # 重建受影响的串口时，保留其中原本仍在采集的设备。设备配置若变更
        # 串口，还必须同时重建旧串口，避免同一设备被两个轮询线程同时采集。
        requested_ids = {str(device.get("id")) for device in enabled_devices}
        with self._lock:
            active_port_by_device = {
                str(device_id): port_key
                for port_key, runner in self._port_runners.items()
                for device_id in (runner.get("device_ids") or [])
            }
        affected_ports = set(port_groups)
        affected_ports.update(
            active_port_by_device[device_id]
            for device_id in requested_ids
            if device_id in active_port_by_device
        )
        started_at = _now()
        session_root_path = Path(session_root or ".")
        prepared_slots: dict[str, dict[str, Any]] = {}
        try:
            for device in enabled_devices:
                device_id = str(device.get("id") or "")
                with self._lock:
                    existing = self._device_slots.get(device_id)
                    already_running = existing is not None and bool(existing["state"].get("running"))
                if already_running:
                    continue
                prepared = self._empty_device_slot(device)
                self._restore_recent_history(prepared, session_root_path, device_id, started_at)
                prepared["recorder"] = LiveSessionRecorder(
                    session_root_path, deepcopy(device), config_snapshot=config_snapshot
                )
                prepared["recorder"].record_heat_event(
                    _now(), "系统", "采集开始", f"设备 {device.get('name') or device_id} 开始监控记录"
                )
                prepared_slots[device_id] = prepared
        except Exception:
            for prepared in prepared_slots.values():
                recorder = prepared.get("recorder")
                if recorder is not None:
                    try:
                        recorder.finalize(status="start_failed")
                    except Exception:
                        pass
            raise

        previous = self._stop_port_runners(affected_ports)

        with self._lock:
            for port_key in affected_ports:
                requested_devices = port_groups.get(port_key, [])
                merged_devices: dict[str, dict[str, Any]] = {}
                for old_device_id in previous.get(port_key, []):
                    # 已请求的设备会按最新配置添加到目标串口，不能留在旧串口。
                    if old_device_id in requested_ids:
                        continue
                    old_slot = self._device_slots.get(old_device_id)
                    if old_slot is not None and old_slot["state"].get("running"):
                        merged_devices[old_device_id] = deepcopy(old_slot["config"])
                for device in requested_devices:
                    merged_devices[str(device.get("id"))] = device
                port_devices = list(merged_devices.values())
                if not port_devices:
                    continue

                same_port_count = len(port_devices)
                for device in port_devices:
                    device_id = str(device.get("id") or "")
                    slot = self._device_slots.get(device_id)
                    if slot is not None and slot["state"].get("running"):
                        slot["config"] = deepcopy(device)
                        if slot.get("recorder") is not None:
                            slot["recorder"].device = deepcopy(device)
                            if config_snapshot is not None:
                                slot["recorder"].config_snapshot = deepcopy(config_snapshot)
                        slot["state"].update({
                            "device_name": device.get("name"),
                            "status_stale_after_ms": self._estimate_status_stale_after_ms(device, same_port_count),
                        })
                        continue

                    self._device_slots[device_id] = prepared_slots.get(device_id) or self._empty_device_slot(device)
                    slot = self._device_slots[device_id]
                    if slot["recorder"] is None:
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
                self._start_port_runner(port_key, port_devices)

            self._refresh_global_state()
            return deepcopy(self._global_state)

    def stop_all(self) -> dict[str, Any]:
        with self._lifecycle_lock:
            return self._stop_all_locked()

    def _stop_all_locked(self) -> dict[str, Any]:
        with self._lock:
            port_keys = set(self._port_runners)
        self._stop_port_runners(port_keys)
        with self._lock:
            device_ids = list(self._device_slots)
        for device_id in device_ids:
            self._finalize_device_session(device_id)
        with self._lock:
            self._refresh_global_state()
            return deepcopy(self._global_state)

    def stop_devices(self, device_ids: Iterable[str]) -> dict[str, Any]:
        with self._lifecycle_lock:
            return self._stop_devices_locked(device_ids)

    def _stop_devices_locked(self, device_ids: Iterable[str]) -> dict[str, Any]:
        """只停止勾选的设备；同串口上未勾选的设备继续采集。"""
        targets = {str(value) for value in device_ids if str(value)}
        if not targets:
            return self.get_status()
        with self._lock:
            affected_ports = {
                port_key
                for port_key, runner in self._port_runners.items()
                if targets.intersection(str(item) for item in (runner.get("device_ids") or []))
            }
        previous = self._stop_port_runners(affected_ports)
        for device_id in targets:
            self._finalize_device_session(device_id)
        with self._lock:
            for port_key, old_device_ids in previous.items():
                remaining = [
                    old_id
                    for old_id in old_device_ids
                    if old_id not in targets
                    and old_id in self._device_slots
                    and self._device_slots[old_id]["state"].get("running")
                ]
                if not remaining:
                    continue
                devices = [deepcopy(self._device_slots[old_id]["config"]) for old_id in remaining]
                self._start_port_runner(port_key, devices)
            self._refresh_global_state()
            return deepcopy(self._global_state)

    def _start_port_runner(self, port_key: str, devices: list[dict[str, Any]]) -> None:
        """在指定串口上启动轮询线程，调用方需持有 self._lock。"""
        stop_event = threading.Event()
        runner: dict[str, Any] = {
            "thread": None,
            "stop_event": stop_event,
            "client": None,
            "device_ids": [str(d.get("id")) for d in devices],
            "device_index": 0,
            "port_key": port_key,
            "finalize_on_exit": True,
        }
        self._port_runners[port_key] = runner
        runner["thread"] = threading.Thread(
            target=self._run_port_loop,
            args=(port_key, devices, stop_event),
            name=f"live-acq-{port_key}",
            daemon=True,
        )
        try:
            runner["thread"].start()
        except Exception:
            self._port_runners.pop(port_key, None)
            for device in devices:
                slot = self._device_slots.get(str(device.get("id") or ""))
                if slot is not None:
                    slot["state"]["running"] = False
                    slot["state"]["finalization_pending"] = bool(slot.get("recorder") is not None)
            self._refresh_global_state()
            raise

    def _stop_port_runners(self, port_keys: set[str]) -> dict[str, list[str]]:
        """停止指定串口的轮询线程并关闭串口客户端，返回各串口原设备列表。

        线程退出时不自动归档会话（finalize_on_exit=False），由调用方按设备决定。
        """
        with self._lock:
            runners = {
                port_key: self._port_runners[port_key]
                for port_key in port_keys
                if port_key in self._port_runners
            }
            previous = {
                port_key: [str(item) for item in (runner.get("device_ids") or [])]
                for port_key, runner in runners.items()
            }
            for runner in runners.values():
                runner["finalize_on_exit"] = False
                runner["stop_event"].set()
        for runner in runners.values():
            client = runner.get("client")
            if client is not None:
                try:
                    # 先关闭串口以打断可能阻塞的读操作，再等待轮询线程退出。
                    client.close()
                except Exception:
                    pass
            thread = runner.get("thread")
            if thread is not None and thread.is_alive():
                thread.join(timeout=10.0)
        unfinished = [
            port_key
            for port_key, runner in runners.items()
            if (thread := runner.get("thread")) is not None and thread.is_alive()
        ]
        if unfinished:
            raise RuntimeError(f"轮询线程未在限定时间内退出，拒绝重建串口: {', '.join(unfinished)}")
        with self._lock:
            for port_key, runner in runners.items():
                self._port_runners.pop(port_key, None)
        return previous

    def _finalize_device_session(self, device_id: str) -> None:
        """结束指定设备的采集会话；磁盘归档不得占用全局状态锁。"""
        with self._lock:
            slot = self._device_slots.get(device_id)
            if slot is None or not (slot["state"].get("running") or slot["state"].get("finalization_pending")):
                return
            was_running = bool(slot["state"].get("running"))
            slot["state"]["running"] = False
            slot["state"]["finalization_pending"] = True
            if was_running:
                slot["events"].append({
                    "id": slot["event_seq"] + 1,
                    "ts": _iso(_now()),
                    "type": "session_stopped",
                    "message": "session stopped by api",
                })
                slot["event_seq"] += 1
            recorder = slot.get("recorder")
            final_state = deepcopy(slot["state"])
        if recorder is not None:
            try:
                if was_running:
                    recorder.record_heat_event(_now(), "系统", "采集停止", "上位机停止监控记录")
                recorder.save_checkpoint(final_state, force=True)
                recorder.finalize(status="stopped")
                with self._lock:
                    self._clear_recording_error(slot)
                    slot["state"]["finalization_pending"] = False
            except Exception as exc:
                with self._lock:
                    self._mark_recording_error(slot, exc)

    def _refresh_global_state(self) -> None:
        """根据各设备槽位的运行状态重建全局状态，调用方需持有 self._lock。"""
        running_ids = [
            device_id
            for device_id, slot in self._device_slots.items()
            if slot["state"].get("running")
        ]
        self._global_state = {
            "running": bool(running_ids),
            "device_count": len(running_ids),
            "device_ids": running_ids,
        }

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
        state["active_failure_count"] = len(slot.get("active_failures") or ())
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
        active_failures = max(0, _safe_int(state.get("active_failure_count"), 0))

        if state.get("recording_error"):
            return "warn", "会话记录异常"
        if active_failures:
            if consecutive_errors >= 3:
                return "error", "连续通信异常"
            return "warn", "部分轮询异常"

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
        settings = device.get("pollingSettings") if isinstance(device.get("pollingSettings"), dict) else {}
        commands = [
            item for item in normalize_polling_commands(device.get("pollingCommands"))
            if item.get("autoPoll")
        ]
        timeout_ms = max(100, _safe_int(device.get("timeoutMs"), 1200))
        retry_count = max(0, _safe_int(device.get("retryCount"), 0))
        port_count = max(1, same_port_count)
        worst_request_ms = timeout_ms * (retry_count + 1)
        per_device_delay_ms = sum(max(0, _safe_int(item.get("delayAfterMs"), 0)) for item in commands)
        estimated_cycle_ms = (worst_request_ms * max(1, len(commands)) * port_count) + (per_device_delay_ms * port_count)
        max_interval_ms = max(
            (_safe_int(group.get("intervalMs"), 0) for group in settings.values() if isinstance(group, dict)),
            default=0,
        )
        return max(15000, int(estimated_cycle_ms + max_interval_ms))

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
            if not slot["state"].get("running"):
                return {
                    "deviceId": device_id, "snapshotAt": None, "ts": None,
                    "metrics": [], "statuses": [], "controls": [],
                    "session": self._state_with_health(slot),
                }
            metrics = [self._catalog_item_with_value(item, slot["values"]) for item in self._catalog if item.get("area") == "input_register"]
            statuses = [self._catalog_item_with_value(item, slot["values"]) for item in self._catalog if item.get("area") == "discrete_input"]
            controls = [
                self._catalog_item_with_value(item, slot["values"])
                for item in self._catalog
                if item.get("group") in {"control", "config", "task", "schedule", "runtime_control", "diagnostic"}
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
            return {"rows": [], "byMetric": {}, "availableDates": [], "availableRange": None, "range": {"start": start_at, "end": end_at}}
        start_time = _parse_iso(start_at)
        end_time = _parse_iso(end_at)
        if start_at and start_time is None:
            raise ValueError("曲线开始时间格式无效")
        if end_at and end_time is None:
            raise ValueError("曲线结束时间格式无效")
        if start_time is not None and end_time is not None and end_time < start_time:
            raise ValueError("曲线结束时间不能早于开始时间")
        cutoff = start_time.timestamp() if start_time is not None else time.time() - max(1000, window_ms) / 1000.0
        end_epoch = end_time.timestamp() if end_time is not None else float("inf")
        capped_limit = max(1, min(limit, 2000))
        with self._lock:
            history_archive = slot.get("history_archive") or {}
            all_epochs = sorted({
                float(row["epoch"])
                for history_name in ("history", "history_archive")
                for rows in (slot.get(history_name) or {}).values()
                for row in rows
            })
            available_dates = sorted({datetime.fromtimestamp(epoch).strftime("%Y-%m-%d") for epoch in all_epochs}, reverse=True)
            by_metric: dict[str, list[dict[str, Any]]] = {}
            for key, rows in slot["history"].items():
                raw_rows = list(rows)
                raw_start = float(raw_rows[0]["epoch"]) if raw_rows else float("inf")
                archive_rows = [
                    row for row in history_archive.get(key, ())
                    if float(row["epoch"]) < raw_start
                ]
                filtered = [
                    self._public_history_row(row)
                    for row in (*archive_rows, *raw_rows)
                    if cutoff <= float(row["epoch"]) <= end_epoch
                ]
                by_metric[key] = self._downsample_history_rows(filtered, capped_limit)

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
                "availableDates": available_dates,
                "availableRange": {
                    "start": _iso(datetime.fromtimestamp(all_epochs[0])),
                    "end": _iso(datetime.fromtimestamp(all_epochs[-1])),
                } if all_epochs else None,
                "range": {
                    "start": _iso(start_time) if start_time is not None else None,
                    "end": _iso(end_time) if end_time is not None else None,
                },
            }

    @staticmethod
    def _public_history_row(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if not str(key).startswith("_")}

    @staticmethod
    def _downsample_history_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        if len(rows) <= limit:
            return rows
        if limit <= 1:
            return [rows[-1]]
        if limit == 2:
            return [rows[0], rows[-1]]
        # Largest-Triangle-Three-Buckets：保留首尾及具有最大视觉面积的尖峰/谷值。
        every = (len(rows) - 2) / (limit - 2)
        selected = [rows[0]]
        anchor_index = 0
        for bucket in range(limit - 2):
            avg_start = int((bucket + 1) * every) + 1
            avg_end = min(int((bucket + 2) * every) + 1, len(rows))
            avg_rows = rows[avg_start:avg_end] or [rows[-1]]
            avg_x = sum(float(row["epoch"]) for row in avg_rows) / len(avg_rows)
            avg_y = sum(float(row["value"]) for row in avg_rows) / len(avg_rows)
            range_start = int(bucket * every) + 1
            range_end = min(int((bucket + 1) * every) + 1, len(rows) - 1)
            anchor = rows[anchor_index]
            ax, ay = float(anchor["epoch"]), float(anchor["value"])
            candidates = rows[range_start:range_end] or [rows[range_start]]
            chosen = max(
                candidates,
                key=lambda row: abs(
                    (ax - avg_x) * (float(row["value"]) - ay)
                    - (ax - float(row["epoch"])) * (avg_y - ay)
                ),
            )
            selected.append(chosen)
            anchor_index = rows.index(chosen, range_start, range_end or None)
        selected.append(rows[-1])
        return selected

    @staticmethod
    def _append_history_point(
        slot: dict[str, Any],
        metric_key: str,
        timestamp: str,
        epoch: float,
        value: Any,
    ) -> None:
        row = {"ts": timestamp, "value": value, "epoch": epoch}
        numeric_value = float(value)
        if not math.isfinite(float(epoch)) or not math.isfinite(numeric_value):
            return
        if slot["history"][metric_key] and float(slot["history"][metric_key][-1]["epoch"]) == epoch:
            slot["history"][metric_key][-1] = row
            return
        slot["history"][metric_key].append(row)
        archive = slot["history_archive"][metric_key]
        bucket_epoch = int(epoch // 60) * 60
        if archive and int(float(archive[-1]["epoch"])) == bucket_epoch:
            bucket = archive[-1]
            bucket["_sum"] = float(bucket.get("_sum", bucket["value"])) + numeric_value
            bucket["_count"] = int(bucket.get("_count", 1)) + 1
            bucket["value"] = bucket["_sum"] / bucket["_count"]
            return
        archive.append({
            "ts": _iso(datetime.fromtimestamp(bucket_epoch)),
            "value": numeric_value,
            "epoch": float(bucket_epoch),
            "_sum": numeric_value,
            "_count": 1,
        })

    def _restore_recent_history(
        self,
        slot: dict[str, Any],
        session_root: Path,
        device_id: str,
        now: datetime,
    ) -> int:
        if not session_root.exists():
            return 0
        cutoff = now.timestamp() - HISTORY_RETENTION_SECONDS
        restored = 0
        pending: dict[str, dict[float, dict[str, Any]]] = {
            key: {} for key in slot["history"]
        }
        cutoff_date = datetime.fromtimestamp(cutoff).date()
        meta_paths = sorted(session_root.glob("*/session_meta.json"))
        for meta_path in meta_paths:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            meta_device = meta.get("device")
            if not isinstance(meta_device, dict) or str(meta_device.get("id") or "") != device_id:
                continue
            ended_at = _parse_iso(meta.get("ended_at"))
            if ended_at is not None and ended_at.timestamp() < cutoff:
                continue
            data_paths = sorted(meta_path.parent.glob("data_0/sensor_*.csv"))
            for data_path in data_paths:
                date_match = re.search(r"sensor_(\d{4})_(\d{2})_(\d{2})\.csv$", data_path.name)
                if date_match:
                    try:
                        file_date = datetime(*map(int, date_match.groups())).date()
                    except ValueError:
                        continue
                    if file_date < cutoff_date:
                        continue
                try:
                    with data_path.open("r", encoding="utf-8", newline="") as handle:
                        reader = csv.DictReader(handle)
                        for record in reader:
                            timestamp = str(record.get("timestamp") or "")
                            parsed = _parse_iso(timestamp)
                            if parsed is None:
                                continue
                            epoch = parsed.timestamp()
                            if epoch < cutoff or epoch > now.timestamp() + 60:
                                continue
                            columns = {
                                "pressure": "pressure",
                                "flow": "flow_rate",
                                "sensor_1.temperature": "t1_temperature",
                                "sensor_1.humidity": "t1_humidity",
                                "sensor_2.temperature": "t2_temperature",
                                "sensor_2.humidity": "t2_humidity",
                                "sensor_3.temperature": "t3_temperature",
                                "sensor_3.humidity": "t3_humidity",
                            }
                            for metric_key, column in columns.items():
                                raw_value = record.get(column)
                                if raw_value in (None, ""):
                                    continue
                                try:
                                    value = float(raw_value)
                                except (TypeError, ValueError):
                                    continue
                                if not math.isfinite(value):
                                    continue
                                pending[metric_key][epoch] = {
                                    "ts": timestamp, "epoch": epoch, "value": value,
                                }
                except OSError:
                    continue
        for metric_key, rows_by_epoch in pending.items():
            for epoch in sorted(rows_by_epoch):
                row = rows_by_epoch[epoch]
                self._append_history_point(slot, metric_key, row["ts"], epoch, row["value"])
                restored += 1
        return restored

    def get_events(
        self,
        device_id: str | None = None,
        limit: int = 80,
        start_at: str | None = None,
        end_at: str | None = None,
    ) -> list[dict[str, Any]]:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return []
        capped_limit = max(1, min(limit, 500))
        with self._lock:
            all_events = [dict(item) for item in list(slot["events"])]
            meaningful = [ev for ev in all_events if ev.get("type") != "read_success"]
            recorder = slot.get("recorder")
            session_root = recorder.sessions_root if recorder is not None else None
        start_time = _parse_iso(start_at)
        end_time = _parse_iso(end_at)
        if start_at and start_time is None:
            raise ValueError("事件开始时间格式无效")
        if end_at and end_time is None:
            raise ValueError("事件结束时间格式无效")
        if start_time is not None or end_time is not None:
            meaningful.extend(self._load_archived_events(
                session_root, str(device_id or ""), start_time, end_time
            ))
        deduplicated: dict[tuple[str, str, str], dict[str, Any]] = {}
        for event in meaningful:
            event_time = _parse_iso(event.get("ts"))
            if start_time is not None and (event_time is None or event_time < start_time):
                continue
            if end_time is not None and (event_time is None or event_time > end_time):
                continue
            key = (str(event.get("ts") or ""), str(event.get("type") or ""), str(event.get("message") or ""))
            deduplicated[key] = event
        return sorted(deduplicated.values(), key=lambda event: str(event.get("ts") or ""))[-capped_limit:]

    @staticmethod
    def _load_archived_events(
        session_root: Path | None,
        device_id: str,
        start_time: datetime | None,
        end_time: datetime | None,
    ) -> list[dict[str, Any]]:
        if session_root is None or not session_root.exists():
            return []
        events: list[dict[str, Any]] = []
        for meta_path in session_root.glob("*/session_meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            device = meta.get("device") if isinstance(meta, dict) else None
            if not isinstance(device, dict) or str(device.get("id") or "") != device_id:
                continue
            for event_path in sorted(meta_path.parent.glob("heat_events/heat_*.csv")):
                try:
                    with event_path.open("r", encoding="utf-8", newline="") as handle:
                        for line_number, row in enumerate(csv.reader(handle), start=1):
                            if len(row) < 3:
                                continue
                            timestamp = _parse_iso(row[0])
                            if timestamp is None or (start_time is not None and timestamp < start_time) or (end_time is not None and timestamp > end_time):
                                continue
                            events.append({
                                "id": f"archive:{meta_path.parent.name}:{event_path.name}:{line_number}",
                                "ts": _iso(timestamp), "type": "heat_event",
                                "message": f"{row[1]} {row[2]}",
                                "details": {"channel": row[1], "event": row[2], "detail": row[3] if len(row) > 3 else ""},
                            })
                except OSError:
                    continue
        return events

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
                    if item.get("area") == "holding_register" and CONFIG_REGION_START <= int(item.get("address") or 0) < RUNTIME_REGION_START
                    and item.get("group") != "time_sync"
                    and item.get("id") != "holding.schedule.operation"
                ],
                "runtime": [builder(item) for item in self._catalog if item.get("group") == "runtime_control"],
                "diagnostic": [builder(item) for item in self._catalog if item.get("group") == "diagnostic"],
                "transaction": [builder(item) for item in self._catalog if item.get("group") == "config_transaction"],
            }

    def get_pending_connection_profile(self, device_id: str) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        with self._lock:
            return dict(slot.get("pending_connection_profile") or {})

    def write_runtime_control(self, device_id: str, item_id: str, value: Any) -> dict[str, Any]:
        item = self._catalog_by_id.get(item_id)
        if item is None or item.get("group") != "runtime_control":
            raise ValueError(f"不是即时运行控制点: {item_id}")
        address = int(item.get("address") or -1)
        address_end = int(item.get("addressEnd") or address)
        if item.get("area") != "holding_register" or address < RUNTIME_REGION_START or address_end > RUNTIME_CONTROL_END:
            raise ValueError(f"即时控制地址必须位于 HR800–807: {item_id}")
        V9ConfigTransaction._validate_value_range(item, value)
        return self.write_value(device_id, item_id, value)

    @_serialized_lifecycle
    def stage_config_value(self, device_id: str, item_id: str, value: Any) -> dict[str, Any]:
        with self._lock:
            item = dict(self._catalog_by_id.get(item_id) or {})
            slot = self._get_device_slot(device_id)
        if not item:
            raise KeyError(f"未知配置点: {item_id}")
        if item_id in {"holding.schedule.task_count", "holding.schedule.operation"}:
            raise ValueError(f"该寄存器只能通过定时任务专用接口操作: {item_id}")
        address = int(item.get("address") or 0)
        if item.get("area") != "holding_register" or not CONFIG_REGION_START <= address < RUNTIME_REGION_START or not item.get("writable"):
            raise ValueError(f"不是可暂存配置点: {item_id}")
        if slot is None or not slot["state"].get("running"):
            raise ValueError("设备采集会话尚未运行")

        device = deepcopy(slot["config"])
        V9ConfigTransaction._validate_value_range(item, value)
        port_key = _device_port_key(device)
        with self._port_io_lock(port_key):
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                self._validate_related_config_value(slot, item_id, value, client)
                words = V9ConfigTransaction(client).stage_value(item, value)
                decoded = decode_words(words, str(item["dataType"]))
            finally:
                client.close()

        timestamp = _iso(_now())
        with self._lock:
            slot["values"][item_id] = {"value": decoded, "ts": timestamp}
            connection_field = {
                "holding.communication.slave_id": "slaveId",
                "holding.communication.baudrate": "baudrate",
                "holding.communication.parity": "parity",
            }.get(item_id)
            if connection_field is not None:
                connection_value = decoded
                if connection_field == "parity":
                    connection_value = {0: "N", 1: "O", 2: "E"}[int(decoded)]
                slot["pending_connection_profile"][connection_field] = connection_value
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"], "ts": timestamp, "type": "config_staged",
                "message": f"配置已暂存: {item_id}", "details": {"itemId": item_id, "value": decoded},
            })
        return {
            "ok": True,
            "itemId": item_id,
            "value": decoded,
            "wireValue": decoded,
            "words": words,
            "staged": True,
        }

    def _validate_related_config_value(
        self,
        slot: dict[str, Any],
        item_id: str,
        value: Any,
        client: LiveModbusClient | None = None,
    ) -> None:
        pairs = {
            "holding.pressure.alarm_high": ("holding.pressure.alarm_low", "high"),
            "holding.pressure.alarm_low": ("holding.pressure.alarm_high", "low"),
            "holding.flow.breath_high": ("holding.flow.breath_low", "high"),
            "holding.flow.breath_low": ("holding.flow.breath_high", "low"),
            "holding.antifreeze.close_temperature": ("holding.antifreeze.open_temperature", "high"),
            "holding.antifreeze.open_temperature": ("holding.antifreeze.close_temperature", "low"),
        }
        for channel in range(1, 4):
            for metric in ("temperature", "humidity"):
                high = f"holding.sensor_{channel}.{metric}_alarm_high"
                low = f"holding.sensor_{channel}.{metric}_alarm_low"
                pairs[high] = (low, "high")
                pairs[low] = (high, "low")
        relation = pairs.get(item_id)
        if relation is None:
            return
        counterpart_id, role = relation
        with self._lock:
            counterpart = (slot["values"].get(counterpart_id) or {}).get("value")
        if counterpart is None and client is not None:
            counterpart_item = self._catalog_by_id[counterpart_id]
            address = int(counterpart_item["address"])
            word_length = int(counterpart_item.get("wordLength") or 1)
            counterpart = decode_words(
                client.read_holding_registers(address, word_length),
                str(counterpart_item["dataType"]),
            )
        if counterpart is None:
            raise ValueError(f"无法读取关联参数: {counterpart_id}")
        current = float(value)
        other = float(counterpart)
        if (role == "high" and current <= other) or (role == "low" and current >= other):
            raise ValueError(f"{item_id} 与 {counterpart_id} 的上下限关系无效")

    @_serialized_lifecycle
    def select_schedule_task(self, device_id: str, task_number: Any) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        if not slot["state"].get("running"):
            raise ValueError("设备采集会话尚未运行")
        selected = _strict_int(task_number, "taskNumber")
        if selected < 1 or selected > SCHEDULE_MAX_TASKS:
            raise ValueError("定时任务序号必须在 1–12 之间")

        device = deepcopy(slot["config"])
        port_key = _device_port_key(device)
        with self._port_io_lock(port_key):
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                transaction = V9ConfigTransaction(client)
                if transaction.read_status().state & 0x0002:
                    raise ValueError("当前已有未提交配置，不能切换定时任务浏览窗口")
                current = self._refresh_schedule_from_client(device_id, slot, client)
                task_count = int(current[1])
                if selected > task_count:
                    raise ValueError(f"任务 {selected} 尚未配置，当前仅有 {task_count} 个任务")
                client.write_single_register(SCHEDULE_BASE_ADDRESS, selected)
                refreshed = self._refresh_schedule_from_client(device_id, slot, client)
                if int(refreshed[0]) != selected:
                    raise ModbusError("定时任务切换回读不一致")
                transaction.discard()
            finally:
                client.close()
        return self._schedule_result(slot)

    @_serialized_lifecycle
    def mutate_schedule_tasks(self, device_id: str, action: str) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        if not slot["state"].get("running"):
            raise ValueError("设备采集会话尚未运行")
        normalized = str(action or "").strip().lower()
        operations = {
            "add": SCHEDULE_OPERATION_ADD,
            "delete": SCHEDULE_OPERATION_DELETE_SELECTED,
        }
        if normalized not in operations:
            raise ValueError(f"不支持的定时任务操作: {action}")

        device = deepcopy(slot["config"])
        port_key = _device_port_key(device)
        with self._port_io_lock(port_key):
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                before = self._refresh_schedule_from_client(device_id, slot, client)
                old_count = int(before[1])
                if normalized == "add" and old_count >= SCHEDULE_MAX_TASKS:
                    raise ValueError("定时任务已达到 12 条上限")
                if normalized == "delete" and old_count == 0:
                    raise ValueError("当前没有可删除的定时任务")
                client.write_single_register(SCHEDULE_OPERATION_ADDRESS, operations[normalized])
                after = self._refresh_schedule_from_client(device_id, slot, client)
                expected_count = old_count + (1 if normalized == "add" else -1)
                if int(after[1]) != expected_count:
                    raise ModbusError("定时任务数量回读不一致，请确认下位机运行 Modbus V9 固件")
            finally:
                client.close()

        timestamp = _iso(_now())
        with self._lock:
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": timestamp,
                "type": f"schedule_{normalized}",
                "message": "已暂存新增定时任务" if normalized == "add" else "已暂存删除定时任务",
                "details": {"taskCount": expected_count},
            })
        return self._schedule_result(slot)

    @_serialized_lifecycle
    def stage_schedule_task(self, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        if not slot["state"].get("running"):
            raise ValueError("设备采集会话尚未运行")

        task_number = _strict_int(payload.get("taskNumber"), "taskNumber")
        month = _strict_int(payload.get("month"), "month")
        day = _strict_int(payload.get("day"), "day")
        hour = _strict_int(payload.get("hour"), "hour")
        minute = _strict_int(payload.get("minute"), "minute")
        duration_days = _strict_int(payload.get("durationDays"), "durationDays")
        if task_number < 1 or task_number > SCHEDULE_MAX_TASKS:
            raise ValueError("定时任务序号必须在 1–12 之间")
        try:
            # 定时任务按每年重复执行，不能接受仅闰年存在的 2 月 29 日。
            datetime(2001, month, day, hour, minute)
        except ValueError as exc:
            raise ValueError("开始日期或时间无效") from exc
        if duration_days < 1 or duration_days > 3650:
            raise ValueError("持续时间必须在 1–3650 天之间")

        start_thresholds = [
            float(value) for value in payload.get("humidityStartThreshold", [])
        ]
        falling_stop_thresholds = [
            float(value)
            for value in payload.get("humidityFallingStopThreshold", [])
        ]
        peak_drop_thresholds = [
            float(value) for value in payload.get("humidityPeakDropThreshold", [])
        ]
        if (
            len(start_thresholds) != 3
            or len(falling_stop_thresholds) != 3
            or len(peak_drop_thresholds) != 3
        ):
            raise ValueError("必须提供三路启动湿度、回落停热湿度和峰值回落幅度")
        for index, (start, falling_stop, peak_drop) in enumerate(
            zip(
                start_thresholds,
                falling_stop_thresholds,
                peak_drop_thresholds,
            ),
            start=1,
        ):
            if not 0 <= start <= 100 or not 0 <= falling_stop <= 100:
                raise ValueError(f"温湿度 {index} 的湿度阈值必须在 0–100 %RH")
            if falling_stop >= start:
                raise ValueError(f"温湿度{index}的回落停热阈值必须小于启动阈值")
            if not 0 < peak_drop <= 100:
                raise ValueError(f"温湿度 {index} 的峰值回落幅度必须在 0–100 %RH")

        device = deepcopy(slot["config"])
        port_key = _device_port_key(device)
        with self._port_io_lock(port_key):
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                current = self._refresh_schedule_from_client(device_id, slot, client)
                if task_number > int(current[1]):
                    raise ValueError(f"任务 {task_number} 尚未配置")
                if int(current[0]) != task_number:
                    client.write_single_register(SCHEDULE_BASE_ADDRESS, task_number)
                    current = self._refresh_schedule_from_client(device_id, slot, client)

                words = list(current[:SCHEDULE_DATA_WORD_COUNT])
                words[0] = task_number
                words[2] = 1 if self._strict_bool(payload.get("enabled"), "enabled") else 0
                words[3] = month
                words[4] = day
                words[5] = hour
                words[6] = minute
                words[7:9] = encode_words(duration_days, "uint32")
                words[9] = 1 if self._strict_bool(payload.get("humidityOverrideEnabled"), "humidityOverrideEnabled") else 0
                for sensor, value in enumerate(start_thresholds):
                    offset = 10 + sensor * 2
                    words[offset:offset + 2] = encode_words(value, "float32")
                for sensor, value in enumerate(falling_stop_thresholds):
                    offset = 16 + sensor * 2
                    words[offset:offset + 2] = encode_words(value, "float32")
                for sensor, value in enumerate(peak_drop_thresholds):
                    offset = 22 + sensor * 2
                    words[offset:offset + 2] = encode_words(value, "float32")

                client.write_multiple_registers(SCHEDULE_BASE_ADDRESS, words)
                readback = client.read_holding_registers(
                    SCHEDULE_BASE_ADDRESS, SCHEDULE_DATA_WORD_COUNT
                )
                if list(readback) != words:
                    raise ModbusError("定时任务配置回读不一致")
                self._refresh_schedule_from_client(device_id, slot, client)
            finally:
                client.close()

        timestamp = _iso(_now())
        with self._lock:
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": timestamp,
                "type": "schedule_staged",
                "message": f"定时任务 {task_number} 已暂存",
                "details": {"taskNumber": task_number},
            })
        return self._schedule_result(slot)

    def _refresh_schedule_from_client(
        self,
        device_id: str,
        slot: dict[str, Any],
        client: LiveModbusClient,
    ) -> list[int]:
        command = next(
            (
                item for item in self._default_polling_commands
                if int(item.get("address") or -1) == SCHEDULE_BASE_ADDRESS
                and int(item.get("functionCode") or 0) == 3
            ),
            None,
        )
        if command is None:
            raise RuntimeError("缺少定时任务固定轮询块")
        block = self._command_to_block(command)
        values = [int(value) & 0xFFFF for value in self._read_block(client, block)]
        if len(values) != SCHEDULE_WINDOW_WORD_COUNT:
            raise ModbusError("定时任务响应长度错误")
        self._apply_block_values(device_id, slot, block, values)
        return values

    def _schedule_result(self, slot: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = [
                self._catalog_item_with_value(item, slot["values"])
                for item in self._catalog
                if item.get("group") == "schedule"
                and item.get("id") != "holding.schedule.operation"
            ]
        return {"ok": True, "staged": True, "config": rows}

    @_serialized_lifecycle
    def sync_rtc_from_epoch(self, device_id: str, epoch_seconds: Any,
                            timezone_offset_minutes: Any = 0) -> dict[str, Any]:
        epoch = _strict_int(epoch_seconds, "epochSeconds")
        offset = _strict_int(timezone_offset_minutes, "timezoneOffsetMinutes")
        if offset != 0:
            raise ValueError("Unix 时间戳已经是 UTC 绝对时间，timezoneOffsetMinutes 必须为 0")
        slot = self._get_device_slot_required(device_id)
        if not slot["state"].get("running"):
            raise ValueError("设备采集会话尚未运行")
        device = deepcopy(slot["config"])
        port_key = _device_port_key(device)
        item = self._catalog_by_id["holding.system.rtc_sync_epoch"]
        client = None
        try:
            with self._port_io_lock(port_key):
                self._close_runner_client_for_port(port_key)
                client = self._open_manual_client(device, device_id)
                transaction = V9ConfigTransaction(client)
                if transaction.read_status().state & 0x0002:
                    raise ValueError("当前已有未提交配置，请先提交或放弃后再同步 RTC")
                words = transaction.stage_value(item, epoch)
                try:
                    status = transaction.commit()
                except Exception:
                    transaction.discard()
                    raise
        finally:
            if client is not None:
                client.close()
        timestamp = _iso(_now())
        with self._lock:
            slot["values"][str(item["id"])] = {"value": epoch, "ts": timestamp}
        return {
            "ok": True,
            "epoch": epoch,
            "timezoneOffsetMinutes": offset,
            "words": words,
            "transaction": {"status": asdict(status), "action": "commit"},
        }

    @_serialized_lifecycle
    def execute_config_transaction(self, device_id: str, action: str) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        if not slot["state"].get("running"):
            raise ValueError("设备采集会话尚未运行")
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"commit", "discard"}:
            raise ValueError(f"不支持的配置事务动作: {action}")

        device = deepcopy(slot["config"])
        port_key = _device_port_key(device)
        refresh_error = ""
        with self._port_io_lock(port_key):
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                transaction = V9ConfigTransaction(client)
                status = transaction.commit() if normalized_action == "commit" else transaction.discard()
                if normalized_action == "discard":
                    try:
                        for command in self._default_polling_commands:
                            if command.get("sourceGroup") == "slow":
                                self._poll_command(device_id, client, command)
                    except Exception as exc:
                        refresh_error = str(exc).strip() or exc.__class__.__name__
            finally:
                client.close()

        payload = asdict(status)
        timestamp = _iso(_now())
        with self._lock:
            connection_profile = dict(slot.get("pending_connection_profile") or {})
            restart_required = normalized_action == "commit" and bool(connection_profile)
            if normalized_action in {"commit", "discard"}:
                slot["pending_connection_profile"] = {}
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"], "ts": timestamp, "type": f"config_{normalized_action}",
                "message": (
                    "配置已提交；通信参数将在设备重启后生效"
                    if restart_required
                    else ("配置已提交" if normalized_action == "commit" else "配置暂存已放弃")
                ),
                "details": {
                    **payload,
                    "restartRequired": restart_required,
                    "connectionProfile": connection_profile,
                },
            })
        return {
            "ok": True,
            "action": normalized_action,
            "status": payload,
            "restartRequired": restart_required,
            "connectionProfile": connection_profile,
            "refreshError": refresh_error,
        }

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

    @_serialized_lifecycle
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
        if not append_crc_bytes:
            raise ValueError("诊断读取必须由程序自动追加 CRC")
        if not expect_response:
            raise ValueError("诊断读取必须等待并校验设备响应")
        if len(request_bytes) != 6:
            raise ValueError("诊断请求必须是 6 字节标准 Modbus 读取 PDU")
        slave_id, function_code = request_bytes[0], request_bytes[1]
        address = int.from_bytes(request_bytes[2:4], "big")
        count = int.from_bytes(request_bytes[4:6], "big")
        allowed_blocks = {
            (int(item["functionCode"]), int(item["address"]), int(item["count"]))
            for item in self._default_polling_commands
        }
        if slave_id != int(device.get("slaveId") or 0):
            raise ValueError("诊断请求的从站地址与当前设备不一致")
        if (function_code, address, count) not in allowed_blocks:
            raise ValueError("仅允许读取点表声明的固定 Modbus V9.1 轮询块")
        if response_timeout_ms is not None and not 50 <= int(response_timeout_ms) <= 30_000:
            raise ValueError("诊断响应超时必须在 50–30000 ms 之间")
        port_key = _device_port_key(device)
        with self._port_io_lock(port_key):
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

    @_serialized_lifecycle
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
        with self._port_io_lock(port_key):
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
                if item_id in {
                    "holding.runtime.htc1_mode",
                    "holding.runtime.htc2_mode",
                    "holding.runtime.antifreeze_mode",
                }:
                    runtime_feedback = self._read_runtime_heat_feedback(client)
                    confirmed = runtime_feedback.get(item_id)
                    if confirmed is None or int(confirmed) != int(decoded_value):
                        raise ModbusError(
                            f"加热模式回读不一致：写入 {decoded_value}，回读 {confirmed}"
                        )
                elif item_id == "holding.runtime.remote_heat":
                    feedback_item = self._catalog_by_id["input_register.output.remote_heat"]
                    feedback_address = int(feedback_item["address"])
                    feedback_words = client.read_input_registers(feedback_address, int(feedback_item["wordLength"]))
                    confirmed = self._decode_value(feedback_item, feedback_words)
                    runtime_feedback[item_id] = confirmed
                    runtime_feedback["input_register.output.remote_heat"] = confirmed
                    if int(confirmed) != int(decoded_value):
                        raise ModbusError(f"远程加热回读不一致: 写入 {decoded_value}, 回读 {confirmed}")
                elif re.fullmatch(r"holding\.runtime\.valve_[1-3]", item_id):
                    runtime_feedback = self._read_runtime_valve_feedback(client)
                    if int(decoded_value) == 3:
                        # 回原点校准为一次性触发命令，下位机不回填该值，跳过回读比对
                        runtime_feedback.pop(item_id, None)
                    else:
                        confirmed = runtime_feedback.get(item_id)
                        if confirmed is None or int(confirmed) != int(decoded_value):
                            raise ModbusError(f"阀门命令回读不一致: 写入 {decoded_value}, 回读 {confirmed}")
            finally:
                client.close()

        timestamp = _iso(_now())
        with self._lock:
            if int(decoded_value) == 3 and re.fullmatch(r"holding\.runtime\.valve_[1-3]", item_id):
                slot["values"].pop(item_id, None)
            else:
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
            row = self._catalog_item_with_value(item, slot["values"])
            result = {
                "ok": True,
                "implemented": True,
                "message": f"live value written: {item_id}",
                "item": row,
                "runtimeFeedback": runtime_feedback,
                "session": deepcopy(slot["state"]),
            }
        self._log_recorder_for_slot(slot, "I", f"write {item_id} = {decoded_value}")
        return result

    @staticmethod
    def _read_runtime_heat_feedback(client: LiveModbusClient) -> dict[str, Any]:
        start_address = int(get_register_item("input_register.output.htc1_mode")["address"])
        words = client.read_input_registers(start_address, 3)
        return {
            "holding.runtime.htc1_mode": words[0],
            "holding.runtime.htc2_mode": words[1],
            "holding.runtime.antifreeze_mode": words[2],
            "input_register.output.htc1_mode": words[0],
            "input_register.output.htc2_mode": words[1],
            "input_register.output.antifreeze_mode": words[2],
        }

    def _read_runtime_valve_feedback(self, client: LiveModbusClient) -> dict[str, Any]:
        start_address = int(get_register_item("holding.runtime.valve_1")["address"])
        end_address = int(get_register_item("holding.runtime.valve_action_limit")["addressEnd"])
        words = client.read_holding_registers(start_address, end_address - start_address + 1)
        feedback: dict[str, Any] = {}
        for item in self._catalog:
            address = int(item.get("address") or -1)
            if item.get("area") != "holding_register" or address < start_address or address > end_address:
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
            recorder = slot["recorder"]
            session_dir = str(recorder.session_dir)
            device_name = slot["config"].get("name")
        exported_dir = recorder.export_to(Path(export_root))
        self._log_recorder_for_slot(slot, "I", f"session exported to {exported_dir}")
        return {
            "sessionDir": session_dir,
            "exportDir": str(exported_dir),
            "deviceId": device_id,
            "deviceName": device_name,
        }

    def _catalog_item_with_value(self, item: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        row = dict(item)
        cached = values.get(item["id"]) or {}
        row["currentValue"] = cached.get("value")
        if item.get("dataType") == "uint64" and row["currentValue"] is not None:
            row["currentValue"] = str(row["currentValue"])
        row["value"] = row["currentValue"]
        row["updatedAt"] = cached.get("ts")
        return row

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
            try:
                slot["recorder"].record_traffic_entry(entry)
                self._clear_recording_error(slot)
            except Exception as exc:
                self._mark_recording_error(slot, exc)

    def _log_recorder_for_slot(self, slot: dict[str, Any], level: str, message: str) -> None:
        if slot["recorder"] is not None:
            try:
                slot["recorder"].record_log(level, _now(), message)
                self._clear_recording_error(slot)
            except Exception as exc:
                self._mark_recording_error(slot, exc)

    @staticmethod
    def _mark_recording_error(slot: dict[str, Any], exc: Exception) -> None:
        message = str(exc).strip() or exc.__class__.__name__
        slot["state"]["recording_error"] = message
        slot["state"]["last_error"] = f"会话记录失败: {message}"
        slot["state"]["last_error_at"] = _iso(_now())

    @staticmethod
    def _clear_recording_error(slot: dict[str, Any]) -> None:
        slot["state"]["recording_error"] = None
        if str(slot["state"].get("last_error") or "").startswith("会话记录失败"):
            slot["state"]["last_error"] = None
            slot["state"]["last_error_at"] = None

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
                settings = device.get("pollingSettings") if isinstance(device.get("pollingSettings"), dict) else {}
                now_monotonic = time.monotonic()
                for command in commands:
                    group_key = str(command.get("sourceGroup") or "fast")
                    group_settings = settings.get(group_key) if isinstance(settings.get(group_key), dict) else {}
                    default_interval = {"fast": 1000, "standard": 5000, "slow": 30000}.get(group_key, 1000)
                    command["_intervalMs"] = max(100, min(300_000, _safe_int(group_settings.get("intervalMs"), default_interval)))
                    command["_nextDue"] = now_monotonic
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
                now_monotonic = time.monotonic()
                command = None
                for offset in range(len(device_commands)):
                    candidate_index = (command_index + offset) % len(device_commands)
                    candidate = device_commands[candidate_index]
                    if float(candidate.get("_nextDue") or 0.0) <= now_monotonic:
                        command = candidate
                        command_indexes[current_device_id] = (candidate_index + 1) % len(device_commands)
                        break
                if command is None:
                    next_due = min(float(item.get("_nextDue") or now_monotonic) for item in device_commands)
                    switch_device()
                    stop_event.wait(max(0.01, min(0.1, next_due - now_monotonic)))
                    continue

                # 串口打开也必须与手动报文共用同一把锁，否则手动调试关闭轮询客户端后，
                # 轮询线程可能在手动帧尚未完成时抢先重新打开 COM 口。
                with self._port_io_lock(port_key):
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
                    with self._port_io_lock(port_key):
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
                    command_ok = False

                if command_ok:
                    command["_nextDue"] = time.monotonic() + float(command.get("_intervalMs") or 1000) / 1000.0
                    delay_ms = max(0, _safe_int(command.get("delayAfterMs"), 0))
                    if delay_ms and stop_event.wait(min(delay_ms / 1000.0, 5.0)):
                        break
                    switch_device()
                else:
                    command["_nextDue"] = time.monotonic() + min(1.0, float(command.get("_intervalMs") or 1000) / 1000.0)
                    switch_device()
                    stop_event.wait(0.25)
        finally:
            if client is not None:
                client.close()
            recorders: list[tuple[dict[str, Any], LiveSessionRecorder]] = []
            with self._lock:
                runner = self._port_runners.get(port_key)
                finalize_on_exit = True
                if runner is not None and runner.get("stop_event") is stop_event:
                    runner["client"] = None
                    finalize_on_exit = bool(runner.get("finalize_on_exit", True))
                    self._port_runners.pop(port_key, None)
                for device_id in device_ids:
                    slot = self._device_slots.get(device_id)
                    if slot is not None and finalize_on_exit:
                        slot["state"]["running"] = False
                        slot["state"]["finalization_pending"] = bool(slot["recorder"] is not None)
                        if slot["recorder"] is not None:
                            recorders.append((slot, slot["recorder"]))
                self._refresh_global_state()
            for slot, recorder in recorders:
                try:
                    recorder.save_checkpoint(deepcopy(slot["state"]), force=True)
                    recorder.finalize(status="stopped")
                    with self._lock:
                        slot["state"]["finalization_pending"] = False
                except Exception as exc:
                    with self._lock:
                        self._mark_recording_error(slot, exc)

    def _record_device_error(self, device_id: str, message: str, event_type: str, **details: Any) -> None:
        slot = self._get_device_slot(device_id)
        if slot is None:
            return
        with self._lock:
            failure_key = str(details.get("command") or event_type)
            slot.setdefault("active_failures", set()).add(failure_key)
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
            failure_key = str(command.get("id") or command.get("name") or "command")
            slot.setdefault("active_failures", set()).discard(failure_key)
            slot["active_failures"].discard("serial_open_failed")
            # 连续失败描述的是相邻 Modbus 请求，而不是某个轮询块累计失败的
            # 次数。任意请求成功都应立即打断连续失败；尚未恢复的其他块仍由
            # active_failures 保留，并在健康状态中显示为“部分轮询异常”。
            slot["state"]["consecutive_error_count"] = 0
            if not slot["active_failures"]:
                slot["state"]["last_error"] = None
                slot["state"]["last_error_at"] = None
            slot["state"]["last_snapshot_at"] = _iso(now)
            self._recompute_sample_counts(slot)

    def _next_traffic_id(self) -> int:
        self._traffic_id += 1
        return self._traffic_id

    @staticmethod
    def _parse_debug_hex(request_hex: str) -> bytes:
        raw = str(request_hex or "").strip()
        if not raw:
            raise ValueError("requestHex is required")
        if re.fullmatch(r"[0-9a-fA-F]+", raw):
            cleaned = raw
        else:
            tokens = raw.split()
            if not tokens or any(re.fullmatch(r"(?:0x)?[0-9a-fA-F]{2}", token, re.IGNORECASE) is None for token in tokens):
                raise ValueError("requestHex contains invalid characters")
            cleaned = "".join(token[2:] if token.lower().startswith("0x") else token for token in tokens)
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

    def _poll_command(
        self,
        device_id: str,
        client: LiveModbusClient,
        command: dict[str, Any],
        stop_event: threading.Event | None = None,
    ) -> bool:
        slot = self._get_device_slot(device_id)
        if slot is None or (stop_event is not None and stop_event.is_set()):
            return False
        is_protocol_command = int(command.get("functionCode") or 0) == 4 and int(command.get("address") or -1) == 0
        with self._lock:
            if slot.get("protocol_rejected") and not is_protocol_command:
                return False
        with self._lock:
            slot["state"]["request_count"] = int(slot["state"].get("request_count") or 0) + 1
            slot["state"]["last_attempt_at"] = _iso(_now())
        block = self._command_to_block(command)
        values = self._read_block(client, block)
        if block["items"] and str(command.get("decodeMode") or "catalog") == "catalog":
            self._apply_block_values(device_id, slot, block, values)
        self._record_command_success_event(slot, command, 1)
        return True

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
                    with self._lock:
                        slot["protocol_rejected"] = True
                    raise ModbusError(
                        f"Modbus 协议版本不匹配: 期望 0x{PROTOCOL_VERSION_WORD:04X}, 实际 0x{int(decoded or 0):04X}"
                    )
                with self._lock:
                    slot["protocol_rejected"] = False
            updates.append((item["id"], decoded))
        update_values = dict(updates)
        invalid_measurements: set[str] = set()
        for sensor_index in range(1, 4):
            prefix = f"input_register.sensor_{sensor_index}"
            status = update_values.get(f"{prefix}.status")
            read_ok = update_values.get(f"{prefix}.read_ok")
            if status is not None and (int(status) != 0 or not bool(read_ok)):
                invalid_measurements.update({f"{prefix}.temperature", f"{prefix}.humidity"})
        with self._lock:
            for item_id, decoded in updates:
                if item_id in invalid_measurements:
                    continue
                slot["values"][item_id] = {"value": decoded, "ts": timestamp}
                if item_id.startswith("input_register."):
                    metric_key = item_id.split(".", 1)[1]
                    if metric_key in slot["history"] and decoded is not None:
                        self._append_history_point(slot, metric_key, timestamp, epoch, decoded)
        if set(update_values).intersection(HISTORY_POINT_IDS):
            self._save_to_recorder(slot, device_id, timestamp)
        self._record_heat_events(slot, timestamp, update_values)

    def _record_heat_events(self, slot: dict[str, Any], timestamp: str, update_values: dict[str, Any]) -> None:
        """检测加热/阀门状态沿，向会话写入结构化 heat_events 记录。"""
        recorder = slot.get("recorder")
        if recorder is None:
            return
        watched = {
            "input_register.output.htc1_state", "input_register.output.htc2_state",
            "input_register.output.antifreeze_state",
            "input_register.heat_session_1.session_flags",
            "input_register.heat_session_2.session_flags",
            "input_register.valve_1.display_state",
            "input_register.valve_2.display_state",
            "input_register.valve_3.display_state",
        }
        if not watched.intersection(update_values):
            return
        try:
            snapshot_ts = datetime.fromisoformat(timestamp)
        except ValueError:
            return
        edges = slot.setdefault("heat_edge_state", {})

        def _emit(channel: str, event: str, detail: str = "") -> None:
            try:
                recorder.record_heat_event(snapshot_ts, channel, event, detail)
            except Exception as exc:
                self._mark_recording_error(slot, exc)
            slot["event_seq"] += 1
            slot["events"].append({
                "id": slot["event_seq"],
                "ts": timestamp,
                "type": "heat_event",
                "message": f"{channel} {event}",
                "details": {"channel": channel, "event": event, "detail": detail},
            })

        for item_id, channel in (
            ("input_register.output.htc1_state", "HTC1"),
            ("input_register.output.htc2_state", "HTC2"),
            ("input_register.output.antifreeze_state", "防冻"),
        ):
            if item_id not in update_values:
                continue
            new_value = update_values.get(item_id)
            old_value = edges.get(item_id)
            edges[item_id] = new_value
            if old_value is None or new_value is None:
                continue
            if int(old_value) != 1 and int(new_value) == 1:
                _emit(channel, "加热开启", f"状态 {int(old_value)}→{int(new_value)}")
            elif int(old_value) == 1 and int(new_value) != 1:
                _emit(channel, "加热关闭", f"状态 {int(old_value)}→{int(new_value)}")

        for side in (1, 2):
            flags_id = f"input_register.heat_session_{side}.session_flags"
            if flags_id not in update_values:
                continue
            new_flags = update_values.get(flags_id)
            old_flags = edges.get(flags_id)
            edges[flags_id] = new_flags
            if old_flags is None or new_flags is None:
                continue
            was_active = bool(int(old_flags) & 0x1)
            is_active = bool(int(new_flags) & 0x1)
            if is_active and not was_active:
                start = (slot["values"].get(f"input_register.heat_session_{side}.start_humidity") or {}).get("value")
                detail = f"起始湿度 {start:.1f}%RH" if isinstance(start, (int, float)) else ""
                _emit(f"HTC{side}", "湿度会话开始", detail)
            elif was_active and not is_active:
                peak = (slot["values"].get(f"input_register.heat_session_{side}.predicted_peak_humidity") or {}).get("value")
                target = (slot["values"].get(f"input_register.heat_session_{side}.stop_target_humidity") or {}).get("value")
                parts = []
                if isinstance(peak, (int, float)):
                    parts.append(f"预判峰值 {peak:.1f}%RH")
                if isinstance(target, (int, float)):
                    parts.append(f"关闭阈值 {target:.1f}%RH")
                _emit(f"HTC{side}", "湿度会话结束", " ".join(parts))

        valve_state_text = {0: "禁用", 1: "原位", 2: "工作位", 3: "运动中", 4: "故障", 5: "未知"}
        for channel, valve_name in enumerate(("上阀", "左阀", "右阀"), start=1):
            item_id = f"input_register.valve_{channel}.display_state"
            if item_id not in update_values:
                continue
            new_value = update_values.get(item_id)
            old_value = edges.get(item_id)
            edges[item_id] = new_value
            if old_value is None or new_value is None or int(old_value) == int(new_value):
                continue
            old_text = valve_state_text.get(int(old_value), str(old_value))
            new_text = valve_state_text.get(int(new_value), str(new_value))
            _emit(valve_name, "阀门状态变化", f"{old_text}→{new_text}")

    def _save_to_recorder(self, slot: dict[str, Any], device_id: str, timestamp: str) -> None:
        if slot["recorder"] is None:
            return
        try:
            snapshot_ts = datetime.fromisoformat(timestamp)
        except ValueError:
            return

        analog: dict[str, float | None] = {}
        source_keys = {
            "pressure": "pressure",
            "flow": "flow",
            "sensor_1.temperature": "sensor_1.temperature",
            "sensor_2.temperature": "sensor_2.temperature",
            "sensor_3.temperature": "sensor_3.temperature",
            "sensor_1.humidity": "sensor_1.humidity",
            "sensor_2.humidity": "sensor_2.humidity",
            "sensor_3.humidity": "sensor_3.humidity",
        }
        with self._lock:
            for key, source_key in source_keys.items():
                cached = slot["values"].get(f"input_register.{source_key}") or {}
                raw_value = cached.get("value")
                cached_at = _parse_iso(cached.get("ts"))
                if cached_at is None or abs((snapshot_ts - cached_at).total_seconds()) > 2.5:
                    raw_value = None
                sensor_match = re.fullmatch(r"sensor_(\d)\.(temperature|humidity)", source_key)
                if sensor_match:
                    read_ok = slot["values"].get(f"input_register.sensor_{sensor_match.group(1)}.read_ok") or {}
                    read_ok_at = _parse_iso(read_ok.get("ts"))
                    if read_ok.get("value") is not True or read_ok_at is None or abs((snapshot_ts - read_ok_at).total_seconds()) > 2.5:
                        raw_value = None
                analog[key] = float(raw_value) if raw_value is not None else None
            breath_state = (slot["values"].get("input_register.breath_state") or {}).get("value")
            analog["breath_state"] = int(breath_state) if breath_state in {0, 1, 2} else None
            raw_snapshot = {
                item_id: cached.get("value")
                for item_id, cached in slot["values"].items()
                if isinstance(cached, dict)
            }

        try:
            slot["recorder"].record_environment_snapshot(snapshot_ts, analog)
            slot["recorder"].record_raw_snapshot(snapshot_ts, raw_snapshot)
            self._clear_recording_error(slot)
        except Exception as exc:
            self._mark_recording_error(slot, exc)

    def _save_checkpoint_if_due(self, device_id: str) -> None:
        with self._lock:
            slot = self._device_slots.get(device_id)
            if slot is None or slot.get("recorder") is None:
                return
            recorder = slot["recorder"]
            state = deepcopy(slot["state"])
        try:
            recorder.save_checkpoint(state)
            self._clear_recording_error(slot)
        except Exception as exc:
            with self._lock:
                self._mark_recording_error(slot, exc)

    def _recompute_sample_counts(self, slot: dict[str, Any]) -> None:
        values = slot["values"]
        metrics = sum(1 for item in self._catalog if item.get("area") == "input_register" and item["id"] in values)
        statuses = sum(1 for item in self._catalog if item.get("area") == "discrete_input" and item["id"] in values)
        controls = sum(1 for item in self._catalog if item.get("group") in {"runtime_control", "diagnostic"} and item["id"] in values)
        parameters = sum(
            1 for item in self._catalog
            if item.get("area") == "holding_register"
            and CONFIG_REGION_START <= int(item.get("address") or -1) < RUNTIME_REGION_START
            and item["id"] in values
        )
        history = sum(len(rows) for rows in slot["history"].values()) + sum(
            len(rows) for rows in slot.get("history_archive", {}).values()
        )
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
        words = [int(word) for word in raw_values[:word_length]]
        data_type = str(item.get("dataType") or "uint16")
        if data_type == "float32" and len(words) == 2:
            # 固件用 IEEE-754 NaN 表示尚未产生的运行时浮点量（例如尚未
            # 开始加热会话时的起始湿度和预测峰值）。报文通信本身是成功的，
            # 上位机应将这种值投影为“暂无数据”，不能把整块轮询判为异常。
            raw_float = ((words[0] & 0xFFFF) << 16) | (words[1] & 0xFFFF)
            if raw_float & 0x7F800000 == 0x7F800000:
                return None
        value = decode_words(words, data_type)
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

    @_serialized_lifecycle
    def poll_slow_group(self, device_id: str) -> dict[str, Any]:
        slot = self._get_device_slot_required(device_id)
        if not slot["state"].get("running"):
            raise ValueError("live acquisition session is not running for this device")
        parameter_commands = [
            item
            for item in self._default_polling_commands
            if item.get("sourceGroup") == "slow"
        ]
        if not parameter_commands:
            return {"ok": True, "message": "no parameter polling commands", "blockCount": 0}
        device = deepcopy(slot["config"])
        port_key = _device_port_key(device)
        with self._port_io_lock(port_key):
            self._close_runner_client_for_port(port_key)
            client = self._open_manual_client(device, device_id)
            try:
                completed = 0
                for command in parameter_commands:
                    if self._poll_command(device_id, client, command):
                        completed += 1
            finally:
                client.close()
        if completed != len(parameter_commands):
            raise ModbusError("协议版本未通过，参数轮询未执行")
        return {
            "ok": True,
            "message": f"polled {completed} parameter commands",
            "blockCount": completed,
        }

    @staticmethod
    def _strict_bool(value: Any, field_name: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in {0, 1}:
            return bool(value)
        raise ValueError(f"{field_name} 必须是布尔值")

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
