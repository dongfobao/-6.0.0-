"""实时采集会话归档查询：扫描会话目录，生成会话索引与事件明细。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

HEAT_CHANNELS = ("HTC1", "HTC2", "防冻")
VALVE_CHANNELS = ("上阀", "左阀", "右阀")
SYSTEM_CHANNEL = "系统"

EVENT_TYPE_OPTIONS = (
    "采集开始", "采集停止",
    "加热开启", "加热关闭",
    "湿度会话开始", "湿度会话结束",
    "阀门状态变化",
)


def _parse_ts(text: Any) -> datetime | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(raw[:26], fmt)
        except ValueError:
            continue
    return None


def _fmt_ts(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _fmt_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "--"
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}小时{minutes:02d}分{secs:02d}秒"
    if minutes:
        return f"{minutes}分{secs:02d}秒"
    return f"{secs}秒"


def _read_meta(session_dir: Path) -> dict[str, Any]:
    meta_path = session_dir / "session_meta.json"
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _iter_heat_events(session_dir: Path) -> list[dict[str, Any]]:
    heat_dir = session_dir / "heat_events"
    if not heat_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    for csv_path in sorted(heat_dir.glob("heat_*.csv")):
        try:
            lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            parts = [part.strip() for part in line.split(",", 3)]
            if len(parts) < 3:
                continue
            ts = _parse_ts(parts[0])
            if ts is None:
                continue
            events.append({
                "time": _fmt_ts(ts),
                "channel": parts[1],
                "event": parts[2],
                "detail": parts[3] if len(parts) > 3 else "",
                "_ts": ts,
            })
    events.sort(key=lambda item: item["_ts"])
    return events


def _summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    channels: dict[str, dict[str, Any]] = {}
    for name in (*HEAT_CHANNELS, *VALVE_CHANNELS):
        channels[name] = {
            "channel": name,
            "kind": "heat" if name in HEAT_CHANNELS else "valve",
            "openCount": 0,
            "activeSeconds": 0.0,
            "actionCount": 0,
            "ongoing": False,
            "lastEvent": "",
            "lastEventTime": "",
        }
    open_since: dict[str, datetime] = {}
    for item in events:
        channel = str(item.get("channel") or "")
        event = str(item.get("event") or "")
        ts = item.get("_ts")
        stats = channels.get(channel)
        if stats is None:
            continue
        stats["lastEvent"] = event
        stats["lastEventTime"] = item.get("time") or ""
        if stats["kind"] == "heat":
            if event == "加热开启":
                stats["openCount"] += 1
                if isinstance(ts, datetime):
                    open_since[channel] = ts
            elif event == "加热关闭":
                start = open_since.pop(channel, None)
                if isinstance(start, datetime) and isinstance(ts, datetime) and ts >= start:
                    stats["activeSeconds"] += (ts - start).total_seconds()
        else:
            if event == "阀门状态变化":
                stats["actionCount"] += 1
    for channel, start in open_since.items():
        channels[channel]["ongoing"] = True
    summary_rows = []
    for name in (*HEAT_CHANNELS, *VALVE_CHANNELS):
        stats = channels[name]
        row = dict(stats)
        row["activeDurationText"] = _fmt_duration(stats["activeSeconds"]) if stats["activeSeconds"] else ("记录中" if stats["ongoing"] else "--")
        summary_rows.append(row)
    return {
        "channels": summary_rows,
        "totalEvents": len(events),
        "heatOpenTotal": sum(channels[name]["openCount"] for name in HEAT_CHANNELS),
        "valveActionTotal": sum(channels[name]["actionCount"] for name in VALVE_CHANNELS),
    }


def _build_session_index(session_dir: Path, meta: dict[str, Any], active_session_names: set[str] | None = None) -> dict[str, Any]:
    started = _parse_ts(meta.get("started_at"))
    ended = _parse_ts(meta.get("ended_at"))
    raw_status = str(meta.get("status") or "unknown")
    device = meta.get("device") if isinstance(meta.get("device"), dict) else {}
    device_id = str(device.get("id") or "")
    recording = raw_status == "recording"
    if recording and active_session_names is not None and session_dir.name not in active_session_names:
        raw_status = "stopped"
    duration_seconds: float | None = None
    if started is not None:
        end_point = ended or (datetime.now() if raw_status == "recording" else None)
        if end_point is not None:
            duration_seconds = max(0.0, (end_point - started).total_seconds())
    return {
        "name": session_dir.name,
        "deviceId": device_id,
        "deviceName": str(device.get("name") or ""),
        "startedAt": _fmt_ts(started) or str(meta.get("started_at") or ""),
        "endedAt": _fmt_ts(ended) or str(meta.get("ended_at") or ""),
        "status": raw_status,
        "durationSeconds": duration_seconds,
        "durationText": _fmt_duration(duration_seconds),
        "_sort": started or datetime.min,
    }


def list_sessions(sessions_root: Path | str, device_id: str | None = None, active_session_names: set[str] | None = None) -> dict[str, Any]:
    root = Path(sessions_root)
    items: list[dict[str, Any]] = []
    if root.exists():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            meta = _read_meta(child)
            if not meta:
                continue
            entry = _build_session_index(child, meta, active_session_names=active_session_names)
            if device_id and entry["deviceId"] != str(device_id):
                continue
            items.append(entry)
    items.sort(key=lambda item: item["_sort"], reverse=True)
    for item in items:
        item.pop("_sort", None)
    return {"items": items, "total": len(items)}


def get_session_detail(sessions_root: Path | str, name: str, active_session_names: set[str] | None = None) -> dict[str, Any]:
    root = Path(sessions_root).resolve()
    safe_name = Path(str(name or "")).name
    if not safe_name or safe_name != str(name or ""):
        raise ValueError("非法会话名称")
    session_dir = (root / safe_name).resolve()
    if session_dir.parent != root or not session_dir.is_dir():
        raise KeyError(f"会话不存在: {safe_name}")
    meta = _read_meta(session_dir)
    if not meta:
        raise KeyError(f"会话缺少元数据: {safe_name}")
    index = _build_session_index(session_dir, meta, active_session_names=active_session_names)
    index.pop("_sort", None)
    events = _iter_heat_events(session_dir)
    summary = _summarize_events(events)
    for item in events:
        item.pop("_ts", None)
    config_path = session_dir / "config.json"
    config_snapshot: dict[str, Any] = {}
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                config_snapshot = payload
        except (OSError, json.JSONDecodeError):
            config_snapshot = {}
    return {
        "session": index,
        "summary": summary,
        "events": events,
        "channels": [*(HEAT_CHANNELS), *(VALVE_CHANNELS), SYSTEM_CHANNEL],
        "eventTypes": list(EVENT_TYPE_OPTIONS),
        "config": config_snapshot,
    }
