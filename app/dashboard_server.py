"""YLDQ 6.0 远程监控 HTTP 服务。"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from live_device_store import (
    clear_pending_device_profile,
    create_live_device,
    delete_live_device,
    load_live_devices,
    select_live_device,
    stage_pending_device_profile,
    update_live_device,
)
from live_polling_commands import build_default_polling_commands
from live_modbus_client import ModbusError
from live_register_catalog import PROTOCOL_VERSION_WORD, get_register_catalog, get_register_catalog_summary
from monitoring_projection import build_monitoring_snapshot
from session_archive import get_session_detail, list_sessions


APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
WEB_DIR = APP_DIR / "web"
LIVE_DEVICES_PATH = BASE_DIR / "live_devices.json"
SESSIONS_DIR = BASE_DIR / "实时采集会话"
HOST = "127.0.0.1"
PORT = 8765
MAX_JSON_BODY_BYTES = 1024 * 1024


def _service():
    from live_acquisition_service import get_live_acquisition_service
    return get_live_acquisition_service()


def set_runtime_base(base_dir: Path, asset_base_dir: Path | None = None) -> None:
    global BASE_DIR, WEB_DIR, LIVE_DEVICES_PATH, SESSIONS_DIR
    BASE_DIR = Path(base_dir).resolve()
    assets = Path(asset_base_dir).resolve() if asset_base_dir else APP_DIR
    WEB_DIR = assets / "web"
    LIVE_DEVICES_PATH = BASE_DIR / "live_devices.json"
    SESSIONS_DIR = BASE_DIR / "实时采集会话"
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _find_device(payload: dict[str, Any], device_id: str | None) -> dict[str, Any] | None:
    return next((item for item in payload.get("devices", []) if item.get("id") == device_id), None)


def _serial_ports() -> list[dict[str, str]]:
    try:
        from serial.tools import list_ports
        return [{"device": port.device, "description": port.description or port.device} for port in list_ports.comports()]
    except Exception:
        return []


def build_bootstrap_payload() -> dict[str, Any]:
    devices = load_live_devices(LIVE_DEVICES_PATH)
    service = _service()
    device_items = devices.get("devices", [])
    return {
        "app": {
            "name": "YLDQ 6.0 远程监控系统",
            "version": "6.0.0",
            "protocol": "Modbus V9.1",
            "protocolWord": f"0x{PROTOCOL_VERSION_WORD:04X}",
        },
        "devices": devices,
        "serialPorts": _serial_ports(),
        "catalogSummary": get_register_catalog_summary(),
        "pollingPlan": build_default_polling_commands(),
        "acquisition": service.get_status(),
        "deviceStatuses": service.get_fleet_status(device_items),
    }


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    server_version = "YLDQMonitor/6.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            if parsed.path == "/":
                self.path = "/index.html"
            return super().do_GET()
        try:
            self._handle_get(parsed.path, parse_qs(parsed.query))
        except Exception as exc:
            self._error(exc)

    def do_POST(self) -> None:
        self._handle_mutation("POST")

    def do_PUT(self) -> None:
        self._handle_mutation("PUT")

    def do_DELETE(self) -> None:
        self._handle_mutation("DELETE")

    def _handle_get(self, path: str, query: dict[str, list[str]]) -> None:
        service = _service()
        device_id = self._query(query, "deviceId")
        if not device_id and path in {
            "/api/monitor/snapshot", "/api/monitor/series", "/api/monitor/events",
            "/api/config/parameters", "/api/session/meta", "/api/sessions/list",
        }:
            device_id = load_live_devices(LIVE_DEVICES_PATH).get("selectedDeviceId")
        if path == "/api/health":
            return self._json({"ok": True, "service": "YLDQ 6.0 monitor", "protocol": "9.1"})
        if path == "/api/bootstrap":
            return self._json(build_bootstrap_payload())
        if path == "/api/devices":
            return self._json(load_live_devices(LIVE_DEVICES_PATH))
        if path == "/api/catalog":
            return self._json({"summary": get_register_catalog_summary(), "items": get_register_catalog()})
        if path == "/api/acquisition/status":
            devices = load_live_devices(LIVE_DEVICES_PATH).get("devices", [])
            return self._json({"global": service.get_status(), "devices": service.get_fleet_status(devices)})
        if path == "/api/monitor/snapshot":
            devices = load_live_devices(LIVE_DEVICES_PATH)
            device_id = device_id or devices.get("selectedDeviceId")
            raw = service.get_snapshot(device_id)
            return self._json(build_monitoring_snapshot(raw, _find_device(devices, device_id)))
        if path == "/api/monitor/series":
            window_ms = self._query_int(query, "windowMs", 900000, 10000, 604800000)
            limit = self._query_int(query, "limit", 600, 10, 2000)
            return self._json(service.get_series(
                device_id,
                window_ms=window_ms,
                limit=limit,
                start_at=self._query(query, "start"),
                end_at=self._query(query, "end"),
            ))
        if path == "/api/monitor/events":
            return self._json({"items": service.get_events(
                device_id,
                self._query_int(query, "limit", 100, 1, 500),
                start_at=self._query(query, "start"),
                end_at=self._query(query, "end"),
            )})
        if path == "/api/monitor/traffic":
            return self._json({"items": service.get_command_traffic(device_id, self._query_int(query, "limit", 120, 1, 1000))})
        if path == "/api/config/parameters":
            return self._json(service.get_parameters(device_id))
        if path == "/api/session/meta":
            return self._json(service.get_session_meta(device_id))
        if path == "/api/sessions/list":
            statuses = service.get_device_status()
            active_names = {
                Path(str(status.get("session_dir"))).name
                for status in statuses.values()
                if status.get("running") and status.get("session_dir")
            }
            return self._json(list_sessions(
                SESSIONS_DIR,
                device_id=device_id,
                active_session_names=active_names,
                limit=self._query_int(query, "limit", 200, 1, 500),
            ))
        if path == "/api/sessions/detail":
            statuses = service.get_device_status()
            active_names = {
                Path(str(status.get("session_dir"))).name
                for status in statuses.values()
                if status.get("running") and status.get("session_dir")
            }
            return self._json(get_session_detail(SESSIONS_DIR, self._query(query, "name") or "", active_session_names=active_names))
        self.send_error(HTTPStatus.NOT_FOUND, "API not found")

    def _handle_mutation(self, method: str) -> None:
        parsed = urlparse(self.path)
        try:
            self._validate_mutation_origin()
            body = self._read_json() if method != "DELETE" else {}
            path = parsed.path
            service = _service()
            if method == "POST" and path == "/api/devices":
                return self._json(create_live_device(LIVE_DEVICES_PATH, body), HTTPStatus.CREATED)
            if path.startswith("/api/devices/"):
                suffix = unquote(path.removeprefix("/api/devices/"))
                if suffix.endswith("/select") and method == "POST":
                    return self._json(select_live_device(LIVE_DEVICES_PATH, suffix.removesuffix("/select")))
                if method == "PUT":
                    updated = update_live_device(LIVE_DEVICES_PATH, suffix, body)
                    status = service.get_device_status().get(suffix) or {}
                    if status.get("running"):
                        service.start_all([updated], session_root=SESSIONS_DIR, config_snapshot={"protocol": "9.1"})
                    return self._json(updated)
                if method == "DELETE":
                    service.stop_devices({suffix})
                    return self._json(delete_live_device(LIVE_DEVICES_PATH, suffix))
            if method == "POST" and path == "/api/acquisition/start":
                devices_payload = load_live_devices(LIVE_DEVICES_PATH)
                raw_ids = body.get("deviceIds", [])
                if not isinstance(raw_ids, list):
                    raise ValueError("deviceIds 必须是字符串数组")
                if any(not isinstance(value, str) or not value.strip() for value in raw_ids):
                    raise ValueError("deviceIds 只能包含非空字符串")
                requested = {value.strip() for value in raw_ids}
                if not requested and devices_payload.get("selectedDeviceId"):
                    requested = {str(devices_payload["selectedDeviceId"])}
                known = {str(item.get("id")) for item in devices_payload.get("devices", [])}
                unknown = requested - known
                if unknown:
                    raise KeyError(f"设备不存在: {', '.join(sorted(unknown))}")
                devices = [item for item in devices_payload.get("devices", []) if item.get("id") in requested]
                disabled = [str(item.get("id")) for item in devices if not item.get("enabled", True)]
                if disabled:
                    raise ValueError(f"禁用设备不能启动: {', '.join(disabled)}")
                return self._json(service.start_all(devices, session_root=SESSIONS_DIR, config_snapshot={"protocol": "9.1"}))
            if method == "POST" and path == "/api/acquisition/stop":
                raw_ids = body.get("deviceIds", [])
                if not isinstance(raw_ids, list):
                    raise ValueError("deviceIds 必须是字符串数组")
                if any(not isinstance(value, str) or not value.strip() for value in raw_ids):
                    raise ValueError("deviceIds 只能包含非空字符串")
                requested = {value.strip() for value in raw_ids}
                if requested:
                    known = {str(item.get("id")) for item in load_live_devices(LIVE_DEVICES_PATH).get("devices", [])}
                    unknown = requested - known
                    if unknown:
                        raise KeyError(f"设备不存在: {', '.join(sorted(unknown))}")
                    return self._json(service.stop_devices(requested))
                return self._json(service.stop_all())
            if method == "POST" and path == "/api/config/refresh":
                return self._json(service.poll_slow_group(str(body.get("deviceId") or "")))
            if method == "POST" and path == "/api/config/stage":
                return self._json(service.stage_config_value(str(body.get("deviceId") or ""), str(body.get("itemId") or ""), body.get("value")))
            if method == "POST" and path == "/api/config/schedule/select":
                return self._json(service.select_schedule_task(
                    str(body.get("deviceId") or ""), body.get("taskNumber"),
                ))
            if method == "POST" and path == "/api/config/schedule/mutate":
                return self._json(service.mutate_schedule_tasks(
                    str(body.get("deviceId") or ""), str(body.get("action") or ""),
                ))
            if method == "POST" and path == "/api/config/schedule/update":
                return self._json(service.stage_schedule_task(
                    str(body.get("deviceId") or ""), body,
                ))
            if method == "POST" and path == "/api/config/transaction":
                target_id = str(body.get("deviceId") or "")
                action = str(body.get("action") or "").strip().lower()
                pending_profile = service.get_pending_connection_profile(target_id) if action == "commit" else {}
                if pending_profile:
                    devices_payload = load_live_devices(LIVE_DEVICES_PATH)
                    target = _find_device(devices_payload, target_id)
                    if target is None:
                        raise KeyError(f"Device not found: {target_id}")
                    future_slave = int(pending_profile.get("slaveId", target.get("slaveId", 1)))
                    future_port = str(target.get("address") or "").upper()
                    if any(
                        str(item.get("id") or "") != target_id
                        and str(item.get("address") or "").upper() == future_port
                        and int(item.get("slaveId") or 1) == future_slave
                        for item in devices_payload.get("devices", [])
                    ):
                        raise ValueError("提交后的从站地址将与同串口其他设备冲突")
                    stage_pending_device_profile(LIVE_DEVICES_PATH, target_id, pending_profile)
                result = service.execute_config_transaction(target_id, action)
                profile = result.get("connectionProfile") if result.get("action") == "commit" else None
                if isinstance(profile, dict) and profile:
                    result["device"] = update_live_device(LIVE_DEVICES_PATH, target_id, profile)
                    clear_pending_device_profile(LIVE_DEVICES_PATH)
                elif action == "discard":
                    clear_pending_device_profile(LIVE_DEVICES_PATH)
                return self._json(result)
            if method == "POST" and path == "/api/system/rtc/sync":
                return self._json(service.sync_rtc_from_epoch(
                    str(body.get("deviceId") or ""), body.get("epoch"),
                ))
            if method == "POST" and path == "/api/control/write":
                return self._json(service.write_runtime_control(str(body.get("deviceId") or ""), str(body.get("itemId") or ""), body.get("value")))
            if method == "POST" and path == "/api/diagnostics/send-frame":
                devices_payload = load_live_devices(LIVE_DEVICES_PATH)
                device_id = str(body.get("deviceId") or devices_payload.get("selectedDeviceId") or "")
                device = _find_device(devices_payload, device_id)
                if device is None:
                    raise ValueError("未找到要发送报文的设备")
                timeout_ms = body.get("responseTimeoutMs")
                return self._json(service.send_debug_frame(
                    device,
                    str(body.get("requestHex") or ""),
                    append_crc_bytes=bool(body.get("appendCrc", True)),
                    expect_response=bool(body.get("expectResponse", True)),
                    response_timeout_ms=int(timeout_ms) if timeout_ms not in (None, "") else None,
                ))
            if method == "POST" and path == "/api/traffic/clear":
                return self._json(service.clear_command_traffic())
            if method == "POST" and path == "/api/session/export":
                return self._json(service.export_session(str(body.get("deviceId") or ""), Path(str(body.get("exportRoot") or BASE_DIR / "导出"))))
            self.send_error(HTTPStatus.NOT_FOUND, "API not found")
        except Exception as exc:
            self._error(exc)

    def _read_json(self) -> dict[str, Any]:
        content_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("请求 Content-Type 必须为 application/json")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ValueError("无效的 Content-Length") from exc
        if length > MAX_JSON_BODY_BYTES:
            raise ValueError("请求正文超过 1 MiB 限制")
        if length <= 0:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求正文必须是 JSON 对象")
        return payload

    def _validate_mutation_origin(self) -> None:
        origin = str(self.headers.get("Origin") or "").rstrip("/").lower()
        if not origin:
            return
        allowed = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
        if origin not in allowed:
            raise ValueError("已拒绝非本机页面发起的写操作")

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, exc: Exception) -> None:
        if isinstance(exc, KeyError):
            status = HTTPStatus.NOT_FOUND
        elif isinstance(exc, (ValueError, json.JSONDecodeError)):
            status = HTTPStatus.BAD_REQUEST
        elif isinstance(exc, ModbusError):
            status = HTTPStatus.BAD_GATEWAY
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self._json({"ok": False, "error": str(exc)}, status)

    @staticmethod
    def _query(query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key) or []
        return str(values[0]) if values else None

    @classmethod
    def _query_int(cls, query: dict[str, list[str]], key: str, default: int, minimum: int, maximum: int) -> int:
        raw = cls._query(query, key)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"查询参数 {key} 必须是整数") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"查询参数 {key} 必须在 {minimum} 到 {maximum} 之间")
        return value


def main() -> None:
    if not WEB_DIR.exists():
        raise SystemExit(f"Web 目录不存在: {WEB_DIR}")
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), DashboardRequestHandler)
    print(f"YLDQ 6.0 远程监控系统: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _service().stop_all()
        server.server_close()


if __name__ == "__main__":
    main()
