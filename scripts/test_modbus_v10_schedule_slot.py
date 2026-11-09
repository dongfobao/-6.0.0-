"""仅验证V10定时任务整槽写入与持久化诊断，不操作任何输出。"""
from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_modbus_client import LiveModbusClient


def main() -> int:
    client = LiveModbusClient({
        "address": "COM7", "slaveId": 1, "baudrate": 9600,
        "parity": "N", "databits": 8, "stopbits": 1,
        "timeoutMs": 1500, "retryCount": 2,
    })
    try:
        protocol = client.read_input_registers(100, 1)[0]
        print(f"协议字=0x{protocol:04X}")
        if protocol != 0x0A01:
            raise RuntimeError("协议字不匹配")

        base = 864
        original = client.read_holding_registers(base, 24)
        print(f"HR{base}原值={original}")
        client.write_multiple_registers(base, original)

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            busy, failed = client.read_discrete_inputs(49, 2)
            error = client.read_input_registers(115, 1)[0]
            diagnostic = client.read_input_registers(136, 1)[0]
            print(
                f"保存状态 busy={int(busy)} failed={int(failed)} "
                f"error={error} diagnostic={diagnostic}"
            )
            if failed or error not in (0, 5):
                return 1
            if not busy:
                actual = client.read_holding_registers(base, 24)
                print(f"HR{base}回读={actual}")
                return 0 if actual == original else 2
            time.sleep(0.2)
        print("保存超时")
        return 3
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
