"""补测配置真实改值/恢复及软件复位，并补齐逐点报告。"""
from __future__ import annotations

import csv
import ast
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_modbus_client import LiveModbusClient

REPORT = ROOT / "test_results" / "modbus_v10_all_points.csv"


def new_client() -> LiveModbusClient:
    return LiveModbusClient({
        "address": "COM7", "slaveId": 1, "baudrate": 9600,
        "parity": "N", "databits": 8, "stopbits": 1,
        "timeoutMs": 1500, "retryCount": 2,
    })


def wait_ready(client: LiveModbusClient) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        busy, failed = client.read_discrete_inputs(49, 2)
        error = client.read_input_registers(115, 1)[0]
        diagnostic = client.read_input_registers(136, 1)[0]
        print(f"保存 busy={int(busy)} failed={int(failed)} error={error} diagnostic={diagnostic}")
        if failed or error not in (0, 5):
            raise RuntimeError(f"保存失败 error={error} diagnostic={diagnostic}")
        if not busy:
            return
        time.sleep(0.2)
    raise RuntimeError("保存超时")


def main() -> int:
    client = new_client()
    try:
        if client.read_input_registers(100, 1)[0] != 0x0A00:
            raise RuntimeError("协议字不匹配")

        logging_enabled = client.read_coils(80, 1)[0]
        client.write_single_coil(80, not logging_enabled)
        wait_ready(client)
        client.write_single_coil(80, logging_enabled)
        wait_ready(client)

        retention = client.read_holding_registers(10, 1)[0]
        retention_test = retention + 1 if retention < 3650 else retention - 1
        client.write_single_register(10, retention_test)
        wait_ready(client)
        if client.read_holding_registers(10, 1)[0] != retention_test:
            raise RuntimeError("日志保留天数改值回读失败")
        client.write_single_register(10, retention)
        wait_ready(client)

        report_rows = list(csv.DictReader(REPORT.open(encoding="utf-8-sig")))
        offset_row = next(
            r for r in report_rows
            if r["区域"] == "HR" and r["地址"] == "100" and r["操作"] == "读取"
        )
        offset_words = [int(v) for v in ast.literal_eval(offset_row["说明"])]
        offset = struct.unpack(">f", struct.pack(">2H", *offset_words))[0]
        test_words = list(struct.unpack(">2H", struct.pack(">f", round(offset + 0.10, 2))))
        client.write_multiple_registers(100, test_words)
        wait_ready(client)
        if client.read_holding_registers(100, 2) != test_words:
            raise RuntimeError("T1温偏改值回读失败")
        client.write_multiple_registers(100, offset_words)
        wait_ready(client)

        client.write_single_coil(1, True)
        client.close()
        recovered = False
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            time.sleep(1)
            try:
                client = new_client()
                if client.read_input_registers(100, 1)[0] == 0x0A00:
                    recovered = True
                    break
            except Exception:
                client.close()
        if not recovered:
            raise RuntimeError("软件复位后90秒未恢复通信")

        rows = list(csv.DictReader(REPORT.open(encoding="utf-8-sig")))
        rows = [
            r for r in rows
            if not (
                r["区域"] == "COIL" and r["地址"] == "1" and
                r["操作"] == "FC05软件复位"
            )
        ]
        rows.append({
            "区域": "COIL", "地址": "1", "数量": "1", "名称": "设备复位",
            "权限": "PULSE", "操作": "FC05软件复位", "结果": "PASS",
            "说明": "复位后重新连通",
        })
        with REPORT.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "区域", "地址", "数量", "名称", "权限", "操作", "结果", "说明"
            ])
            writer.writeheader()
            writer.writerows(rows)
        print(f"补测通过，报告记录={len(rows)}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
