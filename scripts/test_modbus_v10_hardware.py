"""连接实机核验 Modbus V10 四区、读写功能和持久化状态。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_modbus_client import LiveModbusClient, ModbusError


def wait_saved(client: LiveModbusClient, old_generation: int, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        busy, failed = client.read_discrete_inputs(49, 2)
        words = client.read_input_registers(114, 2)
        generation, error = words
        if failed or error not in {0, 5}:
            raise RuntimeError(f"配置保存失败: DI50={int(failed)}, IR115={error}")
        # 原值回写由固件直接接受，不重复落盘，此时代数允许不变。
        if not busy:
            return generation
        time.sleep(0.1)
    raise RuntimeError("配置保存超时，DI49未清零")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM7")
    parser.add_argument("--slave", type=int, default=1)
    args = parser.parse_args()
    point_map = json.loads((ROOT / "app" / "modbus_v10_point_map.json").read_text(encoding="utf-8"))
    by_area_address = {(x["area"], int(x["address"])): x for x in point_map["fields"]}
    device = {"address": args.port, "slaveId": args.slave, "baudrate": 9600, "parity": "N", "databits": 8, "stopbits": 1, "timeoutMs": 1200, "retryCount": 1}
    client = LiveModbusClient(device)
    passed: list[str] = []
    try:
        client.open()
        protocol = client.read_input_registers(100, 1)[0]
        assert protocol == 0x0A01, f"协议字错误: 0x{protocol:04X}"
        passed.append("协议字 IR100=0x0A01")

        mandatory_di = client.read_discrete_inputs(0, 20)
        mandatory_ir = client.read_input_registers(0, 8)
        assert len(mandatory_di) == 20 and len(mandatory_ir) == 8
        passed.append("必选 FC02 DI0..19 与 FC04 IR0..7")
        print("必选离散输入:")
        for address, value in enumerate(mandatory_di):
            field = by_area_address[("DI", address)]
            print(f"  DI{address:02d} {field['name']}: {int(value)} ({field['description']})")

        read_blocks = [
            (client.read_discrete_inputs, 32, 19, "DI32..50"),
            (client.read_discrete_inputs, 64, 22, "DI64..85"),
            (client.read_discrete_inputs, 96, 19, "DI96..114"),
            (client.read_input_registers, 16, 8, "IR16..23"),
            (client.read_input_registers, 32, 66, "IR32..97"),
            (client.read_input_registers, 100, 36, "IR100..135"),
            (client.read_coils, 0, 11, "COIL0..10"),
            (client.read_coils, 16, 14, "COIL16..29"),
            (client.read_coils, 32, 41, "COIL32..72"),
            (client.read_coils, 80, 2, "COIL80..81"),
            (client.read_coils, 96, 24, "COIL96..119"),
            (client.read_holding_registers, 0, 11, "HR0..10"),
            (client.read_holding_registers, 16, 2, "HR16..17"),
            (client.read_holding_registers, 100, 87, "HR100..186"),
            (client.read_holding_registers, 220, 83, "HR220..302"),
        ]
        for task in range(12):
            read_blocks.append((client.read_holding_registers, 512 + task * 32, 24, f"HR任务{task + 1}"))
        for reader, address, count, label in read_blocks:
            assert len(reader(address, count)) == count, label
        passed.append("四区全部文档点段读取")

        for base in (16, 18, 20, 24, 26, 28):
            pair = client.read_coils(base, 2)
            assert pair in ([False, False], [True, False], [True, True]), f"COIL{base}非法成对状态: {pair}"
        passed.append("六组成对控制状态合法")

        remote = client.read_coils(0, 1)[0]
        client.write_single_coil(0, remote)
        assert client.read_coils(0, 1)[0] == remote
        passed.append("FC05单线圈原值写入及回读")

        pair = client.read_coils(16, 2)
        client.write_multiple_coils(16, pair)
        assert client.read_coils(16, 2) == pair
        passed.append("FC0F成对线圈原值写入及回读")

        rejected = False
        try:
            client.write_single_coil(16, pair[0])
        except ModbusError:
            rejected = True
        assert rejected, "成对控制首位被FC05单独写入，协议保护失效"
        passed.append("FC05非法半对写入被拒绝")

        generation = client.read_input_registers(114, 1)[0]
        retention = client.read_holding_registers(10, 1)[0]
        client.write_single_register(10, retention)
        generation = wait_saved(client, generation)
        assert client.read_holding_registers(10, 1)[0] == retention
        passed.append("FC06配置原值写入接受及回读")

        interval = client.read_holding_registers(8, 2)
        client.write_multiple_registers(8, interval)
        wait_saved(client, generation)
        assert client.read_holding_registers(8, 2) == interval
        passed.append("FC10多寄存器原值写入接受及回读")

        unix_seconds = int(time.time())
        client.write_multiple_registers(16, [unix_seconds >> 16, unix_seconds & 0xFFFF])
        rtc_words = client.read_holding_registers(16, 2)
        rtc_seconds = (rtc_words[0] << 16) | rtc_words[1]
        assert 0 <= rtc_seconds - unix_seconds <= 3, (
            f"Unix校时回读偏差异常: 写入{unix_seconds}，回读{rtc_seconds}"
        )
        passed.append("HR16 Unix UTC校时写入回读")

        rejected = False
        try:
            client.write_single_register(512, client.read_holding_registers(512, 1)[0])
        except ModbusError:
            rejected = True
        assert rejected, "任务槽允许FC06单字段写入，整槽保护失效"
        passed.append("任务槽FC06单字段写入被拒绝")

        print("\n通过项目:")
        for text in passed:
            print(f"  PASS {text}")
        print(f"\nRESULT PASS {len(passed)}/{len(passed)}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
