from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


DEFAULT_BREATH_EVIDENCE_TARGET_COUNT = 3
DEFAULT_HUMIDITY_EVIDENCE_TARGET_COUNT = 3
DEFAULT_BREATH_EVIDENCE_INTERVAL_SEC = 120
DEFAULT_HUMIDITY_EVIDENCE_INTERVAL_SEC = 600
MAX_EVIDENCE_TARGET_COUNT = 10
MAX_EVIDENCE_INTERVAL_SEC = 86400
EXHALE_INTERVAL_WINDOW_SIZE = 5
EXHALE_TIMEOUT_MIN_DEFAULT_SEC = 300
EXHALE_TIMEOUT_MIN_SEC = 1
EXHALE_TIMEOUT_MAX_SEC = 3600
EXHALE_RECOVERY_MARGIN_PERCENT = 30
EXHALE_TARGET_RAISE_WINDOW_SEC = 5

FAMILY_OTHER = "other"
FAMILY_EXHALE = "exhale"
FAMILY_INHALE = "inhale"

ZONE_NEUTRAL = "neutral"
ZONE_HIGH = "high"
ZONE_LOW = "low"


@dataclass
class SimulationParams:
    humidity_enabled: bool = True
    humidity_high_threshold: float = 40
    humidity_low_threshold: float = 37
    humidity_evidence_interval_sec: int = DEFAULT_HUMIDITY_EVIDENCE_INTERVAL_SEC
    humidity_evidence_count: int = DEFAULT_HUMIDITY_EVIDENCE_TARGET_COUNT
    breath_enabled: bool = True
    heat_on_threshold: float = -4
    heat_off_threshold: float = 1
    derange_lt: float = -3
    derange_ht: float = 3
    breath_evidence_interval_sec: int = 60
    breath_evidence_count: int = 3
    exhale_timeout_min_sec: int = 300
    exhale_timeout_sec: int = 1000
    exhale_live_enter_sec: float = 0.5
    temperature_low_threshold: float = -5
    no_record_gap_sec: int = 60
    data_gap_reset_sec: int = 1800
    breath_evidence_timer_enabled: bool = False


@dataclass
class HumidityEvidence:
    zone: str = ZONE_NEUTRAL
    high_count: int = 0
    low_count: int = 0
    next_tick: datetime | None = None


@dataclass
class BreathEvidence:
    family: str = FAMILY_OTHER
    exhale_count: int = 0
    inhale_count: int = 0
    balance_count: int = 0
    last_sample_at: datetime | None = None
    next_tick: datetime | None = None


@dataclass
class ExhaleTracker:
    last_family: str = FAMILY_OTHER
    last_exhale_active_at: datetime | None = None
    last_exhale_end_at: datetime | None = None
    smoothed_interval_sec: int = 0
    predicted_interval_sec: int = 0
    recovery_floor_sec: int = 0
    intervals: list[int] = field(default_factory=list)
    next_index: int = 0


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _num(value: Any, fallback: float) -> float:
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _int(value: Any, fallback: int) -> int:
    try:
        if value is None:
            return fallback
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def _bool(value: Any, fallback: bool) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return fallback


def _clamp_count(count: int, fallback: int) -> int:
    if count < 1:
        return fallback
    return min(count, MAX_EVIDENCE_TARGET_COUNT)


def _clamp_interval(interval_sec: int, fallback: int) -> int:
    if interval_sec < 1:
        return fallback
    return min(interval_sec, MAX_EVIDENCE_INTERVAL_SEC)


def _clamp_timeout(timeout_sec: int) -> int:
    if timeout_sec == 0:
        return 0
    return max(EXHALE_TIMEOUT_MIN_SEC, min(timeout_sec, EXHALE_TIMEOUT_MAX_SEC))


def params_from_config(config: dict[str, Any] | None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    overrides = overrides or {}
    humidity = config.get("HumidityValue", {}) if isinstance(config.get("HumidityValue"), dict) else {}
    respiratory = config.get("RespiratoryRate", {}) if isinstance(config.get("RespiratoryRate"), dict) else {}
    respiratory_infor = respiratory.get("infor", {}) if isinstance(respiratory.get("infor"), dict) else {}
    temperature = config.get("Temperature", {}) if isinstance(config.get("Temperature"), dict) else {}
    base = {
        "humidity_enabled": _bool(humidity.get("Priority", humidity.get("VSW")), True),
        "humidity_high_threshold": _num(humidity.get("HThreshold"), 40),
        "humidity_low_threshold": _num(humidity.get("LThreshold"), 37),
        "humidity_evidence_interval_sec": _clamp_interval(
            _int(humidity.get("HeatEvidenceIntervalSec"), DEFAULT_HUMIDITY_EVIDENCE_INTERVAL_SEC),
            DEFAULT_HUMIDITY_EVIDENCE_INTERVAL_SEC,
        ),
        "humidity_evidence_count": _clamp_count(
            _int(humidity.get("HeatEvidenceCount"), DEFAULT_HUMIDITY_EVIDENCE_TARGET_COUNT),
            DEFAULT_HUMIDITY_EVIDENCE_TARGET_COUNT,
        ),
        "breath_enabled": _bool(respiratory_infor.get("Priority", respiratory.get("VSW")), True),
        "heat_on_threshold": _num(respiratory.get("HeatOnThreshold"), -4),
        "heat_off_threshold": _num(respiratory.get("HeatOffThreshold"), 1),
        "derange_lt": _num(respiratory.get("DERangeLT"), -3),
        "derange_ht": _num(respiratory.get("DERangeHT"), 3),
        "breath_evidence_interval_sec": _clamp_interval(
            _int(respiratory.get("HeatEvidenceIntervalSec"), DEFAULT_BREATH_EVIDENCE_INTERVAL_SEC),
            DEFAULT_BREATH_EVIDENCE_INTERVAL_SEC,
        ),
        "breath_evidence_count": _clamp_count(
            _int(respiratory.get("HeatEvidenceCount"), DEFAULT_BREATH_EVIDENCE_TARGET_COUNT),
            DEFAULT_BREATH_EVIDENCE_TARGET_COUNT,
        ),
        "exhale_timeout_min_sec": _clamp_timeout(
            _int(respiratory.get("ExhaleTimeoutMinSec"), EXHALE_TIMEOUT_MIN_DEFAULT_SEC)
        )
        or EXHALE_TIMEOUT_MIN_DEFAULT_SEC,
        "exhale_timeout_sec": _clamp_timeout(_int(respiratory.get("ExhaleTimeoutSec"), 0)),
        "exhale_live_enter_sec": _num(respiratory.get("ExhaleLiveEnterSec"), 0.5),
        "temperature_low_threshold": _num(temperature.get("LThreshold"), -5),
        "no_record_gap_sec": max(1, _int(overrides.get("no_record_gap_sec"), 60)),
        "data_gap_reset_sec": max(1, _int(overrides.get("data_gap_reset_sec"), 1800)),
        "breath_evidence_timer_enabled": _bool(overrides.get("breath_evidence_timer_enabled"), False),
    }
    for key, value in overrides.items():
        if key not in base:
            continue
        if key.endswith("_enabled"):
            base[key] = _bool(value, bool(base[key]))
        elif key.endswith("_count"):
            base[key] = _clamp_count(_int(value, int(base[key])), int(base[key]))
        elif key.endswith("_interval_sec"):
            base[key] = _clamp_interval(_int(value, int(base[key])), int(base[key]))
        elif key.endswith("_timeout_sec") or key.endswith("_timeout_min_sec"):
            base[key] = _clamp_timeout(_int(value, int(base[key]))) or int(base[key])
        else:
            base[key] = _num(value, float(base[key]))
    if base["exhale_timeout_sec"] and base["exhale_timeout_sec"] < base["exhale_timeout_min_sec"]:
        base["exhale_timeout_sec"] = base["exhale_timeout_min_sec"]
    return base


def _humidity_zone(humidity: float, params: SimulationParams) -> str:
    if humidity > params.humidity_high_threshold:
        return ZONE_HIGH
    if humidity < params.humidity_low_threshold:
        return ZONE_LOW
    return ZONE_NEUTRAL


def _heat_activity_family(flow: float, params: SimulationParams) -> str:
    if flow <= params.heat_on_threshold:
        return FAMILY_EXHALE
    if flow >= params.heat_off_threshold:
        return FAMILY_INHALE
    return FAMILY_OTHER


def _breath_state_family(row: dict[str, Any] | None, params: SimulationParams) -> str:
    if row is None:
        return FAMILY_OTHER
    state = row.get("state")
    if state in (0, 3):
        return FAMILY_EXHALE
    if state in (1, 4):
        return FAMILY_INHALE
    flow = _num(row.get("flow_rate", row.get("flow")), 0)
    if flow < params.derange_lt:
        return FAMILY_EXHALE
    if flow > params.derange_ht:
        return FAMILY_INHALE
    return FAMILY_OTHER


def _ordered_intervals(tracker: ExhaleTracker) -> list[int]:
    if len(tracker.intervals) < EXHALE_INTERVAL_WINDOW_SIZE:
        return list(tracker.intervals)
    return tracker.intervals[tracker.next_index :] + tracker.intervals[: tracker.next_index]


def _short_average(ordered: list[int]) -> int:
    if not ordered:
        return 0
    count = min(len(ordered), 3)
    return sum(ordered[-count:]) // count


def _long_average(ordered: list[int]) -> int:
    if not ordered:
        return 0
    if len(ordered) < EXHALE_INTERVAL_WINDOW_SIZE:
        return sum(ordered) // len(ordered)
    sorted_values = sorted(ordered)
    trimmed = sorted_values[1:-1]
    return sum(trimmed) // len(trimmed)


def _volatility_ratio_percent(sorted_values: list[int]) -> int:
    if len(sorted_values) < 2:
        return 0
    average = max(1, sum(sorted_values) // len(sorted_values))
    return int(((sorted_values[-1] - sorted_values[0]) * 100) / average)


def _limit_prediction_step(previous: int, raw: int) -> int:
    _ = previous
    return raw


def _refresh_prediction(tracker: ExhaleTracker) -> None:
    ordered = _ordered_intervals(tracker)
    if not ordered:
        tracker.predicted_interval_sec = 0
        return
    sorted_values = sorted(ordered)
    short_sec = _short_average(ordered)
    long_sec = _long_average(ordered)
    smoothed = tracker.smoothed_interval_sec or short_sec
    if len(ordered) == 1:
        raw = ordered[0]
    elif _volatility_ratio_percent(sorted_values) >= 50:
        raw = ((short_sec * 5) + (long_sec * 5)) // 10
    else:
        raw = ((short_sec * 7) + (long_sec * 3)) // 10
    raw = ((raw * 3) + (smoothed * 2)) // 5
    tracker.predicted_interval_sec = _limit_prediction_step(tracker.predicted_interval_sec, raw)


def _update_recovery_floor(tracker: ExhaleTracker, interval_sec: int, current_timeout_sec: int) -> None:
    if interval_sec <= 0 or current_timeout_sec <= 0:
        tracker.recovery_floor_sec = 0
        return
    if interval_sec < current_timeout_sec and (current_timeout_sec - interval_sec) > EXHALE_TARGET_RAISE_WINDOW_SEC:
        tracker.recovery_floor_sec = 0
        return
    base_sec = max(interval_sec, current_timeout_sec)
    tracker.recovery_floor_sec = base_sec + ((base_sec * EXHALE_RECOVERY_MARGIN_PERCENT) // 100)


def _record_exhale_interval(
    tracker: ExhaleTracker,
    interval_sec: int,
    min_interval_sec: int = 0,
    current_timeout_sec: int = 0,
) -> None:
    if interval_sec <= 0:
        return
    normalized_interval_sec = interval_sec
    if min_interval_sec > 0 and normalized_interval_sec < min_interval_sec:
        normalized_interval_sec = min_interval_sec
    if len(tracker.intervals) < EXHALE_INTERVAL_WINDOW_SIZE:
        tracker.intervals.append(normalized_interval_sec)
        tracker.next_index = len(tracker.intervals) % EXHALE_INTERVAL_WINDOW_SIZE
    else:
        tracker.intervals[tracker.next_index] = normalized_interval_sec
        tracker.next_index = (tracker.next_index + 1) % EXHALE_INTERVAL_WINDOW_SIZE
    if tracker.smoothed_interval_sec == 0:
        tracker.smoothed_interval_sec = normalized_interval_sec
    else:
        tracker.smoothed_interval_sec = ((tracker.smoothed_interval_sec * 7) + (normalized_interval_sec * 3)) // 10
    _update_recovery_floor(tracker, interval_sec, current_timeout_sec)
    _refresh_prediction(tracker)


def _update_exhale_tracker(
    tracker: ExhaleTracker,
    family: str,
    now: datetime,
    min_interval_sec: int,
    current_timeout_sec: int,
) -> None:
    if family == FAMILY_EXHALE:
        tracker.last_exhale_active_at = now
        if tracker.last_family != FAMILY_EXHALE:
            reference = tracker.last_exhale_end_at
            if reference and now > reference:
                _record_exhale_interval(
                    tracker,
                    int((now - reference).total_seconds()),
                    min_interval_sec,
                    current_timeout_sec,
                )
            tracker.last_family = FAMILY_EXHALE
        return
    if tracker.last_family == FAMILY_EXHALE:
        tracker.last_exhale_end_at = now
    tracker.last_family = family


def _dynamic_timeout_sec(tracker: ExhaleTracker, params: SimulationParams) -> int:
    max_limit = _clamp_timeout(params.exhale_timeout_sec)
    if max_limit == 0:
        return 0
    min_limit = _clamp_timeout(params.exhale_timeout_min_sec) or EXHALE_TIMEOUT_MIN_DEFAULT_SEC
    max_limit = max(max_limit, min_limit)
    if tracker.predicted_interval_sec <= 0:
        return max_limit
    timeout = (tracker.predicted_interval_sec * 3) // 2
    if tracker.recovery_floor_sec > 0 and timeout < tracker.recovery_floor_sec:
        timeout = tracker.recovery_floor_sec
    return max(min_limit, min(timeout, max_limit))


def _is_exhale_live(tracker: ExhaleTracker, now: datetime, live_enter_sec: int) -> bool:
    if tracker.last_family == FAMILY_EXHALE:
        return True
    if tracker.last_exhale_active_at is None:
        return False
    return (now - tracker.last_exhale_active_at).total_seconds() <= max(0.0, float(live_enter_sec))


def _timeout_due_at(
    heating_on: bool,
    heating_start: datetime | None,
    tracker: ExhaleTracker,
    params: SimulationParams,
    now: datetime,
) -> datetime | None:
    if not heating_on or heating_start is None or not params.breath_enabled:
        return None
    timeout_sec = _dynamic_timeout_sec(tracker, params)
    if timeout_sec <= 0 or _is_exhale_live(tracker, now, params.exhale_live_enter_sec):
        return None
    reference = tracker.last_exhale_end_at or heating_start
    due = reference + timedelta(seconds=timeout_sec)
    return due if due > now else now


def _serialize_dt(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _normalize_environment_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        ts = _parse_dt(row.get("ts", row.get("timestamp")))
        if ts is None:
            continue
        normalized.append(
            {
                "timestamp": ts,
                "humidity": _num(row.get("humidity"), 0),
                "temperature": _num(row.get("temperature"), 0),
                "pressure": _num(row.get("pressure"), 0),
                "flow": _num(row.get("flow"), 0),
            }
        )
    normalized.sort(key=lambda item: item["timestamp"])
    return normalized


def _normalize_breath_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        ts = _parse_dt(row.get("ts", row.get("timestamp")))
        if ts is None:
            continue
        normalized.append(
            {
                "timestamp": ts,
                "flow_rate": _num(row.get("flow_rate", row.get("flow")), 0),
                "state": _int(row.get("state"), -1),
                "rhythm": _int(row.get("rhythm"), 0),
            }
        )
    normalized.sort(key=lambda item: item["timestamp"])
    return normalized


def _apply_date_filter(rows: list[dict[str, Any]], start: datetime | None, end: datetime | None) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        ts = row["timestamp"]
        if start and ts < start:
            continue
        if end and ts > end:
            continue
        result.append(row)
    return result


def run_simulation(
    environment_rows: list[dict[str, Any]],
    breath_rows: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    date_range: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params_dict = params_from_config(config, overrides)
    params = SimulationParams(**params_dict)
    start = _parse_dt((date_range or {}).get("start"))
    end = _parse_dt((date_range or {}).get("end"))
    env_rows = _apply_date_filter(_normalize_environment_rows(environment_rows), start, end)
    breath_rows = _apply_date_filter(_normalize_breath_rows(breath_rows), start, end)
    if not env_rows and not breath_rows:
        return {
            "params": params_dict,
            "summary": {"actions": 0, "segments": 0, "heating_total_sec": 0},
            "actions": [],
            "segments": [],
            "series": {"environment": [], "breath": []},
            "daily": {},
            "no_record_gaps": [],
        }

    events = []
    for row in env_rows:
        events.append(("env", row["timestamp"], row))
    for row in breath_rows:
        events.append(("breath", row["timestamp"], row))
    events.sort(key=lambda item: (item[1], 0 if item[0] == "env" else 1))

    humidity_evidence = HumidityEvidence()
    breath_evidence = BreathEvidence()
    exhale_tracker = ExhaleTracker()
    actions: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    no_record_gaps: list[dict[str, Any]] = []
    heating_on = False
    heating_start: datetime | None = None
    current_env: dict[str, Any] | None = None
    current_breath: dict[str, Any] | None = None
    env_index = 0
    breath_index = 0
    event_index = 0
    now = events[0][1]
    last_breath_at: datetime | None = None
    last_breath_row: dict[str, Any] | None = None

    def add_action(ts: datetime, action_type: str, reason: str, row_type: str = "logic") -> None:
        actions.append(
            {
                "ts": _serialize_dt(ts),
                "type": action_type,
                "reason": reason,
                "source": row_type,
                "heating": heating_on,
                "humidity": current_env.get("humidity") if current_env else None,
                "temperature": current_env.get("temperature") if current_env else None,
                "flow_rate": current_breath.get("flow_rate") if current_breath else None,
                "humidity_high_count": humidity_evidence.high_count,
                "humidity_low_count": humidity_evidence.low_count,
                "breath_exhale_count": breath_evidence.exhale_count,
                "breath_inhale_count": breath_evidence.inhale_count,
                "predicted_interval_sec": exhale_tracker.predicted_interval_sec,
                "timeout_sec": _dynamic_timeout_sec(exhale_tracker, params),
            }
        )

    def breath_state_name(row: dict[str, Any] | None) -> str:
        if not row:
            return "未知"
        state = row.get("state")
        if state == 0:
            return "呼气"
        if state == 1:
            return "吸气"
        if state == 2:
            return "无呼吸"
        if state == 3:
            return "低流速告警"
        if state == 4:
            return "高流速告警"
        return "未知"

    def turn_on(ts: datetime) -> None:
        nonlocal heating_on, heating_start
        if heating_on:
            return
        heating_on = True
        heating_start = ts
        add_action(ts, "heat_on", "湿度高证据+出气证据满足")

    def turn_off(ts: datetime, reason: str) -> None:
        nonlocal heating_on, heating_start
        if not heating_on:
            return
        start_at = heating_start or ts
        segments.append(
            {
                "start": _serialize_dt(start_at),
                "end": _serialize_dt(ts),
                "duration_sec": max(0, int((ts - start_at).total_seconds())),
                "state": "heating",
                "end_reason": reason,
            }
        )
        heating_on = False
        heating_start = None
        exhale_tracker.last_family = FAMILY_OTHER
        exhale_tracker.last_exhale_active_at = None
        exhale_tracker.last_exhale_end_at = None
        exhale_tracker.recovery_floor_sec = 0
        if reason == "出气预测超时关闭":
            breath_evidence.exhale_count = 0
            breath_evidence.inhale_count = 0
            breath_evidence.balance_count = 0
            breath_evidence.last_sample_at = None
            breath_evidence.next_tick = None
        add_action(ts, "heat_off", reason)

    def reset_breath_state() -> None:
        breath_evidence.family = FAMILY_OTHER
        breath_evidence.exhale_count = 0
        breath_evidence.inhale_count = 0
        breath_evidence.balance_count = 0
        breath_evidence.last_sample_at = None
        breath_evidence.next_tick = None
        exhale_tracker.last_family = FAMILY_OTHER
        exhale_tracker.last_exhale_active_at = None
        exhale_tracker.last_exhale_end_at = None
        exhale_tracker.recovery_floor_sec = 0

    def update_humidity(ts: datetime, force_tick: bool = False) -> None:
        if not params.humidity_enabled or current_env is None:
            return
        zone = _humidity_zone(current_env["humidity"], params)
        if zone == ZONE_HIGH:
            if humidity_evidence.zone != ZONE_HIGH:
                humidity_evidence.zone = ZONE_HIGH
                humidity_evidence.high_count = 1
                humidity_evidence.low_count = 0
                humidity_evidence.next_tick = ts + timedelta(seconds=params.humidity_evidence_interval_sec)
            elif force_tick:
                humidity_evidence.high_count = min(params.humidity_evidence_count, humidity_evidence.high_count + 1)
                humidity_evidence.next_tick = ts + timedelta(seconds=params.humidity_evidence_interval_sec)
        elif zone == ZONE_LOW:
            if humidity_evidence.zone != ZONE_LOW:
                humidity_evidence.zone = ZONE_LOW
                humidity_evidence.low_count = 1
                humidity_evidence.high_count = 0
                humidity_evidence.next_tick = ts + timedelta(seconds=params.humidity_evidence_interval_sec)
            elif force_tick:
                humidity_evidence.low_count = min(params.humidity_evidence_count, humidity_evidence.low_count + 1)
                humidity_evidence.next_tick = ts + timedelta(seconds=params.humidity_evidence_interval_sec)
        else:
            humidity_evidence.zone = ZONE_NEUTRAL
            humidity_evidence.high_count = 0
            humidity_evidence.low_count = 0
            humidity_evidence.next_tick = None

    def update_breath(ts: datetime, force_tick: bool = False) -> None:
        if not params.breath_enabled or current_breath is None:
            return
        family = _heat_activity_family(current_breath["flow_rate"], params)
        tracker_family = _breath_state_family(current_breath, params)
        breath_evidence.family = family
        if heating_on:
            current_timeout_sec = _dynamic_timeout_sec(exhale_tracker, params)
            _update_exhale_tracker(
                exhale_tracker,
                tracker_family,
                ts,
                params.breath_evidence_interval_sec,
                current_timeout_sec,
            )
        if family == FAMILY_OTHER:
            breath_evidence.next_tick = None
            return
        if breath_evidence.last_sample_at is not None:
            due_at = breath_evidence.last_sample_at + timedelta(seconds=params.breath_evidence_interval_sec)
            if ts < due_at:
                breath_evidence.next_tick = due_at if params.breath_evidence_timer_enabled else None
                return
        balance = breath_evidence.balance_count
        if family == FAMILY_EXHALE:
            if balance < 0:
                balance = 0
            if balance < params.breath_evidence_count:
                balance += 1
        elif family == FAMILY_INHALE:
            if balance > 0:
                balance = 0
            if balance > -params.breath_evidence_count:
                balance -= 1
        breath_evidence.balance_count = balance
        if balance > 0:
            breath_evidence.exhale_count = balance
            breath_evidence.inhale_count = 0
        elif balance < 0:
            breath_evidence.exhale_count = 0
            breath_evidence.inhale_count = -balance
        else:
            breath_evidence.exhale_count = 0
            breath_evidence.inhale_count = 0
        breath_evidence.last_sample_at = ts
        stable_until = current_breath.get("_stable_until") if isinstance(current_breath, dict) else None
        next_due = ts + timedelta(seconds=params.breath_evidence_interval_sec)
        should_continue_stable = (
            stable_until is not None
            and family != FAMILY_OTHER
            and next_due <= stable_until
        )
        breath_evidence.next_tick = (
            next_due
            if params.breath_evidence_timer_enabled or should_continue_stable
            else None
        )

    def evaluate(ts: datetime) -> None:
        if params.humidity_enabled and humidity_evidence.low_count >= params.humidity_evidence_count:
            turn_off(ts, "湿度低关闭")
            return
        if params.breath_enabled and breath_evidence.inhale_count >= params.breath_evidence_count:
            turn_off(ts, "吸气确认关闭")
            return
        if params.breath_enabled and heating_on and heating_start and not _is_exhale_live(exhale_tracker, ts, params.exhale_live_enter_sec):
            timeout_sec = _dynamic_timeout_sec(exhale_tracker, params)
            if timeout_sec:
                reference = exhale_tracker.last_exhale_end_at or heating_start
                if (ts - reference).total_seconds() >= timeout_sec:
                    turn_off(ts, "出气预测超时关闭")
                    return
        humidity_ready = (not params.humidity_enabled) or humidity_evidence.high_count >= params.humidity_evidence_count
        breath_ready = (not params.breath_enabled) or breath_evidence.exhale_count >= params.breath_evidence_count
        temp_ready = current_env is not None and current_env["temperature"] > params.temperature_low_threshold
        if humidity_ready and breath_ready and temp_ready:
            turn_on(ts)

    max_steps = max(1000, (len(events) * 8) + 10000)
    steps = 0
    while steps < max_steps:
        steps += 1
        next_event_time = events[event_index][1] if event_index < len(events) else None
        candidates = [time for time in [next_event_time, humidity_evidence.next_tick, breath_evidence.next_tick, _timeout_due_at(heating_on, heating_start, exhale_tracker, params, now)] if time]
        if not candidates:
            break
        next_time = min(candidates)
        now = next_time
        if humidity_evidence.next_tick and humidity_evidence.next_tick <= now:
            update_humidity(now, force_tick=True)
            evaluate(now)
        if breath_evidence.next_tick and breath_evidence.next_tick <= now:
            update_breath(now, force_tick=True)
            evaluate(now)
        timeout_time = _timeout_due_at(heating_on, heating_start, exhale_tracker, params, now)
        if timeout_time and timeout_time <= now:
            evaluate(now)
        while event_index < len(events) and events[event_index][1] <= now:
            kind, ts, row = events[event_index]
            if kind == "env":
                current_env = row
                env_index += 1
                update_humidity(ts)
            else:
                if last_breath_at and (ts - last_breath_at).total_seconds() > params.no_record_gap_sec:
                    gap_sec = int((ts - last_breath_at).total_seconds())
                    inferred_family = _heat_activity_family(last_breath_row.get("flow_rate", 0), params) if last_breath_row else FAMILY_OTHER
                    no_record_gaps.append(
                        {
                            "start": _serialize_dt(last_breath_at),
                            "end": _serialize_dt(ts),
                            "duration_sec": gap_sec,
                            "inferred_state": breath_state_name(last_breath_row),
                            "inferred_family": inferred_family,
                            "before_state": last_breath_row.get("state") if last_breath_row else None,
                            "before_rhythm": last_breath_row.get("rhythm") if last_breath_row else None,
                            "after_state": row.get("state"),
                            "after_rhythm": row.get("rhythm"),
                        }
                    )
                last_breath_at = ts
                next_breath = breath_rows[breath_index + 1] if (breath_index + 1) < len(breath_rows) else None
                current_breath = dict(row)
                if next_breath is not None:
                    next_gap_sec = int((next_breath["timestamp"] - ts).total_seconds())
                    if next_gap_sec > params.no_record_gap_sec:
                        current_breath["_stable_until"] = next_breath["timestamp"]
                        current_breath["_stable_gap_sec"] = next_gap_sec
                last_breath_row = dict(row)
                breath_index += 1
                update_breath(ts)
            event_index += 1
            evaluate(ts)
        if event_index >= len(events) and not heating_on:
            break

    if heating_on and heating_start:
        end_at = events[-1][1]
        segments.append(
            {
                "start": _serialize_dt(heating_start),
                "end": _serialize_dt(end_at),
                "duration_sec": max(0, int((end_at - heating_start).total_seconds())),
                "state": "heating",
                "end_reason": "数据结束仍在加热",
            }
        )

    durations = [item["duration_sec"] for item in segments]
    reason_counts: dict[str, int] = {}
    for item in segments:
        reason = item.get("end_reason") or "-"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    day_map: dict[str, dict[str, Any]] = {}
    for action in actions:
        day = str(action["ts"])[:10]
        day_map.setdefault(day, {"actions": [], "segments": []})["actions"].append(action)
    for segment in segments:
        day = str(segment["start"])[:10]
        day_map.setdefault(day, {"actions": [], "segments": []})["segments"].append(segment)
    return {
        "params": params_dict,
        "summary": {
            "actions": len(actions),
            "segments": len(segments),
            "heating_total_sec": sum(durations),
            "heating_min_sec": min(durations) if durations else 0,
            "heating_max_sec": max(durations) if durations else 0,
            "heating_avg_sec": round(sum(durations) / len(durations), 1) if durations else 0,
            "off_reason_counts": reason_counts,
            "no_record_gap_count": len(no_record_gaps),
            "environment_rows": len(env_rows),
            "breath_rows": len(breath_rows),
        },
        "actions": actions,
        "segments": segments,
        "series": {
            "environment": [
                {
                    "ts": _serialize_dt(row["timestamp"]),
                    "humidity": row["humidity"],
                    "temperature": row["temperature"],
                    "pressure": row["pressure"],
                    "flow": row["flow"],
                }
                for row in env_rows
            ],
            "breath": [
                {
                    "ts": _serialize_dt(row["timestamp"]),
                    "flow_rate": row["flow_rate"],
                    "state": row["state"],
                    "rhythm": row["rhythm"],
                }
                for row in breath_rows
            ],
        },
        "daily": day_map,
        "no_record_gaps": no_record_gaps,
    }
