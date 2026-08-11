from __future__ import annotations

import json
import os
import shutil
import time
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _slug(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(text or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "device"


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _interval_key(dt: datetime) -> str:
    hour = dt.hour
    return dt.strftime("%Y_%m_%d") + f"_{hour:02d}00-{hour + 1:02d}00"


def _fsync_path(path: Path) -> None:
    fd: int | None = None
    try:
        fd = os.open(str(path), os.O_RDONLY)
        os.fsync(fd)
    except OSError:
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


class LiveSessionRecorder:
    def __init__(self, sessions_root: Path, device: dict[str, Any], config_snapshot: dict[str, Any] | None = None) -> None:
        self.sessions_root = Path(sessions_root)
        self.device = dict(device)
        self.config_snapshot = dict(config_snapshot or {})
        self.started_at = datetime.now()
        session_name = f"{self.started_at.strftime('%Y%m%d_%H%M%S')}_{_slug(device.get('name') or device.get('id') or 'device')}"
        self.session_dir = self._reserve_session_dir(session_name)
        self.data_dir = self.session_dir / "data_0"
        self.breath_dir = self.session_dir / "breath_data"
        self.run_dir = self.session_dir / "run"
        self.traffic_dir = self.session_dir / "traffic"
        self.heat_dir = self.session_dir / "heat_events"
        self.meta_path = self.session_dir / "session_meta.json"
        self.checkpoint_path = self.session_dir / "checkpoint.json"
        self._current_interval = _interval_key(self.started_at)
        self._env_path = self._interval_env_path()
        self._breath_path = self._interval_breath_path()
        self._run_path = self._interval_run_path()
        self._traffic_path = self._interval_traffic_path()
        self._raw_path = self._interval_raw_path()
        self._heat_path = self._interval_heat_path()
        self.last_env_second: str | None = None
        self.last_breath_state: int | None = None
        self.last_state_change: datetime | None = None
        self.last_written_snapshot: dict[str, Any] | None = None
        self._pending_env_timestamp: datetime | None = None
        self._pending_env_snapshot: dict[str, Any] | None = None
        self._last_checkpoint_epoch = 0.0
        self._last_checkpoint_state: dict[str, Any] | None = None
        self._io_lock = threading.RLock()
        self._finalized = False
        self._prepare()

    def _reserve_session_dir(self, session_name: str) -> Path:
        """原子地预留会话目录，避免同秒启动覆盖已有会话。"""
        counter = 0
        while True:
            suffix = "" if counter == 0 else f"_{counter:02d}"
            candidate = self.sessions_root / f"{session_name}{suffix}"
            try:
                candidate.mkdir(parents=True, exist_ok=False)
                return candidate
            except FileExistsError:
                counter += 1

    def _interval_env_path(self) -> Path:
        return self.data_dir / f"sensor_{self._current_interval[:10]}.csv"

    def _interval_breath_path(self) -> Path:
        return self.breath_dir / f"breath_{self._current_interval}.csv"

    def _interval_run_path(self) -> Path:
        return self.run_dir / f"acquisition_{self._current_interval}.csv"

    def _interval_traffic_path(self) -> Path:
        return self.traffic_dir / f"traffic_{self._current_interval}.csv"

    def _interval_raw_path(self) -> Path:
        return self.data_dir / f"raw_{self._current_interval}.jsonl"

    def _interval_heat_path(self) -> Path:
        return self.heat_dir / f"heat_{self._current_interval}.csv"

    @property
    def env_path(self) -> Path:
        return self._env_path

    @property
    def breath_path(self) -> Path:
        return self._breath_path

    @property
    def run_path(self) -> Path:
        return self._run_path

    @property
    def traffic_path(self) -> Path:
        return self._traffic_path

    @property
    def raw_path(self) -> Path:
        return self._raw_path

    def _prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.breath_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_environment_file()
        self._breath_path.touch()
        self._run_path.touch()
        self._atomic_write_json(self.session_dir / "config.json", self.config_snapshot)
        self._write_meta(status="recording", ended_at=None)

    def _roll_interval(self, now: datetime) -> None:
        next_key = _interval_key(now)
        if next_key == self._current_interval:
            return
        self._current_interval = next_key
        self._env_path = self._interval_env_path()
        self._breath_path = self._interval_breath_path()
        self._run_path = self._interval_run_path()
        self._traffic_path = self._interval_traffic_path()
        self._raw_path = self._interval_raw_path()
        self._heat_path = self._interval_heat_path()
        self._ensure_environment_file()
        self._breath_path.touch()
        self._run_path.touch()

    def _write_meta(self, status: str, ended_at: str | None) -> None:
        meta = {
            "device": self.device,
            "started_at": _fmt_ts(self.started_at),
            "ended_at": ended_at,
            "status": status,
            "paths": {
                "config": "config.json",
                "environment": str(self._env_path.relative_to(self.session_dir)),
                "breath": str(self._breath_path.relative_to(self.session_dir)),
                "run": str(self._run_path.relative_to(self.session_dir)),
                "traffic": str(self._traffic_path.relative_to(self.session_dir)),
                "heat_events": str(self._heat_path.relative_to(self.session_dir)),
                "raw": str(self._raw_path.relative_to(self.session_dir)),
            },
            "format": {
                "environment": "下位机传感器 CSV：timestamp,pressure,flow_rate,t1_temperature,t1_humidity,t2_temperature,t2_humidity,t3_temperature,t3_humidity",
                "breath": "uses firmware breath_state and persists per second",
                "run": "compatible with RUN_ROW_RE",
                "traffic": "one JSON object per line, abnormal command/response records only",
            },
        }
        self._atomic_write_json(self.meta_path, meta)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(path)
            _fsync_path(path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def _ensure_environment_file(self) -> None:
        """创建与下位机一致的传感器 CSV，并且只写入一次表头。"""
        if self._env_path.exists() and self._env_path.stat().st_size > 0:
            return
        self._env_path.parent.mkdir(parents=True, exist_ok=True)
        self._env_path.write_text(
            "timestamp,pressure,flow_rate,t1_temperature,t1_humidity,"
            "t2_temperature,t2_humidity,t3_temperature,t3_humidity\n",
            encoding="utf-8",
        )

    def _append_line(self, path: Path, line: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()

    def record_environment_snapshot(self, timestamp: datetime, snapshot: dict[str, Any]) -> None:
        with self._io_lock:
            second_key = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if self.last_env_second == second_key:
                self.last_written_snapshot = dict(snapshot)
                self._pending_env_snapshot = dict(snapshot)
                return
            self._flush_pending_environment()
            self.last_env_second = second_key
            self.last_written_snapshot = dict(snapshot)
            self._pending_env_timestamp = timestamp
            self._pending_env_snapshot = dict(snapshot)

    @staticmethod
    def _csv_number(value: Any) -> str:
        if value is None or value == "":
            return ""
        return f"{float(value):.2f}"

    def _flush_pending_environment(self) -> None:
        timestamp = self._pending_env_timestamp
        snapshot = self._pending_env_snapshot
        if timestamp is None or snapshot is None:
            return
        self._roll_interval(timestamp)
        values = (
            snapshot.get("pressure"),
            snapshot.get("flow"),
            snapshot.get("sensor_1.temperature", snapshot.get("temperature")),
            snapshot.get("sensor_1.humidity", snapshot.get("humidity")),
            snapshot.get("sensor_2.temperature"),
            snapshot.get("sensor_2.humidity"),
            snapshot.get("sensor_3.temperature"),
            snapshot.get("sensor_3.humidity"),
        )
        line = _fmt_ts(timestamp) + "," + ",".join(self._csv_number(value) for value in values) + "\n"
        self._append_line(self._env_path, line)
        if snapshot.get("flow") is not None:
            self._record_breath(
                timestamp,
                float(snapshot["flow"]),
                snapshot.get("breath_state"),
            )
        self._pending_env_timestamp = None
        self._pending_env_snapshot = None

    def record_raw_snapshot(self, timestamp: datetime, register_values: dict[str, Any]) -> None:
        with self._io_lock:
            self._roll_interval(timestamp)
            payload = {
                "timestamp": _fmt_ts(timestamp),
                "registerValues": dict(register_values),
            }
            self._append_line(self._raw_path, json.dumps(payload, ensure_ascii=False) + "\n")

    def record_traffic_entry(self, entry: dict[str, Any]) -> None:
        status = str(entry.get("status") or "").lower()
        if status not in {"no_response", "error"}:
            return
        with self._io_lock:
            now = datetime.now()
            self._roll_interval(now)
            self.traffic_dir.mkdir(parents=True, exist_ok=True)
            self._traffic_path.touch(exist_ok=True)
            self._append_line(self._traffic_path, json.dumps(entry, ensure_ascii=False) + "\n")

    def save_checkpoint(self, state: dict[str, Any], *, force: bool = False) -> None:
        with self._io_lock:
            self._last_checkpoint_state = dict(state)
            now = time.monotonic()
            if not force and now - self._last_checkpoint_epoch < 30.0:
                return
            self._last_checkpoint_epoch = now
            self._atomic_write_json(self.checkpoint_path, {
                "updated_at": _fmt_ts(datetime.now()), "state": state,
            })

    def _record_breath(self, timestamp: datetime, flow_value: float, firmware_state: Any = None) -> None:
        if firmware_state in {0, 1, 2}:
            state = int(firmware_state)
        elif flow_value >= 0.5:
            state = 1
        elif flow_value <= -0.5:
            state = 0
        else:
            state = 2
        rhythm = 0
        if self.last_breath_state is None or self.last_breath_state != state:
            rhythm = 1
            self.last_breath_state = state
            self.last_state_change = timestamp
        elapsed = 0.0
        if self.last_state_change is not None:
            elapsed = max(0.0, (timestamp - self.last_state_change).total_seconds())
        line = f"{_fmt_ts(timestamp)},{state},{flow_value:.2f},{elapsed:.1f},{rhythm}\n"
        self._append_line(self._breath_path, line)

    def record_log(self, level: str, timestamp: datetime, message: str) -> None:
        with self._io_lock:
            self._roll_interval(timestamp)
            level_code = str(level or "I").upper()[:1]
            if level_code not in {"I", "W", "E"}:
                level_code = "I"
            self._append_line(self._run_path, f"{level_code}/YLDQ [{_fmt_ts(timestamp)}] {message}\n")

    def record_heat_event(self, timestamp: datetime, channel: str, event: str, detail: str = "") -> None:
        with self._io_lock:
            self._roll_interval(timestamp)
            self.heat_dir.mkdir(parents=True, exist_ok=True)
            self._heat_path.touch(exist_ok=True)
            safe_detail = str(detail or "").replace(",", "，").replace("\n", " ")
            self._append_line(self._heat_path, f"{_fmt_ts(timestamp)},{channel},{event},{safe_detail}\n")

    def finalize(self, status: str = "stopped") -> None:
        with self._io_lock:
            if self._finalized:
                return
            self._flush_pending_environment()
            if self._last_checkpoint_state is not None:
                self.save_checkpoint(self._last_checkpoint_state, force=True)
            self._atomic_write_json(self.session_dir / "config.json", self.config_snapshot)
            self._write_meta(status=status, ended_at=_fmt_ts(datetime.now()))
            for p in (self._env_path, self._breath_path, self._run_path, self._traffic_path, self._heat_path):
                if p.exists():
                    _fsync_path(p)
            self._finalized = True

    def export_to(self, export_root: Path) -> Path:
        with self._io_lock:
            self._flush_pending_environment()
            return self._export_to_locked(export_root)

    def _export_to_locked(self, export_root: Path) -> Path:
        export_root = Path(export_root)
        session_dir_resolved = self.session_dir.resolve()
        export_root_resolved = export_root.resolve()
        try:
            export_root_resolved.relative_to(session_dir_resolved)
        except ValueError:
            pass
        else:
            raise ValueError("export root cannot be inside the current live session directory")

        export_root.mkdir(parents=True, exist_ok=True)
        device_name = _slug(self.device.get("name") or "device")
        device_id = _slug(self.device.get("id") or "unknown")
        base_dir = export_root / f"{device_name}__{device_id}" / self.session_dir.name
        target_dir = base_dir
        counter = 1
        while target_dir.exists():
            target_dir = Path(str(base_dir) + f"_{counter:02d}")
            counter += 1
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir()

        files_to_copy = [
            Path("config.json"),
            Path("session_meta.json"),
            Path("checkpoint.json"),
        ]
        for rel_path in files_to_copy:
            src = self.session_dir / rel_path
            if src.exists() and not src.is_symlink():
                dst = target_dir / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        patterns = {
            "data_0": ("sensor_*.csv", "raw_*.jsonl"),
            "breath_data": ("breath_*.csv",),
            "run": ("*.csv",),
            "heat_events": ("heat_*.csv",),
            "traffic": ("traffic_*.csv",),
        }
        for folder_name, globs in patterns.items():
            src_dir = self.session_dir / folder_name
            if not src_dir.exists() or src_dir.is_symlink():
                continue
            dst_dir = target_dir / folder_name
            dst_dir.mkdir(parents=True, exist_ok=True)
            for pattern in globs:
                for src_file in sorted(src_dir.glob(pattern)):
                    if src_file.is_file() and not src_file.is_symlink():
                        shutil.copy2(src_file, dst_dir / src_file.name)
        return target_dir
