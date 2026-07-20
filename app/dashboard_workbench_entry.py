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
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

import dashboard_server


APP_TITLE = "YLDQ 6.0 远程监控系统"
APP_URL = f"http://{dashboard_server.HOST}:{dashboard_server.PORT}"
HEALTH_URL = f"{APP_URL}/api/health"
_shutting_down = False


def runtime_base_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def runtime_asset_dir(base_dir: Path) -> Path:
    return Path(getattr(sys, "_MEIPASS", base_dir)).resolve() if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def _cleanup() -> None:
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    try:
        from live_acquisition_service import get_live_acquisition_service
        get_live_acquisition_service().stop_all()
    except Exception:
        pass


def _register_cleanup() -> None:
    atexit.register(_cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: (_cleanup(), sys.exit(0)))
        except (ValueError, OSError):
            pass


def _message(text: str, flags: int = 0) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, APP_TITLE, flags)
    except Exception:
        print(text)


def _kill_port_owner(port: int) -> None:
    try:
        subprocess.run([
            "powershell", "-NoProfile", "-Command",
            f"$c=Get-NetTCPConnection -LocalPort {port} -State Listen -EA SilentlyContinue|Select -First 1;if($c){{Stop-Process -Id $c.OwningProcess -Force -EA SilentlyContinue}}",
        ], capture_output=True, timeout=8)
    except Exception:
        pass


def _open_browser_when_ready() -> None:
    for _ in range(30):
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("ok"):
                    webbrowser.open(APP_URL)
                    return
        except Exception:
            threading.Event().wait(0.25)


def main() -> int:
    base_dir = runtime_base_dir()
    try:
        _register_cleanup()
        asset_dir = runtime_asset_dir(base_dir)
        if not (asset_dir / "web").exists():
            raise FileNotFoundError(f"未找到 web 目录: {asset_dir / 'web'}")
        dashboard_server.set_runtime_base(base_dir, asset_base_dir=asset_dir)
        _kill_port_owner(dashboard_server.PORT)
        server = ThreadingHTTPServer((dashboard_server.HOST, dashboard_server.PORT), dashboard_server.DashboardRequestHandler)
        threading.Thread(target=_open_browser_when_ready, daemon=True).start()
        try:
            server.serve_forever()
        finally:
            server.server_close()
            _cleanup()
        return 0
    except Exception as exc:
        traceback.print_exc()
        _message(f"启动失败：\n\n{exc}\n\n程序目录：{base_dir}", flags=0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
