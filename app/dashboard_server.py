from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from copy import deepcopy

from live_device_store import (
    create_live_device,
    delete_live_device,
    export_live_devices_json,
    import_live_devices_payload,
    load_live_devices,
    select_live_device,
    update_live_device,
)
from live_polling_commands import build_default_polling_commands
from live_register_catalog import get_register_catalog, get_register_catalog_summary
from parameter_recommendation import build_parameter_recommendation_payload
from simulation_engine import params_from_config, run_simulation


def _get_live_service():
    from live_acquisition_service import get_live_acquisition_service
    return get_live_acquisition_service()

APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
DATA_DIR = BASE_DIR / "实时数据"
WEB_DIR = APP_DIR / "web"
LIVE_DEVICES_PATH = BASE_DIR / "live_devices.json"
HOST = "127.0.0.1"
PORT = 8765

ENV_ROW_RE = re.compile(
    r"\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\],/\*\s*"
    r"(?P<pressure>[-\d.]+),(?P<temperature>[-\d.]+),(?P<flow>[-\d.]+),(?P<humidity>[-\d.]+),?\s*\*/"
)
RUN_ROW_RE = re.compile(
    r"^(?P<level>[IWE])/YLDQ\s+\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(?P<message>.*)$"
)

STATE_LABELS = {
    -1: "NONE",
    0: "EXHALING",
    1: "INHALING",
    2: "NOT_BREATHING",
    3: "ALARM_LOW",
    4: "ALARM_HIGH",
}
STATE_NAMES_ZH = {
    -1: "未定义",
    0: "呼气",
    1: "吸气",
    2: "无呼吸",
    3: "低流速告警",
    4: "高流速告警",
}
RHYTHM_NAMES_ZH = {
    0: "普通采样",
    1: "状态切换点",
    2: "段开始",
    3: "段结束",
}
METRIC_META = {
    "pressure": {"label": "压力", "unit": "kPa", "section": "PressureValue", "high": "HThreshold", "low": "LThreshold"},
    "temperature": {"label": "温度", "unit": "°C", "section": "Temperature", "high": "HThreshold", "low": "LThreshold"},
    "flow": {"label": "????", "unit": "L/min", "section": "RespiratoryRate", "high": "HeatOffThreshold", "low": "HeatOnThreshold"},
    "humidity": {"label": "湿度", "unit": "%", "section": "HumidityValue", "high": "HThreshold", "low": "LThreshold"},
}
RUN_KEYWORDS = {
    "watchdog": ["watchdog"],
    "flow": ["[Flow]", "GetFlow", "flow"],
    "i2c": ["I2C", "bus recovery"],
    "lora": ["LoRa"],
    "iec61850": ["IEC61850"],
    "alarm": ["ALARM", "ERR OUT", "ONLINE ERR"],
    "heat_control": [
        "open",
        "close",
        "HEAT",
        "HeatChannel",
        "HTC1",
        "HTC2",
        "VALVE",
        "ANTIFREEZE",
        "ONLINEopen",
        "ONLINEclose",
        "ForceCloseTask",
        "ExhaleTimeout",
        "(Humidity)",
    ],
    "config": ["SD card config updated", "Config synced to Flash", "Config saved"],
}

_CACHE: dict[str, Any] = {"key": None, "analysis": None}
LIVE_SESSION_STATE: dict[str, Any] = {
    "running": False,
    "selected_device_id": None,
    "started_at": None,
    "last_error": None,
    "session_dir": None,
    "sample_counts": {
        "environment": 0,
        "breath": 0,
        "run": 0,
    },
}


def _find_live_device(devices_payload: dict[str, Any], device_id: Any) -> dict[str, Any] | None:
    if device_id in (None, ""):
        return None
    device_id = str(device_id)
    return next((item for item in devices_payload.get("devices", []) if item.get("id") == device_id), None)


def _empty_live_sample_counts() -> dict[str, int]:
    return {
        "metrics": 0,
        "statuses": 0,
        "controls": 0,
        "parameters": 0,
        "history": 0,
    }


def _build_live_empty_session(device_id: str | None = None) -> dict[str, Any]:
    return {
        "running": False,
        "device_id": device_id,
        "started_at": None,
        "last_error": None,
        "last_success_at": None,
        "error_count": 0,
        "request_count": 0,
        "sample_counts": _empty_live_sample_counts(),
        "last_snapshot_at": None,
        "session_dir": None,
    }


def _build_live_device_context(
    devices_payload: dict[str, Any],
    service_status: dict[str, Any],
    requested_device_id: Any = None,
) -> dict[str, Any]:
    selected_device_id = str(requested_device_id or devices_payload.get("selectedDeviceId") or "") or None
    active_device_ids = service_status.get("device_ids") if isinstance(service_status.get("device_ids"), list) else []
    service_running = bool(service_status.get("running"))
    active_device_id = active_device_ids[0] if active_device_ids and service_running else None
    selected_device = _find_live_device(devices_payload, selected_device_id)
    matches_selected_device = bool(selected_device_id and service_running and selected_device_id in active_device_ids)
    return {
        "selectedDeviceId": selected_device_id,
        "activeDeviceIds": active_device_ids,
        "activeDeviceId": active_device_id,
        "selectedDevice": selected_device,
        "matchesSelectedDevice": matches_selected_device,
        "activeMatchesSelectedDevice": matches_selected_device,
    }


def _project_live_session(service_status: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if context["matchesSelectedDevice"]:
        return deepcopy(service_status)
    return _build_live_empty_session(context["selectedDeviceId"])


def _build_live_snapshot_projection(
    snapshot: dict[str, Any] | None,
    service_status: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if context["matchesSelectedDevice"] and isinstance(snapshot, dict):
        payload = deepcopy(snapshot)
        payload["device"] = context["selectedDevice"]
        payload["deviceId"] = context["selectedDeviceId"]
        payload["activeDeviceId"] = context["activeDeviceId"]
        payload["matchesSelectedDevice"] = True
        return payload
    return {
        "deviceId": context["selectedDeviceId"],
        "activeDeviceId": context["activeDeviceId"],
        "matchesSelectedDevice": False,
        "device": context["selectedDevice"],
        "snapshotAt": None,
        "ts": None,
        "metrics": [],
        "statuses": [],
        "controls": [],
        "session": _build_live_empty_session(context["selectedDeviceId"]),
    }


def _build_live_series_projection(
    series: dict[str, Any] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if context["matchesSelectedDevice"] and isinstance(series, dict):
        payload = deepcopy(series)
        payload["deviceId"] = context["selectedDeviceId"]
        payload["activeDeviceId"] = context["activeDeviceId"]
        payload["matchesSelectedDevice"] = True
        return payload
    return {
        "deviceId": context["selectedDeviceId"],
        "activeDeviceId": context["activeDeviceId"],
        "matchesSelectedDevice": False,
        "rows": [],
        "byMetric": {key: [] for key in ("temperature", "humidity", "pressure", "flow")},
    }


def _build_live_events_projection(
    events: list[dict[str, Any]] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "deviceId": context["selectedDeviceId"],
        "activeDeviceId": context["activeDeviceId"],
        "matchesSelectedDevice": context["matchesSelectedDevice"],
        "events": deepcopy(events) if context["matchesSelectedDevice"] and isinstance(events, list) else [],
    }


def _build_live_traffic_projection(
    traffic: list[dict[str, Any]] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "deviceId": context["selectedDeviceId"],
        "activeDeviceId": context["activeDeviceId"],
        "matchesSelectedDevice": context["matchesSelectedDevice"],
        "traffic": deepcopy(traffic) if isinstance(traffic, list) else [],
    }


def _build_live_parameters_projection(
    sections: dict[str, list[dict[str, Any]]] | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(sections, dict):
        payload = deepcopy(sections)
    else:
        payload = {"control": [], "config": [], "task": []}
    return {
        "deviceId": context["selectedDeviceId"],
        "activeDeviceId": context["activeDeviceId"],
        "matchesSelectedDevice": context["matchesSelectedDevice"],
        "sections": payload,
    }


def _build_live_meta_projection(
    meta: dict[str, Any] | None,
    service_status: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    if context["matchesSelectedDevice"] and isinstance(meta, dict):
        payload = deepcopy(meta)
        payload["deviceId"] = context["selectedDeviceId"]
        payload["activeDeviceId"] = context["activeDeviceId"]
        payload["matchesSelectedDevice"] = True
        return payload
    return {
        "available": False,
        "sessionDir": None,
        "lastSnapshot": None,
        "session": _build_live_empty_session(context["selectedDeviceId"]),
        "deviceId": context["selectedDeviceId"],
        "activeDeviceId": context["activeDeviceId"],
        "matchesSelectedDevice": False,
    }

CONFIG_SCHEMA: list[dict[str, Any]] = [
    {
        "key": "system",
        "title": "系统参数",
        "description": "控制设备的整体运行方式、时间同步和保护行为。",
        "fields": [
            {"path": "ver", "label": "配置版本", "type": "string", "readonly": True, "description": "配置文件版本号。主要用于和固件版本匹配，不建议在这里手工改写。"},
            {"path": "curDateTime", "label": "当前时间", "type": "string", "description": "配置文件记录的当前日期时间。通常作为设备当前时间基准。格式为 YYYY-MM-DD HH:MM:SS。"},
            {"path": "updateTime", "label": "更新时间开关", "type": "bool", "description": "是否允许设备根据配置文件更新时间。"},
            {"path": "DoubleMode", "label": "双模式", "type": "bool", "description": "决定设备按单模式还是双模式运行。双模式下 HTC1 和 HTC2 会参与轮换。"},
            {"path": "DoubleSwitch", "label": "最小保护时间", "type": "int", "unit": "秒", "min": 0, "max": 31536000, "description": "主加热回路最小保护时间。数值越大，切换越慢。"},
            {"path": "ForceClose", "label": "强制关闭保护", "type": "int", "unit": "秒", "min": 0, "max": 31536000, "description": "达到该时长后强制关闭相关输出，避免长时间持续动作。"},
            {"path": "lcdShow", "label": "LCD 显示开关", "type": "bool", "description": "控制本地 LCD 的显示使能。"},
        ],
    },
    {
        "key": "uart",
        "title": "串口与网络",
        "description": "用于本机通信地址、串口参数和联网参数配置。",
        "fields": [
            {"path": "uartInfor.addr", "label": "串口地址", "type": "int", "min": 1, "max": 247, "description": "决定本机通信地址。现场联机前应与上位机请求地址保持一致。"},
            {"path": "uartInfor.rate", "label": "波特率", "type": "select", "options": [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200], "description": "配置本机串口波特率。"},
            {"path": "uartInfor.parity", "label": "校验位", "type": "select", "options": [{"value": 0, "label": "无校验"}, {"value": 1, "label": "奇校验"}, {"value": 2, "label": "偶校验"}], "description": "配置串口校验方式。"},
            {"path": "netInfor.Wireless", "label": "无线模式", "type": "bool", "description": "网络通信是否按无线模式处理。"},
            {"path": "netInfor.IP", "label": "服务器地址", "type": "string", "description": "目标服务器 IP 或域名。"},
            {"path": "netInfor.PORT", "label": "服务器端口", "type": "int", "min": 1, "max": 65535, "description": "目标服务器端口号。"},
            {"path": "netInfor.SN", "label": "设备 SN", "type": "string", "description": "设备序列号，用于平台识别。"},
            {"path": "netInfor.CommPwd", "label": "通信口令", "type": "string", "description": "设备通信认证口令。"},
        ],
    },
    {
        "key": "humidity",
        "title": "湿度参数",
        "description": "控制湿度判定阈值、偏移和湿度热证据规则。",
        "fields": [
            {"path": "HumidityValue.HThreshold", "label": "湿度高阈值", "type": "int", "description": "湿度高告警或高判据阈值。"},
            {"path": "HumidityValue.LThreshold", "label": "湿度低阈值", "type": "int", "description": "湿度低判据阈值。"},
            {"path": "HumidityValue.offset", "label": "湿度偏移", "type": "float", "step": 0.1, "description": "对湿度测量值做整体偏移补偿。"},
            {"path": "HumidityValue.HeatEvidenceIntervalSec", "label": "湿度热证据间隔", "type": "int", "unit": "秒", "min": 1, "max": 86400, "description": "湿度热证据采样间隔。代码中解析时会限制在 1 到 86400 秒之间。"},
            {"path": "HumidityValue.HeatEvidenceCount", "label": "湿度热证据计数", "type": "int", "min": 1, "max": 10, "description": "湿度热证据累计次数门槛。代码中解析时会限制在 1 到 10 之间。"},
            {"path": "HumidityValue.VSW", "label": "湿度优先/使能", "type": "bool", "description": "该位在代码中映射到 Priority 布尔值，用于湿度通道的优先/使能标志。"},
        ],
    },
    {
        "key": "temperature",
        "title": "温度参数",
        "description": "控制防冻相关阈值、偏移和延时退出。",
        "fields": [
            {"path": "Temperature.HThreshold", "label": "温度高阈值", "type": "int", "description": "温度高阈值。"},
            {"path": "Temperature.LThreshold", "label": "温度低阈值", "type": "int", "description": "温度低阈值，常用于防冻判据。"},
            {"path": "Temperature.offset", "label": "温度偏移", "type": "float", "step": 0.1, "description": "对温度测量值做整体偏移补偿。"},
            {"path": "Temperature.delay", "label": "防冻延时", "type": "int", "unit": "秒", "min": 0, "max": 31536000, "description": "决定防冻相关辅助输出保持时间。"},
        ],
    },
    {
        "key": "pressure",
        "title": "压力参数",
        "description": "控制压力判定阈值与偏移。",
        "fields": [
            {"path": "PressureValue.HThreshold", "label": "压力高阈值", "type": "int", "description": "压力高阈值。"},
            {"path": "PressureValue.LThreshold", "label": "压力低阈值", "type": "int", "description": "压力低阈值。"},
            {"path": "PressureValue.offset", "label": "压力偏移", "type": "float", "step": 0.1, "description": "对压力测量值做整体偏移补偿。"},
            {"path": "PressureValue.VSW", "label": "压力优先/使能", "type": "bool", "description": "该位在代码中映射到 Priority 布尔值，用于压力通道的优先/使能标志。"},
        ],
    },
    {
        "key": "respiratory",
        "title": "呼吸参数",
        "description": "控制呼吸流量分区、报警边界和呼吸热证据规则。",
        "fields": [
            {"path": "RespiratoryRate.HeatOnThreshold", "label": "HeatOnThreshold", "type": "int", "description": "固定推荐 -4。"},
            {"path": "RespiratoryRate.HeatOffThreshold", "label": "HeatOffThreshold", "type": "int", "description": "固定推荐 -1。"},
            {"path": "RespiratoryRate.offset", "label": "呼吸偏移", "type": "float", "step": 0.1, "description": "对呼吸流量测量值做整体偏移补偿。"},
            {"path": "RespiratoryRate.DERangeHT", "label": "有效吸气分区阈值", "type": "float", "step": 0.1, "description": "区分有效吸气和干扰波动的正向流速边界。"},
            {"path": "RespiratoryRate.DERangeLT", "label": "有效出气分区阈值", "type": "float", "step": 0.1, "description": "区分有效呼气和干扰波动的负向流速边界。"},
            {"path": "RespiratoryRate.NoChangeAlarmTimeSec", "label": "无变化告警时间", "type": "int", "unit": "秒", "min": 60, "max": 604800, "description": "呼吸状态长时间无变化后触发告警的时长。代码中解析时限制在 60 到 604800 秒之间。"},
            {"path": "RespiratoryRate.ExhaleTimeoutMinSec", "label": "呼气超时下限", "type": "int", "unit": "秒", "min": 1, "max": 3600, "description": "动态呼气超时的最小等待时间。固件解析时限制在 1 到 3600 秒之间。"},
            {"path": "RespiratoryRate.ExhaleTimeoutSec", "label": "呼气超时", "type": "int", "unit": "秒", "min": 0, "max": 3600, "description": "呼气超时时间。0 表示关闭；非零值需不小于 ExhaleTimeoutMinSec，固件解析时限制最大 3600 秒。"},
            {"path": "RespiratoryRate.HeatEvidenceIntervalSec", "label": "呼吸热证据间隔", "type": "int", "unit": "秒", "min": 1, "max": 86400, "description": "呼吸热证据采样间隔。代码中解析时限制在 1 到 86400 秒之间。"},
            {"path": "RespiratoryRate.HeatEvidenceCount", "label": "呼吸热证据计数", "type": "int", "min": 1, "max": 10, "description": "呼吸热证据累计次数门槛。代码中解析时限制在 1 到 10 之间。"},
            {"path": "RespiratoryRate.VSW", "label": "呼吸优先/使能", "type": "bool", "description": "该位在代码中映射到 Priority 布尔值，用于呼吸通道的优先/使能标志。"},
        ],
    },
    {
        "key": "outputs",
        "title": "输出通道使能",
        "description": "控制各输出通道是否参与运行控制。",
        "fields": [
            {"path": "outOnline.HeatChannel1_Online", "label": "通道一加热", "type": "bool", "description": "控制 HEAT_CHANNEL_1 输出通道是否参与在线监测。"},
            {"path": "outOnline.HeatChannel2_Online", "label": "通道二加热", "type": "bool", "description": "控制 HEAT_CHANNEL_2 输出通道是否参与在线监测。"},
            {"path": "outOnline.Valve_Online", "label": "阀门", "type": "bool", "description": "控制 VALVE 输出是否参与在线监测。"},
            {"path": "outOnline.Antifreeze_Online", "label": "防冻", "type": "bool", "description": "控制 ANTIFREEZE 输出是否参与在线监测。"},
            {"path": "outOnline.AlarmOutput_Online", "label": "报警输出", "type": "bool", "description": "控制报警输出是否参与在线监测。"},
        ],
    },
    {
        "key": "iec61850",
        "title": "IEC61850 通信",
        "description": "用于 IEC61850 服务启停、监听地址、端口和最大连接数配置。",
        "fields": [
            {"path": "iec61850Config.enabled", "label": "启用 IEC61850", "type": "bool", "description": "是否启用 IEC61850 服务。"},
            {"path": "iec61850Config.bindIP", "label": "绑定地址", "type": "string", "description": "IEC61850 服务监听地址。0.0.0.0 表示监听所有接口。"},
            {"path": "iec61850Config.port", "label": "端口", "type": "int", "min": 1, "max": 65535, "description": "IEC61850 服务监听端口。"},
            {"path": "iec61850Config.maxClients", "label": "最大客户端数", "type": "int", "min": 1, "max": 1024, "description": "IEC61850 服务允许的最大连接数。"},
        ],
    },
    {
        "key": "iec104",
        "title": "IEC104 通信",
        "description": "用于 IEC104 服务启停、监听地址、端口、公共地址和地址长度配置。",
        "fields": [
            {"path": "iec104Config.enabled", "label": "启用 IEC104", "type": "bool", "description": "是否启用 IEC104 服务。"},
            {"path": "iec104Config.bindIP", "label": "绑定地址", "type": "string", "description": "IEC104 服务监听地址。0.0.0.0 表示监听所有接口。"},
            {"path": "iec104Config.port", "label": "端口", "type": "int", "min": 1, "max": 65535, "description": "IEC104 服务监听端口。"},
            {"path": "iec104Config.commonAddress", "label": "公共地址", "type": "int", "min": 1, "max": 65535, "description": "IEC104 公共地址。"},
            {"path": "iec104Config.cotSize", "label": "传送原因长度", "type": "int", "min": 1, "max": 4, "description": "IEC104 传送原因长度。"},
            {"path": "iec104Config.ioaSize", "label": "信息对象地址长度", "type": "int", "min": 1, "max": 4, "description": "IEC104 信息对象地址长度。"},
            {"path": "iec104Config.caSize", "label": "公共地址长度", "type": "int", "min": 1, "max": 4, "description": "IEC104 公共地址字段长度。"},
            {"path": "iec104Config.maxQueueSize", "label": "最大队列", "type": "int", "min": 1, "max": 100000, "description": "IEC104 内部消息队列上限。"},
        ],
    },
    {
        "key": "tasks",
        "title": "定时任务",
        "description": "控制 HTC1、HTC2 等周期任务的开始时间、循环执行和保持时长。TaskCount 会按任务数量自动回写。",
        "fields": [
            {
                "path": "TaskArray",
                "label": "任务列表",
                "type": "task_array",
                "item_schema": [
                    {"key": "name", "label": "name", "type": "string", "description": "TaskArray[i].name"},
                    {"key": "StartTime", "label": "StartTime", "type": "string", "description": "TaskArray[i].StartTime, e.g. 04/01-07:00"},
                    {"key": "delay", "label": "delay", "type": "int", "unit": "sec", "min": 0, "max": 31536000, "description": "TaskArray[i].delay"},
                    {"key": "HumidityValue.HThreshold", "label": "HumidityValue.HThreshold", "type": "int", "description": "TaskArray[i].HumidityValue.HThreshold"},
                    {"key": "HumidityValue.LThreshold", "label": "HumidityValue.LThreshold", "type": "int", "description": "TaskArray[i].HumidityValue.LThreshold"},
                    {"key": "RespiratoryRate.HeatOnThreshold", "label": "RespiratoryRate.HeatOnThreshold", "type": "int", "description": "TaskArray[i].RespiratoryRate.HeatOnThreshold"},
                    {"key": "RespiratoryRate.HeatOffThreshold", "label": "RespiratoryRate.HeatOffThreshold", "type": "int", "description": "TaskArray[i].RespiratoryRate.HeatOffThreshold"},
                ],
            },
            {"path": "TaskCount", "label": "任务数量", "type": "int", "readonly": True, "description": "该值会根据任务列表数量自动生成。"},
        ],
    },
]


def set_runtime_base(base_dir: Path, asset_base_dir: Path | None = None, data_dir: Path | None = None) -> None:
    global BASE_DIR, DATA_DIR, WEB_DIR, LIVE_DEVICES_PATH
    BASE_DIR = Path(base_dir).resolve()
    assets_root = Path(asset_base_dir).resolve() if asset_base_dir is not None else BASE_DIR
    DATA_DIR = Path(data_dir).resolve() if data_dir is not None else BASE_DIR / "实时数据"
    WEB_DIR = assets_root / "web"
    LIVE_DEVICES_PATH = BASE_DIR / "live_devices.json"
    _CACHE["key"] = None
    _CACHE["analysis"] = None


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def isoformat(dt: datetime | None) -> str | None:
    return dt.isoformat(sep=" ") if dt else None


def round_number(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def read_config_json() -> dict[str, Any]:
    config_file = DATA_DIR / "config.json"
    if not config_file.exists():
        return {}
    return json.loads(config_file.read_text(encoding="utf-8", errors="ignore"))


def write_config_json(config: dict[str, Any]) -> None:
    config_file = DATA_DIR / "config.json"
    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_nested_value(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def set_nested_value(data: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    current: dict[str, Any] = data
    for key in keys[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[keys[-1]] = value


def find_schema_field(path: str) -> dict[str, Any] | None:
    for section in CONFIG_SCHEMA:
        for field in section["fields"]:
            if field["path"] == path:
                return field
    return None


def normalize_scalar_value(field: dict[str, Any], value: Any) -> Any:
    field_type = field["type"]
    label = field["label"]
    if field_type == "bool":
        if isinstance(value, bool):
            normalized = value
        elif isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                normalized = True
            elif lowered in {"false", "0", "no", "off"}:
                normalized = False
            else:
                raise ValueError(f"{label} 需要布尔值")
        else:
            normalized = bool(value)
        return normalized
    if field_type == "int":
        if isinstance(value, bool):
            raise ValueError(f"{label} 不能是布尔值")
        try:
            normalized = int(value)
        except Exception as exc:
            raise ValueError(f"{label} 需要整数") from exc
        if "min" in field and normalized < field["min"]:
            raise ValueError(f"{label} 不能小于 {field['min']}")
        if "max" in field and normalized > field["max"]:
            raise ValueError(f"{label} 不能大于 {field['max']}")
        return normalized
    if field_type == "float":
        if isinstance(value, bool):
            raise ValueError(f"{label} 不能是布尔值")
        try:
            normalized = float(value)
        except Exception as exc:
            raise ValueError(f"{label} 需要数字") from exc
        if "min" in field and normalized < field["min"]:
            raise ValueError(f"{label} 不能小于 {field['min']}")
        if "max" in field and normalized > field["max"]:
            raise ValueError(f"{label} 不能大于 {field['max']}")
        return round(normalized, 4)
    if field_type in {"string", "select"}:
        if field_type == "select" and isinstance(field.get("options"), list) and field["options"]:
            option_values = {opt["value"] if isinstance(opt, dict) else opt for opt in field["options"]}
            raw = str(value) if not isinstance(value, str) else value
            sample = next(iter(option_values))
            if isinstance(sample, int):
                try:
                    normalized = int(raw)
                except Exception as exc:
                    raise ValueError(f"{label} 选项无效") from exc
            else:
                normalized = raw
            if normalized not in option_values:
                raise ValueError(f"{label} 不在允许选项内")
            return normalized
        return "" if value is None else str(value)
    raise ValueError(f"暂不支持的字段类型: {field_type}")


def normalize_task_array(value: Any, field: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("任务列表必须是数组")
    normalized_tasks: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"任务 {index + 1} 必须是对象")
        normalized_item: dict[str, Any] = {}
        for item_field in field["item_schema"]:
            raw = get_nested_value(item, item_field["key"])
            if raw is None:
                continue
            set_nested_value(normalized_item, item_field["key"], normalize_scalar_value(item_field, raw))
        normalized_tasks.append(normalized_item)
    return normalized_tasks


def validate_and_merge_config(incoming_config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(incoming_config, dict):
        raise ValueError("配置内容必须是 JSON 对象")
    current = read_config_json()
    merged = deepcopy(current)

    for section in CONFIG_SCHEMA:
        for field in section["fields"]:
            if field.get("readonly"):
                continue
            path = field["path"]
            incoming_value = get_nested_value(incoming_config, path)
            if incoming_value is None:
                continue
            if field["type"] == "task_array":
                normalized_tasks = normalize_task_array(incoming_value, field)
                set_nested_value(merged, path, normalized_tasks)
                merged["TaskCount"] = len(normalized_tasks)
                continue
            normalized_value = normalize_scalar_value(field, incoming_value)
            set_nested_value(merged, path, normalized_value)

    if "TaskArray" in merged and isinstance(merged["TaskArray"], list):
        merged["TaskCount"] = len(merged["TaskArray"])
    return merged


def safe_mean(values: list[float]) -> float | None:
    return round_number(statistics.fmean(values)) if values else None


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    if len(data) == 1:
        return round_number(data[0])
    pos = (len(data) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return round_number(data[low])
    weight = pos - low
    return round_number(data[low] * (1 - weight) + data[high] * weight)


def compute_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "max": None, "avg": None, "p10": None, "p90": None}
    return {
        "min": round_number(min(values)),
        "max": round_number(max(values)),
        "avg": safe_mean(values),
        "p10": percentile(values, 0.10),
        "p90": percentile(values, 0.90),
    }


def downsample(rows: list[dict[str, Any]], max_points: int) -> list[dict[str, Any]]:
    if len(rows) <= max_points:
        return rows
    step = math.ceil(len(rows) / max_points)
    sampled = [rows[idx] for idx in range(0, len(rows), step)]
    if sampled[-1] != rows[-1]:
        sampled.append(rows[-1])
    return sampled


def compute_interval_seconds(datetimes: list[datetime], default_value: int) -> int:
    if len(datetimes) < 2:
        return default_value
    deltas = []
    previous = datetimes[0]
    for current in datetimes[1:]:
        diff = int((current - previous).total_seconds())
        if diff > 0:
            deltas.append(diff)
        previous = current
    if not deltas:
        return default_value
    return int(statistics.median(deltas))


def file_signature(files: list[Path]) -> list[tuple[str, int, int]]:
    signature = []
    for file in files:
        stat = file.stat()
        signature.append((str(file), stat.st_size, int(stat.st_mtime)))
    return signature


def get_thresholds(config: dict[str, Any], metric_key: str) -> dict[str, float | None]:
    meta = METRIC_META[metric_key]
    section = config.get(meta["section"], {})
    return {
        "high": section.get(meta["high"]),
        "low": section.get(meta["low"]),
    }


def parse_env_files(files: list[Path]) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    for file in files:
        with file.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                match = ENV_ROW_RE.match(text)
                if not match:
                    malformed += 1
                    continue
                rows.append(
                    {
                        "timestamp": parse_timestamp(match.group("ts")),
                        "pressure": float(match.group("pressure")),
                        "temperature": float(match.group("temperature")),
                        "flow": float(match.group("flow")),
                        "humidity": float(match.group("humidity")),
                        "source_file": file.name,
                        "line_number": line_number,
                    }
                )
    rows.sort(key=lambda item: item["timestamp"])
    return rows, malformed


def parse_breath_files(files: list[Path]) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    for file in files:
        with file.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                parts = [part.strip() for part in text.split(",")]
                if len(parts) != 5:
                    malformed += 1
                    continue
                try:
                    state = int(parts[1])
                    rhythm = int(parts[4])
                    rows.append(
                        {
                            "timestamp": parse_timestamp(parts[0]),
                            "state": state,
                            "state_label": STATE_LABELS.get(state, f"UNKNOWN_{state}"),
                            "state_name": STATE_NAMES_ZH.get(state, f"未知状态 {state}"),
                            "flow_rate": float(parts[2]),
                            "elapsed_since_change": float(parts[3]),
                            "rhythm": rhythm,
                            "rhythm_name": RHYTHM_NAMES_ZH.get(rhythm, f"未知标记 {rhythm}"),
                            "source_file": file.name,
                            "line_number": line_number,
                        }
                    )
                except ValueError:
                    malformed += 1
    rows.sort(key=lambda item: item["timestamp"])
    return rows, malformed


def parse_run_files(files: list[Path]) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    for file in files:
        with file.open("r", encoding="utf-8", errors="ignore") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.rstrip()
                if not text:
                    continue
                match = RUN_ROW_RE.match(text)
                if not match:
                    malformed += 1
                    continue
                rows.append(
                    {
                        "timestamp": parse_timestamp(match.group("ts")),
                        "level": match.group("level"),
                        "message": match.group("message"),
                        "source_file": file.name,
                        "line_number": line_number,
                    }
                )
    rows.sort(key=lambda item: item["timestamp"])
    return rows, malformed


def analyze_environment(rows: list[dict[str, Any]], malformed_rows: int, config: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return {
            "total_rows": 0,
            "files": 0,
            "series": [],
            "daily": [],
            "metrics": {},
            "quality": {"duplicates": 0, "gap_count": 0, "largest_gap_sec": 0, "malformed_rows": malformed_rows, "anomalies": []},
            "threshold_breaches": {},
        }

    timestamps = [row["timestamp"] for row in rows]
    interval_sec = compute_interval_seconds(timestamps, 60)
    duplicates = 0
    gap_count = 0
    largest_gap_sec = 0
    anomalies: list[dict[str, Any]] = []

    previous = rows[0]
    for row in rows[1:]:
        diff = int((row["timestamp"] - previous["timestamp"]).total_seconds())
        if diff == 0:
            duplicates += 1
        elif diff > max(interval_sec * 2, interval_sec + 10):
            gap_count += 1
            largest_gap_sec = max(largest_gap_sec, diff)
            if len(anomalies) < 20:
                anomalies.append(
                    {
                        "type": "gap",
                        "start_at": isoformat(previous["timestamp"]),
                        "end_at": isoformat(row["timestamp"]),
                        "gap_sec": diff,
                        "gap_minutes": round_number(diff / 60.0, 1),
                    }
                )
        previous = row

    metrics: dict[str, Any] = {}
    threshold_breaches: dict[str, Any] = {}
    for metric_key in METRIC_META:
        values = [row[metric_key] for row in rows]
        thresholds = get_thresholds(config, metric_key)
        high = thresholds["high"]
        low = thresholds["low"]
        high_count = sum(1 for value in values if high is not None and value > high)
        low_count = sum(1 for value in values if low is not None and value < low)
        metrics[metric_key] = {
            "label": METRIC_META[metric_key]["label"],
            "unit": METRIC_META[metric_key]["unit"],
            "thresholds": thresholds,
            "stats": compute_stats(values),
            "latest": round_number(values[-1]),
        }
        threshold_breaches[metric_key] = {"high": high_count, "low": low_count}

    daily_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        daily_groups[row["timestamp"].strftime("%Y-%m-%d")].append(row)

    daily = []
    expected_per_day = max(1, int((24 * 60 * 60) / interval_sec))
    completeness_values = []
    for date_key in sorted(daily_groups):
        items = daily_groups[date_key]
        daily_entry: dict[str, Any] = {
            "date": date_key,
            "count": len(items),
            "completeness_pct": round_number(len(items) / expected_per_day * 100),
        }
        completeness_values.append(daily_entry["completeness_pct"])
        for metric_key in METRIC_META:
            values = [item[metric_key] for item in items]
            daily_entry[f"{metric_key}_avg"] = safe_mean(values)
            daily_entry[f"{metric_key}_min"] = round_number(min(values))
            daily_entry[f"{metric_key}_max"] = round_number(max(values))
        daily.append(daily_entry)

    daily_completeness_avg = safe_mean([value for value in completeness_values if value is not None])
    for item in daily:
        if item["completeness_pct"] is not None and item["completeness_pct"] < 85 and len(anomalies) < 30:
            anomalies.append(
                {
                    "type": "low_daily_completeness",
                    "date": item["date"],
                    "completeness_pct": item["completeness_pct"],
                }
            )

    series = downsample(
        [
            {
                "ts": isoformat(row["timestamp"]),
                "pressure": round_number(row["pressure"]),
                "temperature": round_number(row["temperature"]),
                "flow": round_number(row["flow"]),
                "humidity": round_number(row["humidity"]),
            }
            for row in rows
        ],
        720,
    )

    return {
        "total_rows": len(rows),
        "files": len({row["source_file"] for row in rows}),
        "start_at": isoformat(rows[0]["timestamp"]),
        "end_at": isoformat(rows[-1]["timestamp"]),
        "interval_sec": interval_sec,
        "interval_label": f"{interval_sec // 60} 分钟" if interval_sec % 60 == 0 else f"{interval_sec} 秒",
        "metrics": metrics,
        "threshold_breaches": threshold_breaches,
        "quality": {
            "duplicates": duplicates,
            "gap_count": gap_count,
            "largest_gap_sec": largest_gap_sec,
            "malformed_rows": malformed_rows,
            "avg_daily_completeness_pct": daily_completeness_avg,
            "anomalies": anomalies,
        },
        "daily": daily,
        "series": series,
    }


def analyze_breath(rows: list[dict[str, Any]], malformed_rows: int, config: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return {
            "total_rows": 0,
            "files": 0,
            "series": [],
            "daily": [],
            "state_counts": [],
            "rhythm_counts": [],
            "quality": {"malformed_rows": malformed_rows},
        }

    thresholds = config.get("RespiratoryRate", {})
    state_counter = Counter(row["state"] for row in rows)
    rhythm_counter = Counter(row["rhythm"] for row in rows)
    positive_flow = sum(1 for row in rows if row["flow_rate"] > 0)
    negative_flow = sum(1 for row in rows if row["flow_rate"] < 0)
    zero_flow = len(rows) - positive_flow - negative_flow
    longest_elapsed = max(row["elapsed_since_change"] for row in rows)
    interval_sec = compute_interval_seconds([row["timestamp"] for row in rows], 1)

    sessions = []
    open_start: datetime | None = None
    for row in rows:
        if row["rhythm"] == 2:
            open_start = row["timestamp"]
        elif row["rhythm"] == 3 and open_start is not None:
            sessions.append((open_start, row["timestamp"]))
            open_start = None
    if open_start is not None:
        sessions.append((open_start, rows[-1]["timestamp"]))

    session_durations = [(end - start).total_seconds() for start, end in sessions if end >= start]

    daily_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        daily_groups[row["timestamp"].strftime("%Y-%m-%d")].append(row)

    daily = []
    for date_key in sorted(daily_groups):
        items = daily_groups[date_key]
        daily.append(
            {
                "date": date_key,
                "count": len(items),
                "alarm_rows": sum(1 for item in items if item["state"] in (3, 4)),
                "state_switches": sum(1 for item in items if item["rhythm"] == 1),
                "segments_started": sum(1 for item in items if item["rhythm"] == 2),
                "segments_closed": sum(1 for item in items if item["rhythm"] == 3),
                "avg_abs_flow": safe_mean([abs(item["flow_rate"]) for item in items]),
                "max_abs_flow": round_number(max(abs(item["flow_rate"]) for item in items)),
            }
        )

    insights = []
    no_change_alarm_sec = thresholds.get("NoChangeAlarmTimeSec")
    if no_change_alarm_sec and longest_elapsed >= no_change_alarm_sec:
        insights.append(
            {
                "level": "warning",
                "title": "检测到可能的长时间无变化窗口",
                "detail": f"呼吸记录中最长状态持续 {round_number(longest_elapsed, 1)} 秒，已达到配置告警阈值 {no_change_alarm_sec} 秒。",
            }
        )
    if state_counter.get(3, 0) or state_counter.get(4, 0):
        insights.append(
            {
                "level": "warning",
                "title": "存在呼吸告警状态",
                "detail": f"低流速告警 {state_counter.get(3, 0)} 次，高流速告警 {state_counter.get(4, 0)} 次。",
            }
        )

    series = downsample(
        [
            {
                "ts": isoformat(row["timestamp"]),
                "flow_rate": round_number(row["flow_rate"]),
                "state": row["state"],
                "state_name": row["state_name"],
                "elapsed_since_change": round_number(row["elapsed_since_change"]),
                "rhythm": row["rhythm"],
            }
            for row in rows
        ],
        1200,
    )

    return {
        "total_rows": len(rows),
        "files": len({row["source_file"] for row in rows}),
        "start_at": isoformat(rows[0]["timestamp"]),
        "end_at": isoformat(rows[-1]["timestamp"]),
        "interval_sec": interval_sec,
        "state_counts": [
            {
                "state": state,
                "state_label": STATE_LABELS.get(state, f"UNKNOWN_{state}"),
                "state_name": STATE_NAMES_ZH.get(state, f"未知状态 {state}"),
                "count": count,
            }
            for state, count in sorted(state_counter.items())
        ],
        "rhythm_counts": [
            {"rhythm": rhythm, "rhythm_name": RHYTHM_NAMES_ZH.get(rhythm, f"未知标记 {rhythm}"), "count": count}
            for rhythm, count in sorted(rhythm_counter.items())
        ],
        "flow_distribution": {"positive": positive_flow, "negative": negative_flow, "near_zero": zero_flow},
        "session_summary": {
            "segments": len(sessions),
            "avg_duration_sec": safe_mean(session_durations),
            "longest_duration_sec": round_number(max(session_durations), 1) if session_durations else 0,
        },
        "quality": {
            "malformed_rows": malformed_rows,
            "longest_elapsed_sec": round_number(longest_elapsed, 1),
            "no_change_alarm_sec": no_change_alarm_sec,
        },
        "daily": daily,
        "series": series,
        "insights": insights,
    }


def analyze_run_log(rows: list[dict[str, Any]], malformed_rows: int) -> dict[str, Any]:
    if not rows:
        return {
            "total_rows": 0,
            "files": 0,
            "levels": {},
            "daily": [],
            "important_events": [],
            "keyword_counts": [],
            "quality": {"malformed_rows": malformed_rows},
        }

    level_counts: dict[str, int] = {"I": 0, "W": 0, "E": 0}
    daily_counter: dict[str, dict[str, int]] = defaultdict(lambda: {"I": 0, "W": 0, "E": 0})
    keyword_counter: dict[str, int] = {}
    important_events: list[dict[str, Any]] = []

    # 预编译关键词别名集合，避免每次重复lower
    keyword_aliases = {
        keyword: tuple(alias.lower() for alias in aliases)
        for keyword, aliases in RUN_KEYWORDS.items()
    }

    for row in rows:
        level = row["level"]
        level_counts[level] = level_counts.get(level, 0) + 1
        date_key = row["timestamp"].strftime("%Y-%m-%d")
        daily_counter[date_key][level] = daily_counter[date_key].get(level, 0) + 1

        message = row["message"]
        message_lower = message.lower()
        for keyword, aliases in keyword_aliases.items():
            if any(alias in message_lower for alias in aliases):
                keyword_counter[keyword] = keyword_counter.get(keyword, 0) + 1

        # 使用预编译的检测条件，减少字符串扫描次数
        important_tokens = (
            "ALARM",
            "open",
            "close",
            "Failed",
            "recover",
            "ONLINE",
            "HeatChannel",
            "VALVE",
            "ANTIFREEZE",
            "MANUAL HEAT",
            "ExhaleTimeout",
            "(Humidity)",
            "Config synced",
            "SD card config updated",
        )
        if level in ("E", "W") or any(token in message for token in important_tokens):
            important_events.append(
                {
                    "ts": isoformat(row["timestamp"]),
                    "level": level,
                    "message": message,
                }
            )

    important_events = important_events[-120:]
    daily = []
    for date_key in sorted(daily_counter):
        counts = daily_counter[date_key]
        daily.append(
            {
                "date": date_key,
                "info": counts.get("I", 0),
                "warn": counts.get("W", 0),
                "error": counts.get("E", 0),
            }
        )

    # 手动排序替代Counter.most_common()，避免Counter开销
    sorted_keywords = sorted(keyword_counter.items(), key=lambda item: item[1], reverse=True)

    return {
        "total_rows": len(rows),
        "files": len({row["source_file"] for row in rows}),
        "start_at": isoformat(rows[0]["timestamp"]),
        "end_at": isoformat(rows[-1]["timestamp"]),
        "levels": {"info": level_counts.get("I", 0), "warn": level_counts.get("W", 0), "error": level_counts.get("E", 0)},
        "daily": daily,
        "keyword_counts": [{"keyword": keyword, "count": count} for keyword, count in sorted_keywords],
        "important_events": important_events,
        "quality": {"malformed_rows": malformed_rows},
    }


def build_config_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": config.get("ver"),
        "config_time": config.get("curDateTime"),
        "double_mode": config.get("DoubleMode"),
        "double_switch": config.get("DoubleSwitch"),
        "force_close_sec": config.get("ForceClose"),
        "temperature": config.get("Temperature", {}),
        "humidity": config.get("HumidityValue", {}),
        "pressure": config.get("PressureValue", {}),
        "respiratory": config.get("RespiratoryRate", {}),
        "out_online": config.get("outOnline", {}),
        "tasks": [
            {
                "name": item.get("name"),
                "start_time": item.get("StartTime"),
                "delay_sec": item.get("delay"),
                "humidity": item.get("HumidityValue", {}),
                "respiratory": item.get("RespiratoryRate", {}),
            }
            for item in config.get("TaskArray", [])
        ],
    }


def build_raw_payload(
    env_rows: list[dict[str, Any]],
    breath_rows: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
    max_run_rows: int = 2000,
) -> dict[str, Any]:
    all_dates = sorted(
        {
            row["timestamp"].strftime("%Y-%m-%d")
            for row in [*env_rows, *breath_rows, *run_rows]
        }
    )
    # 运行日志通常数据量最大，截断保留最近条目以减少JSON体积
    run_rows_out = run_rows
    run_truncated = False
    if len(run_rows) > max_run_rows:
        run_rows_out = run_rows[-max_run_rows:]
        run_truncated = True
    return {
        "available_dates": all_dates,
        "environment_rows": [
            {
                "ts": isoformat(row["timestamp"]),
                "pressure": round_number(row["pressure"]),
                "temperature": round_number(row["temperature"]),
                "flow": round_number(row["flow"]),
                "humidity": round_number(row["humidity"]),
                "source_file": row["source_file"],
                "line_number": row["line_number"],
            }
            for row in env_rows
        ],
        "breath_rows": [
            {
                "ts": isoformat(row["timestamp"]),
                "state": row["state"],
                "state_name": row["state_name"],
                "flow_rate": round_number(row["flow_rate"]),
                "elapsed_since_change": round_number(row["elapsed_since_change"]),
                "rhythm": row["rhythm"],
                "rhythm_name": row["rhythm_name"],
                "source_file": row["source_file"],
                "line_number": row["line_number"],
            }
            for row in breath_rows
        ],
        "run_rows": [
            {
                "ts": isoformat(row["timestamp"]),
                "level": row["level"],
                "message": row["message"],
                "source_file": row["source_file"],
                "line_number": row["line_number"],
            }
            for row in run_rows_out
        ],
        "run_truncated": run_truncated,
        "run_total": len(run_rows),
    }


def build_history_payload_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    raw_data = analysis.get("raw_data", {})
    return {
        "environment_rows": raw_data.get("environment_rows", []),
        "breath_rows": raw_data.get("breath_rows", []),
        "run_rows": raw_data.get("run_rows", []),
    }


def build_insights(environment: dict[str, Any], breath: dict[str, Any], run_log: dict[str, Any]) -> list[dict[str, str]]:
    insights: list[dict[str, str]] = []
    quality = environment.get("quality", {})
    if quality.get("avg_daily_completeness_pct") is not None and quality["avg_daily_completeness_pct"] < 90:
        insights.append(
            {
                "level": "warning",
                "title": "环境数据完整率偏低",
                "detail": f"环境日志平均日完整率为 {quality['avg_daily_completeness_pct']}%，建议先核查日志采样或文件缺失。",
            }
        )
    if quality.get("gap_count", 0) > 0:
        insights.append(
            {
                "level": "warning",
                "title": "环境日志存在时间断档",
                "detail": f"共识别到 {quality['gap_count']} 个时间断档，最长 {round_number(quality.get('largest_gap_sec', 0) / 60.0, 1)} 分钟。",
            }
        )
    flow_breaches = environment.get("threshold_breaches", {}).get("flow", {})
    if flow_breaches.get("high", 0) or flow_breaches.get("low", 0):
        insights.append(
            {
                "level": "warning",
                "title": "分钟级流速存在阈值越界",
                "detail": f"高阈值越界 {flow_breaches.get('high', 0)} 次，低阈值越界 {flow_breaches.get('low', 0)} 次。",
            }
        )
    if run_log.get("levels", {}).get("error", 0):
        insights.append(
            {
                "level": "critical",
                "title": "运行日志包含错误项",
                "detail": f"本批次运行日志共记录错误 {run_log['levels']['error']} 条，建议结合事件时间线排查。",
            }
        )
    insights.extend(breath.get("insights", []))
    if not insights:
        insights.append({"level": "ok", "title": "未发现明显高风险项", "detail": "当前样本中未触发默认风险规则，可继续查看趋势和日报明细。"})
    return insights


def build_summary_text(analysis: dict[str, Any]) -> str:
    overview = analysis["overview"]
    environment = analysis["environment"]
    breath = analysis["breath"]
    run_log = analysis["run_log"]
    lines = [
        "YLDQ 本地数据分析摘要",
        "=" * 28,
        f"生成时间: {analysis['meta']['generated_at']}",
        f"数据目录: {analysis['meta']['data_root']}",
        f"数据时间范围: {overview.get('start_at') or '-'} -> {overview.get('end_at') or '-'}",
        "",
        "一、规模概览",
        f"- 环境日志: {environment.get('files', 0)} 个文件 / {environment.get('total_rows', 0)} 条记录",
        f"- 呼吸日志: {breath.get('files', 0)} 个文件 / {breath.get('total_rows', 0)} 条记录",
        f"- 运行日志: {run_log.get('files', 0)} 个文件 / {run_log.get('total_rows', 0)} 条记录",
        "",
        "二、环境数据",
        f"- 推断采样间隔: {environment.get('interval_label', '-')}",
        f"- 平均日完整率: {environment.get('quality', {}).get('avg_daily_completeness_pct', '-')}",
        f"- 时间断档: {environment.get('quality', {}).get('gap_count', 0)} 个",
        "",
        "三、呼吸数据",
        f"- 呼吸片段数: {breath.get('session_summary', {}).get('segments', 0)}",
        f"- 最长单段时长: {breath.get('session_summary', {}).get('longest_duration_sec', 0)} 秒",
        f"- 最长状态持续: {breath.get('quality', {}).get('longest_elapsed_sec', 0)} 秒",
        "",
        "四、运行日志",
        f"- 信息/警告/错误: {run_log.get('levels', {}).get('info', 0)} / {run_log.get('levels', {}).get('warn', 0)} / {run_log.get('levels', {}).get('error', 0)}",
        "",
        "五、自动诊断",
    ]
    for insight in analysis["insights"]:
        lines.append(f"- [{insight['level']}] {insight['title']}：{insight['detail']}")
    return "\n".join(lines) + "\n"


def build_standalone_report_html(analysis: dict[str, Any]) -> str:
    index_html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    styles_css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
    app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    chart_js = (WEB_DIR / "chart_interactions.js").read_text(encoding="utf-8")
    payload = json.dumps(analysis, ensure_ascii=False)
    schema_json = json.dumps(CONFIG_SCHEMA, ensure_ascii=False)
    kb_inline = ""
    kb_path = WEB_DIR / "log_knowledge_base.json"
    if kb_path.exists():
        kb_content = kb_path.read_text(encoding="utf-8")
        kb_inline = f"<script>\nwindow.__LOG_KB__ = {kb_content};\n</script>\n"

    html = index_html.replace(
        '<link rel="stylesheet" href="./styles.css">',
        f"<style>\n{styles_css}\n</style>",
    )
    html = html.replace(
        '<script src="./chart_interactions.js"></script>',
        f"<script>\n{chart_js}\n</script>",
    )
    html = html.replace(
        '<script src="./app.js"></script>',
        (
            "<script>\n"
            "window.__STATIC_REPORT__ = true;\n"
            f"window.__ANALYSIS__ = {payload};\n"
            f"window.__CONFIG_SCHEMA__ = {schema_json};\n"
            "</script>\n"
            f"{kb_inline}"
            f"<script>\n{app_js}\n</script>"
        ),
    )
    return html


def write_customer_outputs(output_dir: Path, analysis: dict[str, Any] | None = None) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis = analysis or load_analysis(force_refresh=True)

    report_path = output_dir / "分析报告.html"
    summary_path = output_dir / "分析摘要.txt"
    json_path = output_dir / "analysis.json"

    report_path.write_text(build_standalone_report_html(analysis), encoding="utf-8")
    summary_path.write_text(analysis["summary_text"], encoding="utf-8")
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "report": report_path,
        "summary": summary_path,
        "json": json_path,
    }


def _load_analysis_impl(data_dir: Path) -> dict[str, Any]:
    data_dir = Path(data_dir)
    env_files = sorted((data_dir / "data_0").glob("log_*.csv"))
    breath_files = sorted((data_dir / "breath_data").glob("breath_*.csv"))
    run_files = sorted((data_dir / "run").glob("*.csv"))
    config_file = data_dir / "config.json"
    config = {}
    if config_file.exists():
        config = json.loads(config_file.read_text(encoding="utf-8", errors="ignore"))

    env_rows, env_malformed = parse_env_files(env_files)
    breath_rows, breath_malformed = parse_breath_files(breath_files)
    run_rows, run_malformed = parse_run_files(run_files)

    environment = analyze_environment(env_rows, env_malformed, config)
    breath = analyze_breath(breath_rows, breath_malformed, config)
    run_log = analyze_run_log(run_rows, run_malformed)
    overview_start_candidates = [value for value in [environment.get("start_at"), breath.get("start_at"), run_log.get("start_at")] if value]
    overview_end_candidates = [value for value in [environment.get("end_at"), breath.get("end_at"), run_log.get("end_at")] if value]

    analysis = {
        "meta": {
            "generated_at": isoformat(datetime.now()),
            "data_root": str(data_dir),
        },
        "overview": {
            "start_at": min(overview_start_candidates) if overview_start_candidates else None,
            "end_at": max(overview_end_candidates) if overview_end_candidates else None,
            "latest_environment_sample": environment.get("series", [])[-1] if environment.get("series") else None,
            "env_file_count": len(env_files),
            "breath_file_count": len(breath_files),
            "run_file_count": len(run_files),
        },
        "config": config,
        "config_snapshot": build_config_snapshot(config),
        "raw_data": build_raw_payload(env_rows, breath_rows, run_rows),
        "environment": environment,
        "breath": breath,
        "run_log": run_log,
    }
    analysis["insights"] = build_insights(environment, breath, run_log)
    analysis["summary_text"] = build_summary_text(analysis)
    return analysis


def load_analysis(force_refresh: bool = False) -> dict[str, Any]:
    env_files = sorted((DATA_DIR / "data_0").glob("log_*.csv"))
    breath_files = sorted((DATA_DIR / "breath_data").glob("breath_*.csv"))
    run_files = sorted((DATA_DIR / "run").glob("*.csv"))
    config_file = DATA_DIR / "config.json"
    signature = {
        "config": (str(config_file), config_file.stat().st_size, int(config_file.stat().st_mtime)) if config_file.exists() else None,
        "env": file_signature(env_files),
        "breath": file_signature(breath_files),
        "run": file_signature(run_files),
    }
    if not force_refresh and _CACHE["key"] == signature and _CACHE["analysis"] is not None:
        return _CACHE["analysis"]

    analysis = _load_analysis_impl(DATA_DIR)

    _CACHE["key"] = signature
    _CACHE["analysis"] = analysis
    return analysis


def load_analysis_from_dir(data_dir: Path) -> dict[str, Any]:
    return _load_analysis_impl(data_dir)


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def guess_type(self, path: str) -> str:
        guessed = super().guess_type(path)
        if guessed == "text/html":
            return "text/html; charset=utf-8"
        if guessed == "text/css":
            return "text/css; charset=utf-8"
        if guessed in {"text/javascript", "application/javascript"}:
            return "application/javascript; charset=utf-8"
        return guessed

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/live/"):
            self.handle_live_get(parsed)
            return
        if parsed.path == "/api/analysis":
            self.send_analysis(parsed.query)
            return
        if parsed.path == "/api/config":
            self.send_config_payload()
            return
        if parsed.path == "/api/simulation/defaults":
            self.send_simulation_defaults(parsed.query)
            return
        if parsed.path == "/api/parameter-recommendations":
            self.send_parameter_recommendations(parsed.query)
            return
        if parsed.path == "/api/summary.txt":
            self.send_summary_text(parsed.query)
            return
        if parsed.path in {"/", ""}:
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/shutdown":
            self.handle_shutdown()
            return
        if parsed.path.startswith("/api/live/"):
            self.handle_live_post(parsed)
            return
        if parsed.path == "/api/config":
            self.save_config_payload()
            return
        if parsed.path == "/api/parameter-recommendations-preview":
            self.send_parameter_recommendations_preview()
            return
        if parsed.path == "/api/simulation/run":
            self.send_simulation_run()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unsupported endpoint")

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/live/"):
            self.handle_live_put(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unsupported endpoint")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/live/"):
            self.handle_live_delete(parsed)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unsupported endpoint")

    def _read_json_body(self) -> dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""
        if not raw_body:
            return {}
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是对象")
        return payload

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        download_name: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(body)

    def _get_live_devices_payload(self) -> dict[str, Any]:
        payload = load_live_devices(LIVE_DEVICES_PATH)
        if LIVE_SESSION_STATE.get("selected_device_id") is None:
            LIVE_SESSION_STATE["selected_device_id"] = payload.get("selectedDeviceId")
        return payload

    def _get_live_selected_device(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        selected_device_id = payload.get("selectedDeviceId")
        return next((item for item in payload["devices"] if item["id"] == selected_device_id), None)

    def _get_live_requested_device_id(self, parsed: Any) -> str | None:
        params = parse_qs(parsed.query)
        requested_device_id = str(params.get("deviceId", [""])[0] or "").strip()
        return requested_device_id or None

    def _build_live_request_context(self, parsed: Any, service_status: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        devices_payload = self._get_live_devices_payload()
        context = _build_live_device_context(
            devices_payload,
            service_status,
            requested_device_id=self._get_live_requested_device_id(parsed),
        )
        return devices_payload, context

    def handle_live_put(self, parsed: Any) -> None:
        try:
            if parsed.path.startswith("/api/live/devices/"):
                device_id = parsed.path.rsplit("/", 1)[-1]
                payload = self._read_json_body()
                device = update_live_device(LIVE_DEVICES_PATH, device_id, payload)
                self._send_json({"ok": True, "device": device, **load_live_devices(LIVE_DEVICES_PATH)})
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Unsupported live endpoint")
        except KeyError as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def handle_live_get(self, parsed: Any) -> None:
        live_service = _get_live_service()
        if parsed.path == "/api/live/catalog":
            catalog = get_register_catalog()
            self._send_json(
                {
                    "ok": True,
                    "catalog": catalog,
                    "summary": get_register_catalog_summary(),
                    "defaultPollingCommands": build_default_polling_commands(catalog),
                }
            )
            return
        if parsed.path == "/api/live/devices":
            payload = self._get_live_devices_payload()
            self._send_json({"ok": True, **payload})
            return
        if parsed.path == "/api/live/devices/export":
            body = export_live_devices_json(LIVE_DEVICES_PATH).encode("utf-8")
            self._send_bytes(
                body,
                "application/json; charset=utf-8",
                download_name="live_devices.json",
            )
            return

        service_status = live_service.get_status()
        _, context = self._build_live_request_context(parsed, service_status)
        device_id = context["selectedDeviceId"]

        if parsed.path == "/api/live/session/status":
            device_session = live_service.get_device_status(device_id) if device_id else {"running": False, "device_id": device_id}
            self._send_json(
                {
                    "ok": True,
                    "selectedDeviceId": device_id,
                    "activeDeviceIds": context["activeDeviceIds"],
                    "activeDeviceId": context["activeDeviceId"],
                    "matchesSelectedDevice": context["matchesSelectedDevice"],
                    "selectedDevice": context["selectedDevice"],
                    "session": device_session,
                    "activeSession": service_status,
                }
            )
            return
        if parsed.path == "/api/live/session/all-device-statuses":
            all_statuses = live_service.get_device_status()
            self._send_json({"ok": True, "deviceStatuses": all_statuses, "globalRunning": service_status.get("running", False)})
            return
        if parsed.path == "/api/live/snapshot":
            snapshot = live_service.get_snapshot(device_id=device_id)
            self._send_json(
                {
                    "ok": True,
                    "selectedDeviceId": device_id,
                    "activeDeviceId": context["activeDeviceId"],
                    "matchesSelectedDevice": context["matchesSelectedDevice"],
                    "snapshot": _build_live_snapshot_projection(snapshot, service_status, context),
                }
            )
            return
        if parsed.path == "/api/live/series":
            params = parse_qs(parsed.query)
            window_ms = int(params.get("windowMs", ["300000"])[0] or 300000)
            limit = int(params.get("limit", ["300"])[0] or 300)
            series = live_service.get_series(device_id=device_id, window_ms=window_ms, limit=limit)
            self._send_json(
                {
                    "ok": True,
                    "windowMs": window_ms,
                    "selectedDeviceId": device_id,
                    "activeDeviceId": context["activeDeviceId"],
                    "matchesSelectedDevice": context["matchesSelectedDevice"],
                    "series": _build_live_series_projection(series, context),
                }
            )
            return
        if parsed.path == "/api/live/events":
            params = parse_qs(parsed.query)
            limit = int(params.get("limit", ["80"])[0] or 80)
            events = live_service.get_events(device_id=device_id, limit=limit)
            self._send_json({"ok": True, **_build_live_events_projection(events, context)})
            return
        if parsed.path == "/api/live/traffic":
            params = parse_qs(parsed.query)
            limit = int(params.get("limit", ["160"])[0] or 160)
            req_device_id = params.get("deviceId", [None])[0] or None
            traffic = live_service.get_command_traffic(device_id=req_device_id, limit=limit)
            self._send_json({"ok": True, **_build_live_traffic_projection(traffic, context)})
            return
        if parsed.path == "/api/live/parameters":
            sections = live_service.get_parameters(device_id=device_id, include_cached=context["matchesSelectedDevice"])
            self._send_json({"ok": True, **_build_live_parameters_projection(sections, context)})
            return
        if parsed.path == "/api/live/session/meta":
            meta = live_service.get_session_meta(device_id=device_id)
            projected_meta = _build_live_meta_projection(meta, service_status, context)
            self._send_json(
                {
                    "ok": True,
                    "selectedDeviceId": device_id,
                    "activeDeviceId": context["activeDeviceId"],
                    "matchesSelectedDevice": context["matchesSelectedDevice"],
                    "meta": {
                        **projected_meta,
                        "message": projected_meta["available"]
                        and "实时采集会话已落盘，可导出或直接转入分析。"
                        or "当前选中设备还没有可用的实时采集会话。",
                    },
                }
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unsupported live endpoint")

    def handle_shutdown(self) -> None:
        import threading

        self._send_json({"ok": True, "message": "shutting down"})
        try:
            svc = _get_live_service()
            svc.stop_all()
        except Exception:
            pass
        threading.Thread(target=self._delayed_shutdown, daemon=True).start()

    @staticmethod
    def _delayed_shutdown() -> None:
        import os
        import time

        time.sleep(0.5)
        os._exit(0)

    def handle_live_post(self, parsed: Any) -> None:
        live_service = _get_live_service()
        try:
            if parsed.path == "/api/live/devices":
                payload = self._read_json_body()
                device = create_live_device(LIVE_DEVICES_PATH, payload)
                LIVE_SESSION_STATE["selected_device_id"] = device["id"]
                self._send_json({"ok": True, "device": device, **load_live_devices(LIVE_DEVICES_PATH)})
                return
            if parsed.path == "/api/live/devices/import":
                if live_service.get_status().get("running"):
                    self._send_json(
                        {"ok": False, "message": "请先停止实时采集，再导入设备配置。"},
                        status=HTTPStatus.CONFLICT,
                    )
                    return
                payload = self._read_json_body()
                imported = import_live_devices_payload(LIVE_DEVICES_PATH, payload.get("config"))
                LIVE_SESSION_STATE["selected_device_id"] = imported.get("selectedDeviceId")
                self._send_json({"ok": True, "message": "设备配置已导入", **imported})
                return
            if parsed.path == "/api/live/session/start":
                devices_payload = self._get_live_devices_payload()
                enabled_devices = [d for d in devices_payload.get("devices") or [] if bool(d.get("enabled", True))]
                if not enabled_devices:
                    self._send_json({"ok": False, "message": "no enabled devices found"}, status=HTTPStatus.BAD_REQUEST)
                    return
                state = live_service.start_all(
                    enabled_devices,
                    session_root=BASE_DIR / "实时采集会话",
                    config_snapshot=read_config_json(),
                )
                LIVE_SESSION_STATE.update({"running": True, "device_ids": state.get("device_ids") or []})
                self._send_json({"ok": True, "message": f"started {state.get('device_count', 0)} devices", "state": state})
                return
            if parsed.path == "/api/live/session/stop":
                state = live_service.stop_all()
                LIVE_SESSION_STATE["running"] = False
                self._send_json({"ok": True, "message": "all live sessions stopped", "state": state})
                return
            if parsed.path == "/api/live/session/select":
                payload = self._read_json_body()
                device_id = str(payload.get("deviceId") or "")
                result = select_live_device(LIVE_DEVICES_PATH, device_id)
                LIVE_SESSION_STATE["selected_device_id"] = device_id
                self._send_json({"ok": True, **result})
                return
            if parsed.path == "/api/live/write":
                payload = self._read_json_body()
                device_id = str(payload.get("deviceId") or "")
                if not device_id:
                    self._send_json({"ok": False, "message": "deviceId is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                result = live_service.write_value(device_id, str(payload.get("itemId") or ""), payload.get("value"))
                self._send_json({"ok": True, **result})
                return
            if parsed.path == "/api/live/session/export":
                payload = self._read_json_body()
                device_id = str(payload.get("deviceId") or "")
                if not device_id:
                    self._send_json({"ok": False, "message": "deviceId is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                target_dir = Path(str(payload.get("targetDir") or "").strip() or BASE_DIR / "实时采集会话_导出")
                export_payload = live_service.export_session(device_id, target_dir)
                self._send_json({"ok": True, "message": "live session exported", "export": export_payload})
                return
            if parsed.path == "/api/live/session/analyze":
                payload = self._read_json_body()
                device_id = str(payload.get("deviceId") or "")
                if not device_id:
                    self._send_json({"ok": False, "message": "deviceId is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                target_dir = Path(str(payload.get("targetDir") or "").strip() or BASE_DIR / "实时采集会话_导出")
                export_payload = live_service.export_session(device_id, target_dir)
                analysis = load_analysis_from_dir(Path(export_payload["exportDir"]))
                self._send_json({"ok": True, "message": "live session exported and analyzed", "export": export_payload, "analysis": analysis})
                return
            if parsed.path == "/api/live/poll-parameters":
                payload = self._read_json_body()
                device_id = str(payload.get("deviceId") or "")
                if not device_id:
                    self._send_json({"ok": False, "message": "deviceId is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                result = live_service.poll_slow_group(device_id)
                self._send_json({"ok": True, **result})
                return
            if parsed.path == "/api/live/debug/send":
                payload = self._read_json_body()
                device_id = str(payload.get("deviceId") or "")
                if not device_id:
                    self._send_json({"ok": False, "message": "deviceId is required"}, status=HTTPStatus.BAD_REQUEST)
                    return
                devices_payload = self._get_live_devices_payload()
                device = _find_live_device(devices_payload, device_id)
                if device is None:
                    self._send_json({"ok": False, "message": f"device not found: {device_id}"}, status=HTTPStatus.NOT_FOUND)
                    return
                result = live_service.send_debug_frame(
                    device,
                    str(payload.get("requestHex") or ""),
                    append_crc_bytes=bool(payload.get("appendCrc", False)),
                    expect_response=bool(payload.get("expectResponse", True)),
                    response_timeout_ms=int(payload.get("responseTimeoutMs") or 0) or None,
                )
                self._send_json({"ok": True, **result})
                return
            if parsed.path == "/api/live/traffic/clear":
                result = live_service.clear_command_traffic()
                self._send_json({"ok": True, **result})
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Unsupported live endpoint")
        except KeyError as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def handle_live_delete(self, parsed: Any) -> None:
        try:
            if parsed.path.startswith("/api/live/devices/"):
                device_id = parsed.path.rsplit("/", 1)[-1]
                payload = delete_live_device(LIVE_DEVICES_PATH, device_id)
                if LIVE_SESSION_STATE.get("selected_device_id") == device_id:
                    LIVE_SESSION_STATE["selected_device_id"] = payload.get("selectedDeviceId")
                self._send_json({"ok": True, **payload})
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Unsupported live endpoint")
        except KeyError as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def send_analysis(self, query: str) -> None:
        params = parse_qs(query)
        analysis = load_analysis(force_refresh=params.get("refresh") == ["1"])
        body = json.dumps(analysis, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_summary_text(self, query: str) -> None:
        params = parse_qs(query)
        analysis = load_analysis(force_refresh=params.get("refresh") == ["1"])
        body = analysis["summary_text"].encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_config_payload(self) -> None:
        payload = {
            "config": read_config_json(),
            "schema": CONFIG_SCHEMA,
            "editable": True,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_simulation_defaults(self, query: str) -> None:
        params = parse_qs(query)
        analysis = load_analysis(force_refresh=params.get("refresh") == ["1"])
        defaults = params_from_config(analysis.get("config", {}))
        payload = {
            "ok": True,
            "params": defaults,
            "presets": [
                {
                    "id": "current",
                    "name": "当前配置",
                    "params": defaults,
                },
                {
                    "id": "recommended",
                    "name": "推荐参数",
                    "params": {
                        **defaults,
                        "heat_on_threshold": -4,
                        "heat_off_threshold": 1,
                        "breath_evidence_interval_sec": 60,
                        "breath_evidence_count": 3,
                        "exhale_timeout_min_sec": 300,
                        "exhale_timeout_sec": 1000,
                    },
                },
                {
                    "id": "count5",
                    "name": "累计5次验证",
                    "params": {
                        **defaults,
                        "heat_on_threshold": -4,
                        "heat_off_threshold": 1,
                        "breath_evidence_interval_sec": 60,
                        "breath_evidence_count": 5,
                        "exhale_timeout_min_sec": 300,
                        "exhale_timeout_sec": 1000,
                    },
                },
            ],
        }
        self._send_json(payload)

    def send_simulation_run(self) -> None:
        try:
            payload = self._read_json_body()
            payload_raw_data = payload.get("rawData") if isinstance(payload.get("rawData"), dict) else None
            payload_config = payload.get("config") if isinstance(payload.get("config"), dict) else None
            if payload_raw_data is None or payload_config is None:
                analysis = load_analysis(force_refresh=bool(payload.get("refresh")))
                raw_data = payload_raw_data or analysis.get("raw_data", {})
                config = payload_config or analysis.get("config", {})
            else:
                raw_data = payload_raw_data
                config = payload_config
            scenarios = payload.get("scenarios") or []
            if not isinstance(scenarios, list) or not scenarios:
                scenarios = [{"id": "current", "name": "当前配置", "params": {}}]
            results = []
            for index, scenario in enumerate(scenarios):
                if not isinstance(scenario, dict):
                    continue
                scenario_id = str(scenario.get("id") or f"scenario_{index + 1}")
                scenario_name = str(scenario.get("name") or scenario_id)
                scenario_params = scenario.get("params") if isinstance(scenario.get("params"), dict) else {}
                result = run_simulation(
                    environment_rows=raw_data.get("environment_rows", []),
                    breath_rows=raw_data.get("breath_rows", []),
                    config=config,
                    overrides=scenario_params,
                    date_range=payload.get("dateRange") if isinstance(payload.get("dateRange"), dict) else None,
                )
                result["id"] = scenario_id
                result["name"] = scenario_name
                results.append(result)
            self._send_json({"ok": True, "results": results})
        except Exception as exc:
            self._send_json({"ok": False, "message": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def send_parameter_recommendations(self, query: str) -> None:
        params = parse_qs(query)
        strategy = params.get("strategy", ["balanced"])[0] or "balanced"
        analysis = load_analysis(force_refresh=params.get("refresh") == ["1"])
        payload = build_parameter_recommendation_payload(
            config=analysis.get("config", {}),
            history=build_history_payload_from_analysis(analysis),
            strategy=strategy,
            schema=CONFIG_SCHEMA,
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_parameter_recommendations_preview(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            config = payload.get("config")
            history = payload.get("history")
            strategy = payload.get("strategy") or "balanced"
            schema = payload.get("schema") or CONFIG_SCHEMA
            if not isinstance(config, dict):
                raise ValueError("config 必须是对象")
            if not isinstance(history, dict):
                raise ValueError("history 必须是对象")
            response = build_parameter_recommendation_payload(
                config=config,
                history=history,
                strategy=strategy,
                schema=schema,
            )
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            response = {
                "ok": False,
                "message": str(exc),
            }
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def save_config_payload(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            incoming_config = payload.get("config")
            merged = validate_and_merge_config(incoming_config)
            write_config_json(merged)
            _CACHE["key"] = None
            _CACHE["analysis"] = None
            response = {
                "ok": True,
                "message": "配置已保存到 config.json",
                "config": merged,
            }
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            response = {
                "ok": False,
                "message": str(exc),
            }
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.BAD_REQUEST)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[HTTP] {self.address_string()} - {format % args}")


def main() -> None:
    if not WEB_DIR.exists():
        raise SystemExit(f"Web 目录不存在: {WEB_DIR}")

    load_analysis(force_refresh=True)
    server = ThreadingHTTPServer((HOST, PORT), DashboardRequestHandler)
    print(f"YLDQ 数据分析系统已启动: http://{HOST}:{PORT}")
    print(f"数据目录: {DATA_DIR}")
    print("按 Ctrl+C 结束服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
