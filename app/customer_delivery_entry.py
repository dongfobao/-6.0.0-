from __future__ import annotations

import argparse
import ctypes
import sys
import traceback
import webbrowser
from pathlib import Path

import dashboard_server


APP_TITLE = "YLDQ 数据分析客户交付版"


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


def ensure_required_paths(base_dir: Path, asset_dir: Path) -> None:
    data_dir = base_dir / "实时数据"
    web_dir = asset_dir / "web"
    if not web_dir.exists():
        raise FileNotFoundError(f"未找到 web 目录：{web_dir}")
    if not data_dir.exists():
        raise FileNotFoundError(
            "未找到“实时数据”目录。\n\n"
            "请把 config.json、data_0、breath_data、run 放到程序同目录下的 实时数据 文件夹内。"
        )


def build_customer_report(base_dir: Path, open_report: bool = True) -> dict[str, Path]:
    asset_dir = runtime_asset_dir(base_dir)
    dashboard_server.set_runtime_base(base_dir, asset_base_dir=asset_dir)
    ensure_required_paths(base_dir, asset_dir)
    output_dir = base_dir / "output"
    analysis = dashboard_server.load_analysis(force_refresh=True)
    outputs = dashboard_server.write_customer_outputs(output_dir, analysis)
    if open_report:
        webbrowser.open(outputs["report"].resolve().as_uri())
    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 YLDQ 客户交付版分析报告")
    parser.add_argument("--no-open", action="store_true", help="只生成文件，不自动打开报告")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = runtime_base_dir()
    try:
        outputs = build_customer_report(base_dir, open_report=not args.no_open)
        print(f"报告已生成：{outputs['report']}")
        print(f"摘要已生成：{outputs['summary']}")
        print(f"JSON 已生成：{outputs['json']}")
        return 0
    except Exception as exc:
        error_text = (
            f"生成客户报告失败：{exc}\n\n"
            f"程序目录：{base_dir}\n\n"
            "如果是给客户使用，请确认：\n"
            "1. 程序目录下存在 实时数据 文件夹\n"
            "2. 实时数据 内含 config.json、data_0、breath_data、run\n"
            "3. 数据文件未被占用\n"
        )
        traceback.print_exc()
        show_message(error_text, flags=0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
