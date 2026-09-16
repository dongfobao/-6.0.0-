"""32 位 libiec61850 客户端工作进程。

一行输入一个 JSON 命令，一行输出一个 JSON 事件。该进程由上位机后台监管，
每个进程只维护一台设备连接，避免协议栈异常影响主服务或其他设备。
"""

from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from ctypes import POINTER, byref, c_bool, c_char_p, c_float, c_int, c_uint16, c_uint32, c_uint64, c_void_p
from pathlib import Path
from typing import Any


FC_VALUES = {
    "ST": 0, "MX": 1, "SP": 2, "SV": 3, "CF": 4, "DC": 5,
    "SG": 6, "SE": 7, "SR": 8, "OR": 9, "BL": 10, "EX": 11,
    "CO": 12, "US": 13, "MS": 14, "RP": 15, "BR": 16, "LG": 17,
    "GO": 18,
}
RCB_ELEMENT_RPT_ENA = 2
RCB_ELEMENT_RESV = 4
RCB_ELEMENT_INTG_PD = 512

_write_lock = threading.Lock()


def emit(payload: dict[str, Any]) -> None:
    payload.setdefault("at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with _write_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


class NativeClient:
    def __init__(self) -> None:
        dll_path = Path(sys.executable).resolve().parent / "iec61850.dll"
        if not dll_path.exists():
            raise FileNotFoundError(f"未找到 IEC61850 DLL: {dll_path}")
        self.dll = ctypes.CDLL(str(dll_path))
        self.connection: int | None = None
        self.host = ""
        self.port = 102
        self.rcbs: dict[str, int] = {}
        self.callbacks: dict[str, Any] = {}
        self._configure_api()

    def _fn(self, name: str, restype: Any, argtypes: list[Any]) -> Any:
        function = getattr(self.dll, name)
        function.restype = restype
        function.argtypes = argtypes
        return function

    def _configure_api(self) -> None:
        self.create = self._fn("IedConnection_create", c_void_p, [])
        self.connect_native = self._fn("IedConnection_connect", None, [c_void_p, POINTER(c_int), c_char_p, c_int])
        self.close = self._fn("IedConnection_close", None, [c_void_p])
        self.destroy = self._fn("IedConnection_destroy", None, [c_void_p])
        self.get_state = self._fn("IedConnection_getState", c_int, [c_void_p])
        self.get_ld_list = self._fn("IedConnection_getLogicalDeviceList", c_void_p, [c_void_p, POINTER(c_int)])
        self.get_ld_dir = self._fn("IedConnection_getLogicalDeviceDirectory", c_void_p, [c_void_p, POINTER(c_int), c_char_p])
        self.get_ln_dir = self._fn("IedConnection_getLogicalNodeDirectory", c_void_p, [c_void_p, POINTER(c_int), c_char_p, c_int])
        self.list_next = self._fn("LinkedList_getNext", c_void_p, [c_void_p])
        self.list_data = self._fn("LinkedList_getData", c_void_p, [c_void_p])
        self.list_destroy = self._fn("LinkedList_destroy", None, [c_void_p])
        self.read_object = self._fn("IedConnection_readObject", c_void_p, [c_void_p, POINTER(c_int), c_char_p, c_int])
        self.value_type = self._fn("MmsValue_getType", c_int, [c_void_p])
        self.value_print = self._fn("MmsValue_printToBuffer", None, [c_void_p, c_char_p, c_int])
        self.value_delete = self._fn("MmsValue_delete", None, [c_void_p])
        self.value_array_size = self._fn("MmsValue_getArraySize", c_int, [c_void_p])
        self.value_element = self._fn("MmsValue_getElement", c_void_p, [c_void_p, c_int])
        self.value_float = self._fn("MmsValue_toFloat", c_float, [c_void_p])
        self.value_int = self._fn("MmsValue_toInt64", ctypes.c_int64, [c_void_p])
        self.value_uint = self._fn("MmsValue_toUint32", c_uint32, [c_void_p])
        self.value_bool = self._fn("MmsValue_getBoolean", c_bool, [c_void_p])
        self.get_rcb = self._fn("IedConnection_getRCBValues", c_void_p, [c_void_p, POINTER(c_int), c_char_p, c_void_p])
        self.set_rcb = self._fn("IedConnection_setRCBValues", None, [c_void_p, POINTER(c_int), c_void_p, c_uint32, c_bool])
        self.destroy_rcb = self._fn("ClientReportControlBlock_destroy", None, [c_void_p])
        self.rcb_get_rpt_id = self._fn("ClientReportControlBlock_getRptId", c_char_p, [c_void_p])
        self.rcb_get_dataset = self._fn("ClientReportControlBlock_getDataSetReference", c_char_p, [c_void_p])
        self.rcb_get_enabled = self._fn("ClientReportControlBlock_getRptEna", c_bool, [c_void_p])
        self.rcb_set_enabled = self._fn("ClientReportControlBlock_setRptEna", None, [c_void_p, c_bool])
        self.rcb_set_reserved = self._fn("ClientReportControlBlock_setResv", None, [c_void_p, c_bool])
        self.rcb_set_intg_pd = self._fn("ClientReportControlBlock_setIntgPd", None, [c_void_p, c_uint32])
        self.report_cb_type = ctypes.CFUNCTYPE(None, c_void_p, c_void_p)
        self.install_report = self._fn("IedConnection_installReportHandler", None, [c_void_p, c_char_p, c_char_p, self.report_cb_type, c_void_p])
        self.uninstall_report = self._fn("IedConnection_uninstallReportHandler", None, [c_void_p, c_char_p])
        self.report_rcb_ref = self._fn("ClientReport_getRcbReference", c_char_p, [c_void_p])
        self.report_rpt_id = self._fn("ClientReport_getRptId", c_char_p, [c_void_p])
        self.report_values = self._fn("ClientReport_getDataSetValues", c_void_p, [c_void_p])
        self.report_reason = self._fn("ClientReport_getReasonForInclusion", c_int, [c_void_p, c_int])
        self.report_has_seq = self._fn("ClientReport_hasSeqNum", c_bool, [c_void_p])
        self.report_seq = self._fn("ClientReport_getSeqNum", c_uint16, [c_void_p])
        self.report_has_timestamp = self._fn("ClientReport_hasTimestamp", c_bool, [c_void_p])
        self.report_timestamp = self._fn("ClientReport_getTimestamp", c_uint64, [c_void_p])

    @staticmethod
    def _decode(value: bytes | None) -> str:
        return value.decode("utf-8", errors="replace") if value else ""

    def _list_strings(self, linked_list: int | None) -> list[str]:
        values: list[str] = []
        if not linked_list:
            return values
        try:
            item = self.list_next(linked_list)
            while item:
                data = self.list_data(item)
                if data:
                    values.append(ctypes.string_at(data).decode("utf-8", errors="replace"))
                item = self.list_next(item)
        finally:
            self.list_destroy(linked_list)
        return values

    def connect(self, host: str, port: int) -> dict[str, Any]:
        self.disconnect()
        connection = self.create()
        if not connection:
            raise RuntimeError("IedConnection_create 失败")
        error = c_int()
        self.connect_native(connection, byref(error), host.encode("ascii"), int(port))
        if error.value != 0:
            self.destroy(connection)
            raise RuntimeError(f"MMS关联失败，IedClientError={error.value}")
        self.connection = int(connection)
        self.host = host
        self.port = int(port)
        return {"host": host, "port": port, "state": self.get_state(connection)}

    def browse(self) -> dict[str, Any]:
        connection = self._required_connection()
        error = c_int()
        logical_devices = self._list_strings(self.get_ld_list(connection, byref(error)))
        if error.value != 0:
            raise RuntimeError(f"读取逻辑设备失败，IedClientError={error.value}")
        result: list[dict[str, Any]] = []
        for logical_device in logical_devices:
            logical_nodes = self._list_strings(self.get_ld_dir(connection, byref(error), logical_device.encode()))
            if error.value != 0:
                raise RuntimeError(f"读取 {logical_device} 目录失败，IedClientError={error.value}")
            node_items: list[dict[str, Any]] = []
            for logical_node in logical_nodes:
                reference = f"{logical_device}/{logical_node}".encode()
                datasets = self._list_strings(self.get_ln_dir(connection, byref(error), reference, 1))
                node_items.append({"name": logical_node, "datasets": datasets})
            result.append({"name": logical_device, "logicalNodes": node_items})
        return {"logicalDevices": result}

    def read(self, reference: str, fc: str) -> dict[str, Any]:
        connection = self._required_connection()
        error = c_int()
        value_ptr = self.read_object(connection, byref(error), reference.encode("utf-8"), FC_VALUES.get(fc, 99))
        if error.value != 0 or not value_ptr:
            return {"reference": reference, "fc": fc, "ok": False, "error": error.value}
        try:
            return {"reference": reference, "fc": fc, "ok": True, **self._value_payload(value_ptr)}
        finally:
            self.value_delete(value_ptr)

    def _value_payload(self, value_ptr: int) -> dict[str, Any]:
        value_type = self.value_type(value_ptr)
        text_buffer = ctypes.create_string_buffer(1024)
        self.value_print(value_ptr, text_buffer, len(text_buffer))
        text = text_buffer.value.decode("utf-8", errors="replace")
        value: Any = text
        try:
            if value_type == 6:
                value = float(self.value_float(value_ptr))
            elif value_type == 2:
                value = bool(self.value_bool(value_ptr))
            elif value_type == 4:
                value = int(self.value_int(value_ptr))
            elif value_type == 5:
                value = int(self.value_uint(value_ptr))
        except Exception:
            value = text
        return {"value": value, "text": text, "mmsType": value_type}

    def _report_value_payload(self, value_ptr: int) -> dict[str, Any]:
        raw = self._value_payload(value_ptr)
        leaf = value_ptr
        for _ in range(4):
            if self.value_type(leaf) not in {0, 1}:
                break
            if self.value_array_size(leaf) <= 0:
                break
            next_leaf = self.value_element(leaf, 0)
            if not next_leaf:
                break
            leaf = next_leaf
        primary = self._value_payload(leaf)
        primary["reportText"] = raw["text"]
        return primary

    def subscribe(self, reference: str, integrity_ms: int) -> dict[str, Any]:
        connection = self._required_connection()
        error = c_int()
        rcb = self.get_rcb(connection, byref(error), reference.encode("utf-8"), None)
        if error.value != 0 or not rcb:
            raise RuntimeError(f"读取RCB失败 {reference}，IedClientError={error.value}")
        rpt_id = self._decode(self.rcb_get_rpt_id(rcb))
        dataset = self._decode(self.rcb_get_dataset(rcb))

        @self.report_cb_type
        def report_callback(_parameter: int, report: int) -> None:
            try:
                values_ptr = self.report_values(report)
                count = self.value_array_size(values_ptr) if values_ptr else 0
                entries: list[dict[str, Any]] = []
                for index in range(count):
                    reason = self.report_reason(report, index)
                    if reason == 0:
                        continue
                    element = self.value_element(values_ptr, index)
                    entries.append({"index": index, "reason": reason, **(self._report_value_payload(element) if element else {"value": None})})
                payload: dict[str, Any] = {
                    "event": "report",
                    "rcbReference": self._decode(self.report_rcb_ref(report)),
                    "rptId": self._decode(self.report_rpt_id(report)),
                    "entries": entries,
                }
                if self.report_has_seq(report):
                    payload["seqNum"] = int(self.report_seq(report))
                if self.report_has_timestamp(report):
                    payload["sourceTimestampMs"] = int(self.report_timestamp(report))
                emit(payload)
            except Exception as exc:
                emit({"event": "error", "operation": "report_callback", "error": str(exc)})

        self.callbacks[reference] = report_callback
        self.rcbs[reference] = int(rcb)
        self.install_report(connection, reference.encode(), rpt_id.encode(), report_callback, None)
        self.rcb_set_reserved(rcb, True)
        self.rcb_set_intg_pd(rcb, max(1000, int(integrity_ms)))
        self.rcb_set_enabled(rcb, True)
        # 使用CFG模型中定义的TrgOps，避免客户端把DATA_UPDATE等额外触发条件强加给板卡。
        # 初值已在连接后通过轮询读取；启用多个报告时不再逐个立即触发GI，防止同一
        # MMS关联瞬间叠加多个完整数据集报告而压垮嵌入式服务器的发送路径。
        mask = RCB_ELEMENT_RESV | RCB_ELEMENT_INTG_PD | RCB_ELEMENT_RPT_ENA
        self.set_rcb(connection, byref(error), rcb, mask, True)
        if error.value != 0:
            self.uninstall_report(connection, reference.encode())
            self.destroy_rcb(rcb)
            self.callbacks.pop(reference, None)
            self.rcbs.pop(reference, None)
            raise RuntimeError(f"启用RCB失败 {reference}，IedClientError={error.value}")
        return {"reference": reference, "rptId": rpt_id, "dataset": dataset, "enabled": True}

    def disconnect(self) -> None:
        if not self.connection:
            return
        connection = self.connection
        for reference, rcb in list(self.rcbs.items()):
            try:
                error = c_int()
                self.rcb_set_enabled(rcb, False)
                self.set_rcb(connection, byref(error), rcb, RCB_ELEMENT_RPT_ENA, True)
                self.uninstall_report(connection, reference.encode())
            except Exception:
                pass
            try:
                self.destroy_rcb(rcb)
            except Exception:
                pass
        self.rcbs.clear()
        self.callbacks.clear()
        try:
            self.close(connection)
        finally:
            self.destroy(connection)
            self.connection = None

    def _required_connection(self) -> int:
        if not self.connection:
            raise RuntimeError("设备尚未连接")
        return self.connection


def main() -> None:
    try:
        client = NativeClient()
        emit({"event": "ready", "pointerBits": ctypes.sizeof(c_void_p) * 8})
    except Exception as exc:
        emit({"event": "fatal", "error": str(exc)})
        raise SystemExit(2)

    for raw_line in sys.stdin:
        if not raw_line.strip():
            continue
        request_id = ""
        try:
            command = json.loads(raw_line)
            request_id = str(command.get("id") or "")
            action = str(command.get("cmd") or "")
            if action == "connect":
                result = client.connect(str(command["host"]), int(command.get("port", 102)))
            elif action == "browse":
                result = client.browse()
            elif action == "read":
                result = client.read(str(command["reference"]), str(command.get("fc") or "MX"))
            elif action == "read_batch":
                result = {"values": [client.read(str(item["reference"]), str(item.get("fc") or "MX")) for item in command.get("items", [])]}
            elif action == "subscribe":
                result = client.subscribe(str(command["reference"]), int(command.get("integrityMs", 10000)))
            elif action == "disconnect":
                client.disconnect()
                result = {"disconnected": True}
            elif action == "ping":
                result = {"state": client.get_state(client._required_connection())}
            elif action == "shutdown":
                client.disconnect()
                emit({"event": "response", "id": request_id, "ok": True, "result": {"shutdown": True}})
                break
            else:
                raise ValueError(f"不支持的命令: {action}")
            emit({"event": "response", "id": request_id, "cmd": action, "ok": True, "result": result})
        except Exception as exc:
            emit({"event": "response", "id": request_id, "ok": False, "error": str(exc)})

    try:
        client.disconnect()
    except Exception:
        pass


if __name__ == "__main__":
    main()
