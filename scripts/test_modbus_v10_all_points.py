"""逐点核验V10点表；配置点原值回写，代表点改值后恢复，脉冲点逐个触发。"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from live_modbus_client import LiveModbusClient, ModbusError

PORT = "COM7"
SLAVE = 1
REPORT = ROOT / "test_results" / "modbus_v10_all_points.csv"


def main() -> int:
    fields = json.loads((ROOT / "app" / "modbus_v10_point_map.json").read_text(encoding="utf-8"))["fields"]
    client = LiveModbusClient({"address": PORT, "slaveId": SLAVE, "baudrate": 9600, "parity": "N", "databits": 8, "stopbits": 1, "timeoutMs": 1500, "retryCount": 2})
    rows: list[dict[str, object]] = []
    retry_total = 0

    def request(label, fn):
        nonlocal retry_total
        last = None
        for attempt in range(1, 7):
            try:
                value = fn()
                if attempt > 1:
                    retry_total += attempt - 1
                return value
            except Exception as exc:
                last = exc
                client.close()
                time.sleep(0.2 * attempt)
        raise RuntimeError(f"{label}连续失败: {last}") from last

    def read_field(field):
        area, address, count = field["area"], int(field["address"]), int(field["count"])
        reader = {"DI": client.read_discrete_inputs, "IR": client.read_input_registers, "COIL": client.read_coils, "HR": client.read_holding_registers}[area]
        return request(f"读取{area}{address}", lambda: reader(address, count))

    def wait_ready():
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                busy, failed = request("读取保存状态", lambda: client.read_discrete_inputs(49, 2))
                error = request("读取保存错误", lambda: client.read_input_registers(115, 1))[0]
                if failed or error not in {0, 5}:
                    diagnostic = request("读取持久化诊断", lambda: client.read_input_registers(136, 1))[0]
                    raise RuntimeError(
                        f"保存失败 DI50={int(failed)} IR115={error} IR136={diagnostic}"
                    )
                if not busy:
                    return
            except ModbusError:
                pass
            time.sleep(0.12)
        raise RuntimeError("配置保存25秒未完成")

    def record(field, operation, status, detail=""):
        rows.append({"区域": field["area"], "地址": field["address"], "数量": field["count"], "名称": field["name"], "权限": field["access"], "操作": operation, "结果": status, "说明": detail})

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    try:
        protocol = request("协议字", lambda: client.read_input_registers(100, 1))[0]
        if protocol != 0x0A00:
            raise RuntimeError(f"协议字错误 0x{protocol:04X}")

        print(f"开始逐点读取，共{len(fields)}个物理点定义", flush=True)
        originals = {}
        for index, field in enumerate(fields, 1):
            try:
                value = read_field(field)
                originals[(field["area"], int(field["address"]))] = list(value)
                record(field, "读取", "PASS", str(value))
            except Exception as exc:
                record(field, "读取", "FAIL", str(exc))
            if index % 50 == 0:
                print(f"读取进度 {index}/{len(fields)}", flush=True)

        writable = [x for x in fields if x["access"] != "R"]
        print(f"开始逐点写入回读，共{len(writable)}个可写物理点定义", flush=True)
        pair_done: set[int] = set()
        reset_field = None
        for index, field in enumerate(writable, 1):
            area, address, count, access = field["area"], int(field["address"]), int(field["count"]), field["access"]
            try:
                if access == "PAIR":
                    base = address if address % 2 == 0 else address - 1
                    if base in pair_done:
                        record(field, "成对写入", "PASS", f"随COIL{base}完整写入")
                        continue
                    pair_done.add(base)
                    original = request("读取成对线圈", lambda b=base: client.read_coils(b, 2))
                    request("FC0F成对写入", lambda b=base, v=original: client.write_multiple_coils(b, v))
                    actual = request("回读成对线圈", lambda b=base: client.read_coils(b, 2))
                    if actual != original:
                        raise RuntimeError(f"回读{actual} != 写入{original}")
                    record(field, "FC0F原值写入回读", "PASS", str(actual))
                elif access == "PULSE":
                    if address == 1:
                        reset_field = field
                        continue
                    if 8 <= address <= 10:
                        enabled = request(
                            "读取阀使能",
                            lambda a=48 + address - 8: client.read_coils(a, 1)[0],
                        )
                        if not enabled:
                            try:
                                client.write_single_coil(address, True)
                            except ModbusError:
                                record(field, "FC05写1触发", "PASS", "阀已禁用，命令被保护性拒绝")
                                continue
                            raise RuntimeError("阀已禁用但校准命令未被拒绝")
                    request("FC05脉冲", lambda a=address: client.write_single_coil(a, True))
                    actual = request("脉冲回读", lambda a=address: client.read_coils(a, 1))[0]
                    if actual:
                        raise RuntimeError("脉冲位未自动清零")
                    if 8 <= address <= 10:
                        status_address = 104 + (address - 8) * 4
                        deadline = time.monotonic() + 180
                        while time.monotonic() < deadline:
                            active, passed, failed = request(
                                "读取阀校准状态",
                                lambda a=status_address: client.read_discrete_inputs(a, 3),
                            )
                            if not active:
                                if failed:
                                    raise RuntimeError("阀回原点校准完成但结果失败")
                                break
                            time.sleep(0.5)
                        else:
                            raise RuntimeError("阀回原点校准180秒未结束")
                    record(field, "FC05写1触发", "PASS", "读回0")
                elif area == "COIL":
                    original = originals[(area, address)][0]
                    request("FC05线圈写入", lambda a=address, v=original: client.write_single_coil(a, v))
                    actual = request("线圈回读", lambda a=address: client.read_coils(a, 1))[0]
                    if actual != original:
                        raise RuntimeError(f"回读{actual} != 写入{original}")
                    if access == "CONFIG": wait_ready()
                    record(field, "FC05原值写入回读", "PASS", str(actual))
                elif area == "HR":
                    if 512 <= address < 896:
                        # 任务寄存器只能按24字完整槽写入，统一在本循环后核验。
                        continue
                    original = originals[(area, address)]
                    if access == "COMMAND":
                        written_seconds = int(time.time())
                        words = [(written_seconds >> 16) & 0xFFFF, written_seconds & 0xFFFF]
                        request("FC10设备校时", lambda a=address, v=words: client.write_multiple_registers(a, v))
                        actual = request("设备时间回读", lambda a=address: client.read_holding_registers(a, 2))
                        actual_seconds = (int(actual[0]) << 16) | int(actual[1])
                        if not 0 <= actual_seconds - written_seconds <= 3:
                            raise RuntimeError(f"校时后走时差异常: 写入{written_seconds}，回读{actual_seconds}")
                    else:
                        if count == 1:
                            request("FC06寄存器写入", lambda a=address, v=original[0]: client.write_single_register(a, v))
                        else:
                            request("FC10寄存器写入", lambda a=address, v=original: client.write_multiple_registers(a, v))
                        actual = request("保持寄存器回读", lambda a=address, n=count: client.read_holding_registers(a, n))
                        if actual != original:
                            raise RuntimeError(f"回读{actual} != 写入{original}")
                    if access == "CONFIG": wait_ready()
                    record(field, "FC06原值写入回读" if count == 1 else "FC10原值写入回读", "PASS", str(actual))
            except Exception as exc:
                record(field, "写入回读", "FAIL", str(exc))
            if index % 25 == 0:
                print(f"写入进度 {index}/{len(writable)}", flush=True)

        print("按完整槽写入12条定时任务", flush=True)
        for slot in range(12):
            base = 512 + slot * 32
            slot_fields = [
                x for x in writable
                if x["area"] == "HR" and base <= int(x["address"]) < base + 24
            ]
            try:
                original = request("读取任务槽", lambda b=base: client.read_holding_registers(b, 24))
                request("FC10任务整槽写入", lambda b=base, v=original: client.write_multiple_registers(b, v))
                wait_ready()
                actual = request("回读任务槽", lambda b=base: client.read_holding_registers(b, 24))
                if actual != original:
                    raise RuntimeError(f"任务槽回读不一致: {actual} != {original}")
                for field in slot_fields:
                    record(field, "FC10任务整槽写入回读", "PASS", f"HR{base}起连续24字")
            except Exception as exc:
                for field in slot_fields:
                    record(field, "FC10任务整槽写入回读", "FAIL", str(exc))

        print("执行代表点改值并恢复", flush=True)
        # 远程请求翻转后恢复。
        remote = bool(originals[("COIL", 0)][0])
        request("远程加热改值", lambda: client.write_single_coil(0, not remote))
        if request("远程加热改值回读", lambda: client.read_coils(0, 1))[0] != (not remote): raise RuntimeError("远程加热改值失败")
        request("远程加热恢复", lambda: client.write_single_coil(0, remote))

        # 日志使能翻转并恢复，验证配置线圈真实改值路径。
        logging_enabled = bool(originals[("COIL", 80)][0])
        request("日志使能改值", lambda: client.write_single_coil(80, not logging_enabled)); wait_ready()
        request("日志使能恢复", lambda: client.write_single_coil(80, logging_enabled)); wait_ready()

        # U16和F32各取一个配置点真实改值后恢复。
        retention = originals[("HR", 10)][0]
        retention_test = retention + 1 if retention < 3650 else retention - 1
        request("日志天数改值", lambda: client.write_single_register(10, retention_test)); wait_ready()
        if request("日志天数回读", lambda: client.read_holding_registers(10, 1))[0] != retention_test: raise RuntimeError("日志天数改值失败")
        request("日志天数恢复", lambda: client.write_single_register(10, retention)); wait_ready()

        offset_words = originals[("HR", 100)]
        offset = struct.unpack(">f", struct.pack(">2H", *offset_words))[0]
        test_words = list(struct.unpack(">2H", struct.pack(">f", round(offset + 0.10, 2))))
        request("T1温偏改值", lambda: client.write_multiple_registers(100, test_words)); wait_ready()
        if request("T1温偏回读", lambda: client.read_holding_registers(100, 2)) != test_words: raise RuntimeError("T1温偏改值失败")
        request("T1温偏恢复", lambda: client.write_multiple_registers(100, offset_words)); wait_ready()

        if reset_field is not None:
            print("执行软件复位点并等待设备恢复", flush=True)
            request("软件复位", lambda: client.write_single_coil(1, True))
            client.close()
            deadline = time.monotonic() + 90
            recovered = False
            while time.monotonic() < deadline:
                try:
                    time.sleep(1)
                    if request("复位后协议字", lambda: client.read_input_registers(100, 1))[0] == 0x0A00:
                        recovered = True
                        break
                except Exception:
                    continue
            record(reset_field, "FC05软件复位", "PASS" if recovered else "FAIL", "复位后重新连通" if recovered else "90秒未恢复")

    finally:
        client.close()
        with REPORT.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["区域", "地址", "数量", "名称", "权限", "操作", "结果", "说明"])
            writer.writeheader(); writer.writerows(rows)

    failed = [x for x in rows if x["结果"] != "PASS"]
    print(f"RESULT 总记录{len(rows)} PASS={len(rows)-len(failed)} FAIL={len(failed)} 通信重试={retry_total}", flush=True)
    for row in failed[:30]: print("FAIL", row, flush=True)
    print(f"报告: {REPORT}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
