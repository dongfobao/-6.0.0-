"""YLDQ 6.0 远程监控 HTTP 服务。"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from live_device_store import (
    create_live_device,
    delete_live_device,
    load_live_devices,
    select_live_device,
    update_live_device,
)
from live_polling_commands import build_default_polling_commands
from live_register_catalog import get_register_catalog, get_register_catalog_summary
from monitoring_projection import build_monitoring_snapshot


APP_DIR = Path(__file__).resolve().parent
BASE_DIR = APP_DIR.parent
WEB_DIR = APP_DIR / "web"
LIVE_DEVICES_PATH = BASE_DIR / "live_devices.json"
SESSIONS_DIR = BASE_DIR / "实时采集会话"
HOST = "127.0.0.1"
PORT = 8765


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
    return {
        "app": {"name": "YLDQ 6.0 远程监控系统", "version": "6.0.0", "protocol": "Modbus V7", "protocolWord": "0x0700"},
        "devices": devices,
        "serialPorts": _serial_ports(),
        "catalogSummary": get_register_catalog_summary(),
        "pollingPlan": build_default_polling_commands(),
        "acquisition": service.get_status(),
        "deviceStatuses": service.get_device_status(),
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
        if path == "/api/health":
            return self._json({"ok": True, "service": "YLDQ 6.0 monitor", "protocol": "7.0"})
        if path == "/api/bootstrap":
            return self._json(build_bootstrap_payload())
        if path == "/api/devices":
            return self._json(load_live_devices(LIVE_DEVICES_PATH))
        if path == "/api/catalog":
            return self._json({"summary": get_register_catalog_summary(), "items": get_register_catalog()})
        if path == "/api/acquisition/status":
            return self._json({"global": service.get_status(), "devices": service.get_device_status()})
        if path == "/api/monitor/snapshot":
            devices = load_live_devices(LIVE_DEVICES_PATH)
            device_id = device_id or devices.get("selectedDeviceId")
            raw = service.get_snapshot(device_id)
            return self._json(build_monitoring_snapshot(raw, _find_device(devices, device_id)))
        if path == "/api/monitor/series":
            window_ms = self._query_int(query, "windowMs", 900000, 10000, 86400000)
            limit = self._query_int(query, "limit", 600, 10, 2000)
            return self._json(service.get_series(
                device_id,
                window_ms=window_ms,
                limit=limit,
                start_at=self._query(query, "start"),
                end_at=self._query(query, "end"),
            ))
        if path == "/api/monitor/events":
            return self._json({"items": service.get_events(device_id, self._query_int(query, "limit", 100, 1, 240))})
        if path == "/api/monitor/traffic":
            return self._json({"items": service.get_command_traffic(device_id, self._query_int(query, "limit", 120, 1, 1000))})
        if path == "/api/config/parameters":
            return self._json(service.get_parameters(device_id))
        if path == "/api/session/meta":
            return self._json(service.get_session_meta(device_id))
        self.send_error(HTTPStatus.NOT_FOUND, "API not found")

    def _handle_mutation(self, method: str) -> None:
        parsed = urlparse(self.path)
        try:
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
                    return self._json(update_live_device(LIVE_DEVICES_PATH, suffix, body))
                if method == "DELETE":
                    return self._json(delete_live_device(LIVE_DEVICES_PATH, suffix))
            if method == "POST" and path == "/api/acquisition/start":
                devices_payload = load_live_devices(LIVE_DEVICES_PATH)
                requested = {str(value) for value in body.get("deviceIds", []) if str(value)}
                if not requested and devices_payload.get("selectedDeviceId"):
                    requested = {str(devices_payload["selectedDeviceId"])}
                devices = [item for item in devices_payload.get("devices", []) if not requested or item.get("id") in requested]
                return self._json(service.start_all(devices, session_root=SESSIONS_DIR, config_snapshot={"protocol": "7.0"}))
            if method == "POST" and path == "/api/acquisition/stop":
                return self._json(service.stop_all())
            if method == "POST" and path == "/api/config/refresh":
                return self._json(service.poll_slow_group(str(body.get("deviceId") or "")))
            if method == "POST" and path == "/api/config/stage":
                return self._json(service.stage_config_value(str(body.get("deviceId") or ""), str(body.get("itemId") or ""), body.get("value")))
            if method == "POST" and path == "/api/config/transaction":
                return self._json(service.execute_config_transaction(str(body.get("deviceId") or ""), str(body.get("action") or "")))
            if method == "POST" and path == "/api/control/write":
                return self._json(service.write_runtime_control(str(body.get("deviceId") or ""), str(body.get("itemId") or ""), body.get("value")))
            if method == "POST" and path == "/api/traffic/clear":
                return self._json(service.clear_command_traffic())
            if method == "POST" and path == "/api/session/export":
                return self._json(service.export_session(str(body.get("deviceId") or ""), Path(str(body.get("exportRoot") or BASE_DIR / "导出"))))
            self.send_error(HTTPStatus.NOT_FOUND, "API not found")
        except Exception as exc:
            self._error(exc)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求正文必须是 JSON 对象")
        return payload

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, exc: Exception) -> None:
        status = HTTPStatus.NOT_FOUND if isinstance(exc, KeyError) else HTTPStatus.BAD_REQUEST
        self._json({"ok": False, "error": str(exc)}, status)

    @staticmethod
    def _query(query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key) or []
        return str(values[0]) if values else None

    @classmethod
    def _query_int(cls, query: dict[str, list[str]], key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(cls._query(query, key) or default)
        except ValueError:
            value = default
        return max(minimum, min(maximum, value))


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
