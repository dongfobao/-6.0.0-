from __future__ import annotations

import math
import statistics
import time
from typing import Any


def _round(value: float | int | None, digits: int = 2) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return round(float(value), digits)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    data = sorted(float(item) for item in values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return data[low]
    weight = pos - low
    return data[low] * (1 - weight) + data[high] * weight


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.fmean(values)


def _coerce_number(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _get_nested_value(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _iter_schema_scalars(schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scalar_fields: list[dict[str, Any]] = []
    for section in schema or []:
        for field in section.get("fields", []):
            if field.get("type") == "task_array":
                item_schema = field.get("item_schema", [])
                for item in item_schema:
                    scalar_fields.append(
                        {
                            "path_template": f"{field['path']}[*].{item['key']}",
                            "label": item.get("label") or item["key"],
                            "type": item.get("type", "string"),
                            "readonly": item.get("readonly", False),
                        }
                    )
                continue
            scalar_fields.append(
                {
                    "path_template": field["path"],
                    "label": field.get("label") or field["path"],
                    "type": field.get("type", "string"),
                    "readonly": field.get("readonly", False),
                }
            )
    return scalar_fields


def _collect_fallback_paths(config: dict[str, Any], schema: list[dict[str, Any]] | None) -> list[tuple[str, Any, str]]:
    results: list[tuple[str, Any, str]] = []
    if schema:
        for field in _iter_schema_scalars(schema):
            if field["readonly"]:
                continue
            path_template = field["path_template"]
            if "[*]." in path_template:
                prefix, suffix = path_template.split("[*].", 1)
                rows = config.get(prefix, [])
                if isinstance(rows, list):
                    for index, item in enumerate(rows):
                        if not isinstance(item, dict):
                            continue
                        results.append((f"{prefix}[{index}].{suffix}", item.get(suffix), field["label"]))
            else:
                results.append((path_template, _get_nested_value(config, path_template), field["label"]))
        return results

    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                next_prefix = f"{prefix}.{key}" if prefix else key
                walk(value, next_prefix)
            return
        if isinstance(node, list):
            for index, value in enumerate(node):
                next_prefix = f"{prefix}[{index}]"
                walk(value, next_prefix)
            return
        results.append((prefix, node, prefix.rsplit(".", 1)[-1]))

    walk(config)
    return results


def _closest_to_zero(values: list[float]) -> float | None:
    """找到数据中绝对值最小的值（最接近0），用于偏移推荐。"""
    if not values:
        return None
    best = values[0]
    for v in values:
        if abs(v) < abs(best):
            best = v
    return best


def _collect_exhale_durations(breath_rows: list[dict]) -> list[float]:
    """从呼吸数据中提取每次持续呼气的时长（秒）。"""
    durations = []
    prev_state = None
    exhale_start_elapsed = 0
    for row in breath_rows:
        state = row.get("state")
        elapsed = _coerce_number(row.get("elapsed_since_change"))
        if state is None or elapsed is None:
            continue
        state = int(state)
        if state == 0:  # 呼气
            if prev_state != 0:
                exhale_start_elapsed = elapsed
        else:
            if prev_state == 0:
                dur = max(elapsed, exhale_start_elapsed)
                if dur > 0:
                    durations.append(dur)
        prev_state = state
    # 最后一段如果是呼气
    if prev_state == 0:
        last_elapsed = _coerce_number(breath_rows[-1].get("elapsed_since_change")) if breath_rows else 0
        if last_elapsed and last_elapsed > 0:
            durations.append(last_elapsed)
    return durations


def _collect_effective_breath_segment_durations(
    breath_rows: list[dict],
    *,
    derange_ht: float | None,
    derange_lt: float | None,
) -> list[float]:
    """提取连续有效出气/进气段的持续时间。"""
    if not breath_rows:
        return []

    durations: list[float] = []
    current_kind: str | None = None
    current_start_ts: str | None = None
    current_last_ts: str | None = None

    for row in breath_rows:
        flow = _coerce_number(row.get("flow_rate"))
        ts = row.get("ts") or row.get("timestamp")
        if flow is None or not ts:
            if current_kind is not None and current_start_ts and current_last_ts:
                duration = _time_diff_seconds(current_start_ts, current_last_ts)
                if duration > 0:
                    durations.append(duration)
            current_kind = None
            current_start_ts = None
            current_last_ts = None
            continue

        kind: str | None = None
        if derange_lt is not None and derange_lt < 0 and flow < derange_lt:
            kind = "exhale"
        elif derange_ht is not None and derange_ht > 0 and flow > derange_ht:
            kind = "inhale"

        ts_text = str(ts)
        if kind is None:
            if current_kind is not None and current_start_ts and current_last_ts:
                duration = _time_diff_seconds(current_start_ts, current_last_ts)
                if duration > 0:
                    durations.append(duration)
            current_kind = None
            current_start_ts = None
            current_last_ts = None
            continue

        if current_kind == kind:
            current_last_ts = ts_text
            continue

        if current_kind is not None and current_start_ts and current_last_ts:
            duration = _time_diff_seconds(current_start_ts, current_last_ts)
            if duration > 0:
                durations.append(duration)

        current_kind = kind
        current_start_ts = ts_text
        current_last_ts = ts_text

    if current_kind is not None and current_start_ts and current_last_ts:
        duration = _time_diff_seconds(current_start_ts, current_last_ts)
        if duration > 0:
            durations.append(duration)

    return durations


def _collect_effective_breath_segment_directions(
    breath_rows: list[dict],
    *,
    derange_ht: float | None,
    derange_lt: float | None,
    min_duration_sec: float,
) -> list[str]:
    """提取达到最小时长门槛的连续有效进/出气段方向序列。"""
    if not breath_rows:
        return []

    directions: list[str] = []
    current_kind: str | None = None
    current_start_ts: str | None = None
    current_last_ts: str | None = None

    def flush_segment() -> None:
        nonlocal current_kind, current_start_ts, current_last_ts
        if current_kind is None or not current_start_ts or not current_last_ts:
            return
        duration = _time_diff_seconds(current_start_ts, current_last_ts)
        if duration >= min_duration_sec:
            directions.append(current_kind)

    for row in breath_rows:
        flow = _coerce_number(row.get("flow_rate"))
        ts = row.get("ts") or row.get("timestamp")
        if flow is None or not ts:
            flush_segment()
            current_kind = None
            current_start_ts = None
            current_last_ts = None
            continue

        kind: str | None = None
        if derange_lt is not None and derange_lt < 0 and flow < derange_lt:
            kind = "exhale"
        elif derange_ht is not None and derange_ht > 0 and flow > derange_ht:
            kind = "inhale"

        ts_text = str(ts)
        if kind is None:
            flush_segment()
            current_kind = None
            current_start_ts = None
            current_last_ts = None
            continue

        if current_kind == kind:
            current_last_ts = ts_text
            continue

        flush_segment()
        current_kind = kind
        current_start_ts = ts_text
        current_last_ts = ts_text

    flush_segment()
    return directions


def _collect_no_change_gaps(
    breath_rows: list[dict],
    *,
    derange_ht: float | None,
    derange_lt: float | None,
) -> list[float]:
    """统计相邻有效气流通过事件之间的无变化时长。"""
    if not breath_rows:
        return []

    event_times: list[str] = []
    prev_active = False
    for row in breath_rows:
        flow = _coerce_number(row.get("flow_rate"))
        ts = row.get("ts") or row.get("timestamp")
        if flow is None or not ts:
            prev_active = False
            continue

        is_active = False
        if derange_lt is not None and derange_lt < 0 and flow < derange_lt:
            is_active = True
        elif derange_ht is not None and derange_ht > 0 and flow > derange_ht:
            is_active = True

        if is_active and not prev_active:
            event_times.append(str(ts))
        prev_active = is_active

    gaps: list[float] = []
    for index in range(1, len(event_times)):
        gap = _time_diff_seconds(event_times[index - 1], event_times[index])
        if gap > 0:
            gaps.append(gap)
    return gaps


def _collect_rapid_switch_noise_peaks(
    breath_rows: list[dict],
    *,
    switch_window_sec: float = 3.0,
    min_runs_per_cluster: int = 3,
) -> tuple[list[float], list[float], int]:
    """提取几秒内频繁正负切换方向的噪声峰值。"""
    runs: list[dict[str, Any]] = []
    current_sign: int | None = None
    current_start_ts: str | None = None
    current_last_ts: str | None = None
    current_peak = 0.0

    def flush_run() -> None:
        nonlocal current_sign, current_start_ts, current_last_ts, current_peak
        if current_sign is None or not current_start_ts or not current_last_ts:
            return
        runs.append(
            {
                "sign": current_sign,
                "start": current_start_ts,
                "end": current_last_ts,
                "duration": _time_diff_seconds(current_start_ts, current_last_ts),
                "peak": current_peak,
            }
        )

    for row in breath_rows:
        flow = _coerce_number(row.get("flow_rate"))
        ts = row.get("ts") or row.get("timestamp")
        if flow is None or not ts or flow == 0:
            flush_run()
            current_sign = None
            current_start_ts = None
            current_last_ts = None
            current_peak = 0.0
            continue

        sign = 1 if flow > 0 else -1
        peak_value = abs(flow)
        ts_text = str(ts)
        if current_sign == sign:
            current_last_ts = ts_text
            current_peak = max(current_peak, peak_value)
            continue

        flush_run()
        current_sign = sign
        current_start_ts = ts_text
        current_last_ts = ts_text
        current_peak = peak_value

    flush_run()

    positive_peaks: list[float] = []
    negative_peaks: list[float] = []
    cluster_count = 0
    index = 0
    while index < len(runs):
        cluster = [runs[index]]
        next_index = index + 1
        while next_index < len(runs):
            prev = cluster[-1]
            curr = runs[next_index]
            gap = _time_diff_seconds(prev["end"], curr["start"])
            if (
                curr["sign"] != prev["sign"]
                and prev["duration"] <= switch_window_sec
                and curr["duration"] <= switch_window_sec
                and gap <= switch_window_sec
            ):
                cluster.append(curr)
                next_index += 1
                continue
            break

        if len(cluster) >= min_runs_per_cluster:
            cluster_count += 1
            for item in cluster:
                if item["sign"] > 0:
                    positive_peaks.append(item["peak"])
                else:
                    negative_peaks.append(item["peak"])
            index = next_index
            continue

        index += 1

    return positive_peaks, negative_peaks, cluster_count


def _collect_same_direction_run_lengths(directions: list[str]) -> dict[str, list[int]]:
    runs: dict[str, list[int]] = {"exhale": [], "inhale": []}
    if not directions:
        return runs

    current = directions[0]
    length = 1
    for item in directions[1:]:
        if item == current:
            length += 1
            continue
        runs.setdefault(current, []).append(length)
        current = item
        length = 1
    runs.setdefault(current, []).append(length)
    return runs


def _recommend_evidence_count_from_runs(run_lengths: list[int], target_stability: float = 0.85) -> tuple[int | None, dict[str, float | int]]:
    if len(run_lengths) < 10:
        return None, {"run_count": len(run_lengths)}

    max_run = max(run_lengths)
    if max_run < 2:
        return 2, {"run_count": len(run_lengths), "selected_k": 2, "selected_stability": 0.0}

    best_k: int | None = None
    best_stability = 0.0
    for k in range(2, min(max_run, 6) + 1):
        current_count = sum(1 for length in run_lengths if length >= k)
        next_count = sum(1 for length in run_lengths if length >= (k + 1))
        if current_count == 0:
            continue
        stability = next_count / current_count
        if stability >= target_stability:
            best_k = k
            best_stability = stability
            break
        if stability > best_stability:
            best_stability = stability
            best_k = k

    if best_k is None:
        return None, {"run_count": len(run_lengths)}

    return best_k, {
        "run_count": len(run_lengths),
        "selected_k": best_k,
        "selected_stability": round(best_stability, 4),
    }


def _trim_extremes(values: list[float], ratio: float = 0.10) -> list[float]:
    if len(values) < 5:
        return list(values)
    data = sorted(float(item) for item in values)
    trim_count = max(1, int(len(data) * ratio))
    if trim_count * 2 >= len(data):
        return data
    return data[trim_count: len(data) - trim_count]


def _collect_exhale_peak_intervals(
    breath_rows: list[dict],
    *,
    derange_lt: float | None,
    min_interval_sec: float,
) -> list[float]:
    """提取连续有效出气段的负峰值，并计算相邻峰值之间的峰峰值间距。"""
    if not breath_rows or derange_lt is None or derange_lt >= 0:
        return []

    peak_times: list[str] = []
    current_peak_flow: float | None = None
    current_peak_ts: str | None = None

    for row in breath_rows:
        flow = _coerce_number(row.get("flow_rate"))
        ts = row.get("ts") or row.get("timestamp")
        if flow is None or not ts:
            if current_peak_ts is not None:
                peak_times.append(str(current_peak_ts))
            current_peak_flow = None
            current_peak_ts = None
            continue

        is_valid_exhale = flow < derange_lt
        if is_valid_exhale:
            if current_peak_flow is None or flow < current_peak_flow:
                current_peak_flow = flow
                current_peak_ts = str(ts)
            continue

        if current_peak_ts is not None:
            peak_times.append(str(current_peak_ts))
        current_peak_flow = None
        current_peak_ts = None

    if current_peak_ts is not None:
        peak_times.append(str(current_peak_ts))

    intervals: list[float] = []
    for index in range(1, len(peak_times)):
        seconds = _time_diff_seconds(peak_times[index - 1], peak_times[index])
        if seconds >= min_interval_sec:
            intervals.append(seconds)
    return intervals


def _analyze_breath_rhythm(breath_rows: list[dict]) -> tuple[float, int]:
    """分析呼吸状态切换节奏，返回推荐(间隔秒, 计数)。"""
    # 收集 state 发生变化时的 elapsed_since_change
    change_intervals = []
    prev_state = None
    for row in breath_rows:
        state = row.get("state")
        elapsed = _coerce_number(row.get("elapsed_since_change"))
        if state is None or elapsed is None or elapsed <= 0:
            continue
        if prev_state is not None and state != prev_state:
            change_intervals.append(elapsed)
        prev_state = state

    if len(change_intervals) < 3:
        return 300.0, 3  # 默认 5分钟间隔，计3次

    # 去短 25% + 去极值 10%，取均值作为典型状态持续时长
    sorted_int = sorted(change_intervals)
    n = len(sorted_int)
    lt = max(int(n * 0.25), 1)
    ht = max(int(n * 0.10), 1)
    if lt + ht >= n:
        return 300.0, 3
    core = sorted_int[lt:n - ht]
    avg_interval = _safe_mean(core) or 300.0

    # 间隔限制 2分钟 ~ 1小时
    interval = max(min(int(round(avg_interval)), 3600), 120)

    # 计数：需要覆盖 3~5 个典型状态周期的证据
    count = max(min(int(round(avg_interval * 3 / max(interval, 1))), 8), 2)

    return float(interval), count


def _analyze_humidity_sustained(environment_rows: list[dict], avg_humidity: float) -> float:
    """分析湿度持续高于平均值的时间段，返回典型持续秒数。"""
    if not environment_rows:
        return 3600.0
    pairs = []
    for row in environment_rows:
        ts_str = row.get("ts", "")
        hum = _coerce_number(row.get("humidity"))
        if not ts_str or hum is None:
            continue
        pairs.append((ts_str, hum))
    if len(pairs) < 2:
        return 3600.0

    sustained_durations = []
    current_start = None
    for i, (ts_str, hum) in enumerate(pairs):
        above = hum > avg_humidity
        if above and current_start is None:
            current_start = ts_str
        elif not above and current_start is not None:
            dur = _time_diff_seconds(current_start, ts_str)
            if dur > 60:
                sustained_durations.append(dur)
            current_start = None
    if current_start is not None:
        dur = _time_diff_seconds(current_start, pairs[-1][0])
        if dur > 60:
            sustained_durations.append(dur)

    if sustained_durations:
        sustained_durations.sort()
        mid = len(sustained_durations) // 2
        return sustained_durations[mid]
    return 3600.0


def _time_diff_seconds(start_ts: str, end_ts: str) -> float:
    """计算两个时间字符串之间的秒数差。"""
    try:
        from datetime import datetime
        fmt = "%Y-%m-%d %H:%M:%S"
        t1 = datetime.strptime(start_ts[:19], fmt)
        t2 = datetime.strptime(end_ts[:19], fmt)
        return abs((t2 - t1).total_seconds())
    except Exception:
        return 3600.0


def build_parameter_recommendations(
    *,
    config: dict[str, Any],
    history: dict[str, Any],
    strategy: str = "balanced",
    schema: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    environment_rows = history.get("environment_rows", []) or []
    breath_rows = history.get("breath_rows", []) or []
    run_rows = history.get("run_rows", []) or []
    recommendations: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    strategy_margin = {"conservative": 1.2, "balanced": 1.0, "aggressive": 0.85}.get(strategy, 1.0)

    def add(
        path: str,
        current_value: Any,
        recommended_value: Any,
        confidence: str,
        reason: str,
        risk_note: str,
        *,
        category: str,
        can_apply: bool = True,
    ) -> None:
        if path in seen_paths:
            return
        recommendations.append(
            {
                "parameter_path": path,
                "current_value": current_value,
                "recommended_value": recommended_value,
                "confidence": confidence,
                "strategy": strategy,
                "reason": reason,
                "risk_note": risk_note,
                "category": category,
                "can_apply": can_apply,
            }
        )
        seen_paths.add(path)

    # ── 当前时间推荐：电脑系统时间 + 30s ──
    now_ts = int(time.time())
    add(
        "curDateTime",
        config.get("curDateTime"),
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts + 30)),
        "medium",
        "当前时间详细计算过程：\n"
        "1. 读取当前电脑系统时间。\n"
        "2. 在这个时间基础上加 30 秒，避免点击“生成推荐值”到真正写入设备之间出现少量延迟。\n"
        "3. 按 YYYY-MM-DD HH:MM:SS 格式写成设备配置时间。",
        "这个值完全依赖当前电脑时钟。若电脑时间本身不准，写入后的设备时间也会跟着不准，所以正式下发前应先确认电脑系统时间。",
        category="system",
    )

    # ── 温度：固定阈值 + 最近0偏移 ──
    temp_values = [_coerce_number(row.get("temperature")) for row in environment_rows]
    temp_nums = [item for item in temp_values if item is not None]
    if len(temp_nums) >= 3:
        add(
            "Temperature.HThreshold",
            config.get("Temperature", {}).get("HThreshold"),
            0,
            "high",
            "温度高阈值说明：\n"
            "1. 当前这套推荐规则把温度高阈值固定设为 0。\n"
            "2. 它不是从历史温度波动里拟合出来的，而是作为一条统一基准线使用。\n"
            "3. 这样做的目的是让后续温度偏移校准和阈值判断都围绕同一基准展开。",
            "如果现场希望更保守，尤其是温度上升过快时希望更早触发保护，可以在这个基准上人工继续上调。",
            category="threshold",
        )
        add(
            "Temperature.LThreshold",
            config.get("Temperature", {}).get("LThreshold"),
            -5,
            "high",
            "温度低阈值说明：\n"
            "1. 当前这套推荐规则把温度低阈值固定设为 -5。\n"
            "2. 它和高阈值 0 一起形成基础温度保护区间。\n"
            "3. 这个区间主要用于给系统提供统一的起始保护边界。",
            "若设备所处环境本身偏冷，或者希望更早识别低温风险，可以结合现场工况再继续调整。",
            category="threshold",
        )
        t_offset = _closest_to_zero(temp_nums)
        if t_offset is not None:
            add(
                "Temperature.offset",
                config.get("Temperature", {}).get("offset"),
                t_offset,
                "high",
                "温度偏移详细计算过程：\n"
                "1. 先收集全部历史温度采样值。\n"
                "2. 找到其中绝对值最小、也就是最接近 0 的那个点。\n"
                f"3. 把这个点对应的数值 {t_offset} 作为推荐偏移量，使该点校准后尽量落到 0 附近。\n"
                "4. 这个偏移量本质上是在做整条曲线的整体平移校准。",
                "偏移量适合处理整体零点漂移，但不能修正斜率误差。建议写入后再回看曲线，确认整体读数是否都更合理。",
                category="calibration",
            )

    # ── 湿度：均值×2 阈值 + 最近0偏移 + 热证据 ──
    humidity_values = [_coerce_number(row.get("humidity")) for row in environment_rows]
    humidity_nums = [item for item in humidity_values if item is not None]
    if len(humidity_nums) >= 3:
        avg_humidity = _safe_mean(humidity_nums) or 0
        h_high = max(_round(avg_humidity * 2, 0), 1)
        h_low = max(_round(h_high - 3, 0), 0)
        add(
            "HumidityValue.HThreshold",
            config.get("HumidityValue", {}).get("HThreshold"),
            h_high,
            "high",
            "湿度高阈值详细计算过程：\n"
            "1. 先统计当前历史数据里的全部湿度值。\n"
            f"2. 求这些湿度值的平均值，作为现场的常态湿度水平。\n"
            f"3. 再把平均值乘以 2，得到推荐高阈值 {h_high}。\n"
            "4. 这样做的目的是让高阈值明显高于常态区间，避免普通波动就触发。",
            "如果现场湿度本身波动很大，或者你希望更灵敏/更保守，都可以在这个推荐值基础上再微调。",
            category="threshold",
        )
        add(
            "HumidityValue.LThreshold",
            config.get("HumidityValue", {}).get("LThreshold"),
            h_low,
            "high",
            "湿度低阈值详细计算过程：\n"
            f"1. 先得到湿度高阈值 {h_high}。\n"
            f"2. 再用高阈值减 3，得到低阈值 {h_low}。\n"
            "3. 这样能形成一个简单、固定宽度的湿度判定区间。",
            "这个低阈值更多是基础保护边界。若现场对偏干、偏湿的容忍范围不同，可按实际要求再改。",
            category="threshold",
        )
        h_offset = _closest_to_zero(humidity_nums)
        if h_offset is not None:
            add(
                "HumidityValue.offset",
                config.get("HumidityValue", {}).get("offset"),
                h_offset,
                "high",
                "湿度偏移详细计算过程：\n"
                "1. 收集全部湿度采样值。\n"
                "2. 找到其中最接近 0 的那个值。\n"
                f"3. 把这个值 {h_offset} 作为推荐偏移量，让该点校准后尽量回到 0 附近。\n"
                "4. 这个偏移量用于修正整体零点漂移。",
                "它只解决整体平移问题，不解决比例误差。写入后建议再对照现场实际湿度复核一次。",
                category="calibration",
            )
        # 热证据
        sustained_seconds = _analyze_humidity_sustained(environment_rows, avg_humidity)
        evidence_interval = max(min(int(sustained_seconds * 2), 7200), 1800)
        evidence_count = max(min(int(sustained_seconds / max(evidence_interval, 1)) + 1, 8), 2)
        add(
            "HumidityValue.HeatEvidenceIntervalSec",
            config.get("HumidityValue", {}).get("HeatEvidenceIntervalSec"),
            evidence_interval,
            "high",
            "湿度热证据间隔详细计算过程：\n"
            "1. 先找出湿度持续高于平均湿度的连续时段。\n"
            f"2. 从这些连续时段里提取典型持续时间，再换算成推荐证据间隔 {evidence_interval} 秒。\n"
            "3. 这个间隔的作用是过滤短时湿度波动，避免偶发尖峰直接当成稳定热证据。",
            "间隔越大，抗干扰越强，但响应会变慢；间隔越小，响应更快，但更容易被短时波动触发。",
            category="timing",
        )
        add(
            "HumidityValue.HeatEvidenceCount",
            config.get("HumidityValue", {}).get("HeatEvidenceCount"),
            evidence_count,
            "high",
            "湿度热证据计数详细说明：\n"
            f"1. 当前推荐值 = {evidence_count}。\n"
            "2. 它表示要连续满足多少次热证据条件，系统才真正确认“湿度长期偏高”。\n"
            "3. 这个计数和热证据间隔一起决定系统对短时尖峰的容忍度。",
            "计数越大越稳，但确认更慢；计数越小越敏感，但更容易受短时尖峰影响。",
            category="timing",
        )

    # ── 压力：固定 +5 / −5 阈值 + 最近0偏移 ──
    pressure_values = [_coerce_number(row.get("pressure")) for row in environment_rows]
    pressure_nums = [item for item in pressure_values if item is not None]
    if len(pressure_nums) >= 3:
        add(
            "PressureValue.HThreshold",
            config.get("PressureValue", {}).get("HThreshold"),
            5,
            "high",
            "压力高阈值说明：\n"
            "1. 当前规则将压力高阈值固定为 +5。\n"
            "2. 这是一个统一的起始保护边界，不是根据本批历史压力波动自动拟合出来的。\n"
            "3. 主要目的是先给系统提供稳定一致的默认上界。",
            "若现场压力本底较高或对高压更敏感，可在此基础上再调整。",
            category="threshold",
        )
        add(
            "PressureValue.LThreshold",
            config.get("PressureValue", {}).get("LThreshold"),
            -5,
            "high",
            "压力低阈值说明：\n"
            "1. 当前规则将压力低阈值固定为 -5。\n"
            "2. 它与高阈值 +5 组成基础压力保护区间。\n"
            "3. 这个区间用于提供统一的默认判定边界。",
            "若现场低压风险更敏感，或设备本身运行区间不同，应按实际工况继续修正。",
            category="threshold",
        )
        p_offset = _closest_to_zero(pressure_nums)
        if p_offset is not None:
            add(
                "PressureValue.offset",
                config.get("PressureValue", {}).get("offset"),
                p_offset,
                "high",
                "压力偏移详细计算过程：\n"
                "1. 收集全部历史压力采样值。\n"
                "2. 找到其中最接近 0 的那个压力值。\n"
                f"3. 把该值 {p_offset} 作为推荐偏移量，用来整体平移压力曲线。\n"
                "4. 目标是让零点附近的测量更贴近真实值。",
                "这类偏移适合修正零漂，不适合修正量程误差。写入后建议再核对几组实际压力点。",
                category="calibration",
            )

    flow_values = [_coerce_number(row.get("flow_rate")) for row in breath_rows]
    abs_flows = [abs(v) for v in flow_values if v is not None]
    positive_flows = [v for v in flow_values if v is not None and v > 0]
    negative_flows = [abs(v) for v in flow_values if v is not None and v < 0]
    recommended_derange_ht: float | None = None
    recommended_derange_lt: float | None = None
    noise_pos_peaks, noise_neg_peaks, noise_cluster_count = _collect_rapid_switch_noise_peaks(
        breath_rows,
        switch_window_sec=3.0,
        min_runs_per_cluster=3,
    )
    if noise_pos_peaks:
        core_noise_pos = _trim_extremes(noise_pos_peaks, ratio=0.10)
        pos_noise_envelope = _percentile(core_noise_pos, 0.90)
        if pos_noise_envelope is not None:
            derange_ht_value = max(round(float(pos_noise_envelope) * 1.10, 2), 3.0)
            add(
                "RespiratoryRate.DERangeHT",
                config.get("RespiratoryRate", {}).get("DERangeHT"),
                derange_ht_value,
                "high",
                "有效吸气分区阈值公式：先找 3 秒内频繁正负切换方向的短时噪声簇，"
                "提取其中正向短段的峰值；去掉最小 10% 和最大 10% 的极端事件后，"
                f"取剩余正向噪声峰值的 90 分位，再加 10% 裕量，并设置下限不小于 3，得到 {derange_ht_value}。",
                f"本次识别到 {noise_cluster_count} 个快速切换噪声簇，正向噪声峰值样本 {len(noise_pos_peaks)} 个。",
                category="detection",
            )
            recommended_derange_ht = derange_ht_value
    elif config.get("RespiratoryRate", {}).get("DERangeHT") is not None:
        add(
            "RespiratoryRate.DERangeHT",
            config.get("RespiratoryRate", {}).get("DERangeHT"),
            config.get("RespiratoryRate", {}).get("DERangeHT"),
            "low",
            "有效吸气分区阈值公式：应基于几秒内频繁正负切换方向的噪声簇，"
            "提取正向噪声峰值，去除极端事件后再取噪声包络并加裕量。"
            "当前数据不足，未形成可用的新推荐值，因此这里显示的是当前配置值，不是本次计算所得。",
            "建议补充更多包含短时正负切换噪声的呼吸数据后重新生成推荐值。",
            category="detection",
            can_apply=False,
        )

    if noise_neg_peaks:
        core_noise_neg = _trim_extremes(noise_neg_peaks, ratio=0.10)
        neg_noise_envelope = _percentile(core_noise_neg, 0.90)
        if neg_noise_envelope is not None:
            derange_lt_value = -max(round(float(neg_noise_envelope) * 1.10, 2), 3.0)
            add(
                "RespiratoryRate.DERangeLT",
                config.get("RespiratoryRate", {}).get("DERangeLT"),
                derange_lt_value,
                "high",
                "有效出气分区阈值公式：先找 3 秒内频繁正负切换方向的短时噪声簇，"
                "提取其中负向短段的峰值幅值；去掉最小 10% 和最大 10% 的极端事件后，"
                f"取剩余负向噪声峰值幅值的 90 分位，再加 10% 裕量，并设置下限不小于 -3，得到 {derange_lt_value}。",
                f"本次识别到 {noise_cluster_count} 个快速切换噪声簇，负向噪声峰值样本 {len(noise_neg_peaks)} 个。",
                category="detection",
            )
            recommended_derange_lt = derange_lt_value
    elif config.get("RespiratoryRate", {}).get("DERangeLT") is not None:
        add(
            "RespiratoryRate.DERangeLT",
            config.get("RespiratoryRate", {}).get("DERangeLT"),
            config.get("RespiratoryRate", {}).get("DERangeLT"),
            "low",
            "有效出气分区阈值公式：应基于几秒内频繁正负切换方向的噪声簇，"
            "提取负向噪声峰值幅值，去除极端事件后再取噪声包络并加裕量。"
            "当前数据不足，未形成可用的新推荐值，因此这里显示的是当前配置值，不是本次计算所得。",
            "建议补充更多包含短时正负切换噪声的呼吸数据后重新生成推荐值。",
            category="detection",
            can_apply=False,
        )

    respiratory_cfg = config.get("RespiratoryRate", {})
    derange_ht = recommended_derange_ht if recommended_derange_ht is not None else _coerce_number(respiratory_cfg.get("DERangeHT"))
    derange_lt = recommended_derange_lt if recommended_derange_lt is not None else _coerce_number(respiratory_cfg.get("DERangeLT"))

    if respiratory_cfg.get("HeatOnThreshold") is not None or "HeatOnThreshold" in respiratory_cfg:
        add(
            "RespiratoryRate.HeatOnThreshold",
            respiratory_cfg.get("HeatOnThreshold"),
            -4,
            "high",
            "HeatOnThreshold uses the fixed recommended value -4.",
            "This value no longer comes from the old high-flow alarm formula.",
            category="threshold",
        )

    if respiratory_cfg.get("HeatOffThreshold") is not None or "HeatOffThreshold" in respiratory_cfg:
        add(
            "RespiratoryRate.HeatOffThreshold",
            respiratory_cfg.get("HeatOffThreshold"),
            -1,
            "high",
            "HeatOffThreshold uses the fixed recommended value -1.",
            "This value no longer comes from the old low-flow alarm formula.",
            category="threshold",
        )

    no_change_gaps = _collect_no_change_gaps(
        breath_rows,
        derange_ht=derange_ht,
        derange_lt=derange_lt,
    )
    if no_change_gaps:
        longest_gap = max(no_change_gaps)
        no_change_sec = max(int(round(longest_gap * 2.0)), 10)
        add(
            "RespiratoryRate.NoChangeAlarmTimeSec",
            respiratory_cfg.get("NoChangeAlarmTimeSec"),
            no_change_sec,
            "high",
            "无变化告警时间公式：不区分呼吸正向还是负向，只要气流越过有效分区阈值 "
            "(flow_rate < DERangeLT 或 flow_rate > DERangeHT) 就记为一次有效气流通过。"
            f"统计相邻两次有效气流通过之间的无变化时长，取其中最长值 {int(round(longest_gap))} 秒，再乘以 2，得到 {no_change_sec} 秒。",
            f"本次共识别到 {len(no_change_gaps)} 个无变化间隔；该值用于检查较长时间是否没有有效气流通过。",
            category="timing",
        )
    elif respiratory_cfg.get("NoChangeAlarmTimeSec") is not None:
        add(
            "RespiratoryRate.NoChangeAlarmTimeSec",
            respiratory_cfg.get("NoChangeAlarmTimeSec"),
            respiratory_cfg.get("NoChangeAlarmTimeSec"),
            "low",
            "无变化告警时间公式：不区分呼吸正向还是负向，只要气流越过有效分区阈值 "
            "(flow_rate < DERangeLT 或 flow_rate > DERangeHT) 就记为一次有效气流通过，"
            "再统计相邻有效气流通过之间的最长无变化时长并乘以 2。"
            "当前数据不足，未形成可用的新推荐值，因此这里显示的是当前配置值，不是本次计算所得。",
            "建议补充更多包含有效气流通过的呼吸数据后重新生成推荐值。",
            category="timing",
            can_apply=False,
        )

    elapsed_values = [_coerce_number(row.get("elapsed_since_change")) for row in breath_rows]
    elapsed_numbers = [e for e in elapsed_values if e is not None and e > 0]
    if elapsed_numbers:
        # 无变化告警时间：去短间隔 → 去极值 → 取长区间均值 ×2
        elapsed_sorted = sorted(elapsed_numbers)
        n_elap = len(elapsed_sorted)
        lt_trim_e = max(int(n_elap * 0.25), 1)   # 去掉正常的短间隔（呼吸切换频繁）
        ht_trim_e = max(int(n_elap * 0.10), 1)   # 去掉顶部极值
        if lt_trim_e + ht_trim_e < n_elap:
            core_elapsed = elapsed_sorted[lt_trim_e:n_elap - ht_trim_e]
            avg_long = _safe_mean(core_elapsed)
            if avg_long is not None:
                no_change_sec = max(int(round(avg_long * 2)), 60)
                add(
                    "RespiratoryRate.NoChangeAlarmTimeSec",
                    config.get("RespiratoryRate", {}).get("NoChangeAlarmTimeSec"),
                    no_change_sec,
                    "high",
                    f"无变化告警时间：排除短间隔和极值后，取较长无变化区间的均值 × 2 = {no_change_sec} 秒。",
                    "如果现场需要更灵敏的告警，可适当减小此值。",
                    category="timing",
                )
        effective_segment_durations = _collect_effective_breath_segment_durations(
            breath_rows,
            derange_ht=derange_ht,
            derange_lt=derange_lt,
        )
        evidence_interval = 10.0
        evidence_count = 3
        if effective_segment_durations:
            core_segment_durations = _trim_extremes(effective_segment_durations, ratio=0.10)
            avg_effective_duration = _safe_mean(core_segment_durations)
            if avg_effective_duration is not None:
                evidence_interval = float(max(int(round(avg_effective_duration / 2.0)), 10))
                evidence_count = max(min(int(round(avg_effective_duration * 3 / max(evidence_interval, 1))), 8), 2)
                add(
                    "RespiratoryRate.HeatEvidenceIntervalSec",
                    respiratory_cfg.get("HeatEvidenceIntervalSec"),
                    evidence_interval,
                    "high",
                    "呼吸热证据间隔详细计算过程：\n"
                    f"1. 先用当前阈值判断有效呼吸段：flow_rate < DERangeLT ({derange_lt}) 记为有效出气段，"
                    f"flow_rate > DERangeHT ({derange_ht}) 记为有效进气段。\n"
                    "2. 把相邻、方向一致且连续满足阈值条件的采样点合并成一个连续有效段。\n"
                    "3. 计算每个连续有效段的持续时间，得到一组持续时间样本。\n"
                    "4. 按持续时间从小到大排序后，去掉最小 10% 和最大 10% 的极端值，减少噪声和异常长段影响。\n"
                    "5. 对剩余样本求平均持续时间，再除以 2，表示需要半个稳定呼吸段长度就开始积累热证据。\n"
                    f"6. 最后与最小限制 10 秒比较，取较大值，得到推荐值 {int(evidence_interval)} 秒。\n"
                    f"本次共提取有效连续段 {len(effective_segment_durations)} 个，去极值后参与平均的样本 {len(core_segment_durations)} 个。",
                    "这个值偏小会让短时扰动更容易被当成有效热证据，偏大又会让热证据建立过慢。"
                    "如果现场噪声很多，可结合曲线把这个值再适当调大；如果希望更灵敏，可在确认无噪声误判后再调小。",
                    category="timing",
                )
        else:
            evidence_interval, evidence_count = _analyze_breath_rhythm(breath_rows)

        if "RespiratoryRate.HeatEvidenceIntervalSec" not in seen_paths:
            evidence_interval = float(max(int(round(evidence_interval)), 10))
        add(
            "RespiratoryRate.HeatEvidenceIntervalSec",
            respiratory_cfg.get("HeatEvidenceIntervalSec"),
            evidence_interval,
            "high",
            "呼吸热证据间隔推荐值说明：\n"
            f"1. 当前推荐值 = {int(evidence_interval)} 秒。\n"
            "2. 它表示呼吸方向稳定持续多长时间后，才开始把这一段记为可用于热证据判断的有效阶段。\n"
            "3. 当前算法优先基于连续有效进/出气段的持续时间统计来计算；如果样本不足，则退回到呼吸节奏兜底算法。\n"
            "4. 这个值越小，系统越灵敏；这个值越大，系统越保守。",
            "如果现场存在很多短时正负切换、抖动、毛刺或气流噪声，建议结合曲线确认是否需要继续上调。"
            "如果曲线已经很平稳且你希望更快响应，再考虑适当减小。",
            category="timing",
        )
        double_switch = max(int(round(float(evidence_interval) / 2.0)), 1)
        add(
            "DoubleSwitch",
            config.get("DoubleSwitch"),
            double_switch,
            "high",
            "DoubleSwitch 详细计算过程：\n"
            f"1. 先取得当前推荐的呼吸热证据间隔 = {int(evidence_interval)} 秒。\n"
            "2. DoubleSwitch 取这个间隔的一半，表示切换保护时间不需要完整等到一个热证据间隔结束，"
            "而是在半个证据间隔后就可以开始允许切换。\n"
            f"3. 因此公式为 DoubleSwitch = round(HeatEvidenceIntervalSec / 2) = round({int(evidence_interval)} / 2) = {double_switch} 秒。",
            "如果现场希望切换更保守，可以在此基础上适当增大；"
            "如果希望更快切换，前提是确认不会因为短时波动造成误切换，再考虑减小。",
            category="timing",
        )
        effective_directions = _collect_effective_breath_segment_directions(
            breath_rows,
            derange_ht=derange_ht,
            derange_lt=derange_lt,
            min_duration_sec=float(max(int(evidence_interval), 1)),
        )
        run_lengths = _collect_same_direction_run_lengths(effective_directions)
        exhale_count, exhale_meta = _recommend_evidence_count_from_runs(run_lengths.get("exhale", []))
        inhale_count, inhale_meta = _recommend_evidence_count_from_runs(run_lengths.get("inhale", []))
        directional_counts = [value for value in (exhale_count, inhale_count) if value is not None]
        if directional_counts:
            evidence_count = max(min(max(directional_counts), 6), 2)
            exhale_stability = exhale_meta.get("selected_stability")
            inhale_stability = inhale_meta.get("selected_stability")
            add(
                "RespiratoryRate.HeatEvidenceCount",
                respiratory_cfg.get("HeatEvidenceCount"),
                evidence_count,
                "high",
                "呼吸热证据计数详细计算过程：\n"
                f"1. 先只保留持续时间不小于呼吸热证据间隔 {int(evidence_interval)} 秒的连续有效出气段和连续有效进气段。\n"
                "2. 把这些有效段按时间顺序转成方向序列，例如连续几段都是出气，就认为出气稳定在持续。\n"
                "3. 统计同一方向连续出现的长度，也就是“稳定连续了几段”。\n"
                "4. 对每个候选计数 k，计算稳定率 = 连续长度 >= k+1 的段数 / 连续长度 >= k 的段数。\n"
                "5. 找到稳定率第一次达到 85% 的最小 k；如果进气和出气两边结果不同，取更大的那个。\n"
                f"6. 因此本次推荐值 = {evidence_count}。\n"
                "当前统计："
                f" 出气连续段 {exhale_meta.get('run_count', 0)} 个"
                + (f"，推荐 {exhale_count}，稳定率 {round(float(exhale_stability) * 100, 1)}%" if exhale_count is not None and exhale_stability is not None else "，样本不足")
                + f"；进气连续段 {inhale_meta.get('run_count', 0)} 个"
                + (f"，推荐 {inhale_count}，稳定率 {round(float(inhale_stability) * 100, 1)}%" if inhale_count is not None and inhale_stability is not None else "，样本不足")
                + "。",
                "这个计数越大，系统越不容易被短时不稳定段误触发，但响应会变慢；计数越小，响应更快，但更敏感。",
                category="timing",
            )
        else:
            add(
                "RespiratoryRate.HeatEvidenceCount",
                respiratory_cfg.get("HeatEvidenceCount"),
                respiratory_cfg.get("HeatEvidenceCount"),
                "low",
                "呼吸热证据计数公式：先提取持续时间不小于呼吸热证据间隔的连续有效出气段 "
                "(flow_rate < DERangeLT) 和连续有效进气段 (flow_rate > DERangeHT)，"
                "再统计同向连续段长度，并用稳定率 = 连续长度 >= k+1 / 连续长度 >= k 选择最小稳定计数。"
                "当前有效连续段样本不足，未形成可用的新推荐值，因此这里显示的是当前配置值，不是本次计算所得。",
                "建议补充更多稳定的进气/出气连续段后重新生成推荐值。",
                category="timing",
                can_apply=False,
            )

        # 呼气超时：相邻有效出气负峰值之间的峰峰值间距，去除极小/极大值后均值 × 1.5
        heat_evidence_interval = max(int(evidence_interval), 1)
        exhale_peak_intervals = _collect_exhale_peak_intervals(
            breath_rows,
            derange_lt=derange_lt,
            min_interval_sec=float(heat_evidence_interval),
        )
        if exhale_peak_intervals:
            core_peak_intervals = _trim_extremes(exhale_peak_intervals, ratio=0.10)
            avg_peak_interval = _safe_mean(core_peak_intervals)
            if avg_peak_interval is not None:
                exh_timeout = max(int(round(avg_peak_interval * 1.5)), heat_evidence_interval, 10)
                add(
                    "RespiratoryRate.ExhaleTimeoutSec",
                    respiratory_cfg.get("ExhaleTimeoutSec"),
                    exh_timeout,
                    "high",
                    "呼气超时详细计算过程：\n"
                    f"1. 只统计 flow_rate < DERangeLT ({derange_lt}) 的连续有效出气段。\n"
                    "2. 每个有效出气段只取流速最小的那个点，作为这一段的负峰值。\n"
                    "3. 计算相邻两个负峰值之间的时间间距，得到一组峰峰值间距样本。\n"
                    f"4. 先剔除小于呼吸热证据间隔 {heat_evidence_interval} 秒的间距，避免把太短的噪声波动算进去。\n"
                    "5. 对剩余间距按从小到大排序，再去掉最小 10% 和最大 10% 的极端值。\n"
                    f"6. 对剩余样本取平均值，再乘以 1.5，得到推荐呼气超时 {exh_timeout} 秒。\n"
                    f"本次有效峰峰值样本 {len(exhale_peak_intervals)} 个，去极值后参与平均 {len(core_peak_intervals)} 个。",
                    "这个值偏小会让系统更快判断“呼气超时”，偏大则更保守。现场如果希望更保守，可在此基础上再适当增大。",
                    category="timing",
                )
                exh_timeout_min = min(max(int(round(exh_timeout * 0.375)), 1), exh_timeout, 3600)
                add(
                    "RespiratoryRate.ExhaleTimeoutMinSec",
                    respiratory_cfg.get("ExhaleTimeoutMinSec"),
                    exh_timeout_min,
                    "high",
                    "呼气超时下限推荐：基于本次推荐的 ExhaleTimeoutSec 按 37.5% 折算，"
                    f"并限制在 1 到 3600 秒之间，本次推荐为 {exh_timeout_min} 秒。",
                    "该值越小，动态超时越容易跟随短周期变化；越大则越保守。建议保持不大于 ExhaleTimeoutSec。",
                    category="timing",
                )
        elif respiratory_cfg.get("ExhaleTimeoutSec") is not None:
            add(
                "RespiratoryRate.ExhaleTimeoutSec",
                respiratory_cfg.get("ExhaleTimeoutSec"),
                respiratory_cfg.get("ExhaleTimeoutSec"),
                "low",
                "呼气超时公式：仅统计 flow_rate < DERangeLT 的连续有效出气段，"
                "每段取最小流速点作为负峰值；计算相邻负峰值的峰峰值间距，"
                f"先剔除小于呼吸热证据间隔 {heat_evidence_interval} 秒的间距，"
                "再按从小到大排序去掉最小 10% 和最大 10%，最后取剩余间距均值 × 1.5。"
                "当前数据不足，未形成可用的新推荐值，因此这里显示的是当前配置值，不是本次计算所得。",
                "建议补充更多有效出气段数据后重新生成推荐值。",
                category="timing",
                can_apply=False,
            )
            add(
                "RespiratoryRate.ExhaleTimeoutMinSec",
                respiratory_cfg.get("ExhaleTimeoutMinSec"),
                respiratory_cfg.get("ExhaleTimeoutMinSec"),
                "low",
                "呼气超时下限推荐：当前数据不足以形成新的动态下限，暂时保留当前配置值。",
                "该值需要与 ExhaleTimeoutSec 配套确认，必须保持不大于非零的 ExhaleTimeoutSec。",
                category="timing",
                can_apply=False,
            )

    if run_rows:
        error_count = sum(1 for row in run_rows if str(row.get("level")) == "E")
        interval = 120 if error_count else 60
        for index, task in enumerate(config.get("TaskArray", []) or []):
            add(
                f"TaskArray[{index}].delay",
                task.get("delay"),
                interval,
                "low",
                "任务 delay 推荐说明：\n"
                "1. 这里不是从控制逻辑反推出来的精确最优值，而是根据运行日志中是否出现错误级别事件，给出一个排障起点。\n"
                f"2. 如果日志里出现错误，推荐值倾向于更保守；本次推荐为 {interval}。\n"
                "3. 这个参数更适合拿来做初始试运行，不适合作为最终业务策略直接固化。",
                "任务类参数和现场业务流程、执行器动作节奏关系很强，默认不建议客户直接批量套用，最好结合真实工艺节拍单独确认。",
                category="task",
            )

    fallback_paths = _collect_fallback_paths(config, schema)
    for path, current_value, label in fallback_paths:
        if not path or path in seen_paths:
            continue
        add(
            path,
            current_value,
            current_value,
            "low",
            f"{label} 当前说明：\n"
            "1. 这项参数在当前数据里缺少足够稳定的历史特征，暂时无法可靠地推导出新值。\n"
            "2. 因此系统先把当前配置值原样作为参考展示。\n"
            "3. 这里显示的不是本次计算得出的新推荐，而是“暂时保持原值”。",
            "凡是低可信推荐，都不建议直接覆盖现场参数。更稳妥的做法是补充更多数据后重新生成，再由人工确认。",
            category="fallback",
            can_apply=False,
        )

    return recommendations


def build_parameter_recommendation_payload(
    *,
    config: dict[str, Any],
    history: dict[str, Any],
    strategy: str = "balanced",
    schema: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    recommendations = build_parameter_recommendations(
        config=config,
        history=history,
        strategy=strategy,
        schema=schema,
    )
    grouped = {"high": [], "medium": [], "low": []}
    for item in recommendations:
        grouped.setdefault(item["confidence"], []).append(item)
    summary = {
        "total_count": len(recommendations),
        "high_confidence_count": len(grouped["high"]),
        "medium_confidence_count": len(grouped["medium"]),
        "low_confidence_count": len(grouped["low"]),
        "strategy": strategy,
        "history_summary": {
            "environment_row_count": len(history.get("environment_rows", []) or []),
            "breath_row_count": len(history.get("breath_rows", []) or []),
            "run_row_count": len(history.get("run_rows", []) or []),
        },
    }
    return {
        "recommendations": recommendations,
        "grouped": grouped,
        "summary": summary,
    }
