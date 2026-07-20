from __future__ import annotations

import atexit
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import traceback
import urllib.error
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

import dashboard_server


APP_TITLE = "YLDQ 分析系统"
APP_URL = f"http://{dashboard_server.HOST}:{dashboard_server.PORT}"
API_URL = f"{APP_URL}/api/analysis"

_shutting_down = False


def _cleanup_live_service() -> None:
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    try:
        from live_acquisition_service import get_live_acquisition_service

        svc = get_live_acquisition_service()
        svc.stop_all()
    except Exception:
        pass


def _signal_handler(signum: int, frame: object) -> None:
    _cleanup_live_service()
    sys.exit(0)


def _register_cleanup() -> None:
    atexit.register(_cleanup_live_service)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError):
            pass


def shutdown_system() -> None:
    _cleanup_live_service()
    os._exit(0)


def runtime_base_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def runtime_asset_dir(base_dir: Path) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", base_dir)).resolve()
    return Path(__file__).resolve().parent


def show_message(text: str, title: str = APP_TITLE, flags: int = 0) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception:
        print(f"{title}: {text}")


def ensure_runtime_layout(base_dir: Path, asset_dir: Path) -> None:
    web_dir = asset_dir / "web"
    if not web_dir.exists():
        raise FileNotFoundError(f"未找到 web 目录: {web_dir}")

    data_dir = base_dir / "实时数据"
    (data_dir / "data_0").mkdir(parents=True, exist_ok=True)
    (data_dir / "breath_data").mkdir(parents=True, exist_ok=True)
    (data_dir / "run").mkdir(parents=True, exist_ok=True)


def kill_port_owner(port: int) -> None:
    try:
        subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen -EA SilentlyContinue | Select -First 1;"
                f"if ($c) {{ Stop-Process -Id $c.OwningProcess -Force -EA SilentlyContinue }}",
            ],
            capture_output=True,
            timeout=8,
        )
    except Exception:
        pass


def dashboard_alive() -> bool:
    try:
        with urllib.request.urlopen(API_URL, timeout=2) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
            return isinstance(payload, dict) and "overview" in payload
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False


def open_browser() -> None:
    try:
        webbrowser.open(APP_URL)
    except Exception:
        pass


def serve_dashboard(base_dir: Path) -> None:
    asset_dir = runtime_asset_dir(base_dir)
    ensure_runtime_layout(base_dir, asset_dir)
    dashboard_server.set_runtime_base(base_dir, asset_base_dir=asset_dir)
    dashboard_server.load_analysis(force_refresh=True)
    server = ThreadingHTTPServer((dashboard_server.HOST, dashboard_server.PORT), dashboard_server.DashboardRequestHandler)
    threading.Timer(1.0, open_browser).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> int:
    base_dir = runtime_base_dir()
    try:
        _register_cleanup()
        kill_port_owner(dashboard_server.PORT)
        serve_dashboard(base_dir)
        return 0
    except Exception as exc:
        traceback.print_exc()
        show_message(
            "启动分析系统失败：\n\n"
            f"{exc}\n\n"
            f"程序目录：{base_dir}\n\n"
            "请确认实时数据目录和 web 资源完整。",
            flags=0x10,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
