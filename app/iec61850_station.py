"""IEC 61850 现场测试总站的 ICD 解析和多设备会话管理。"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = APP_DIR.parent
STATION_STORE_PATH = DEFAULT_ROOT / "iec61850_station.json"
STATION_IMPORT_DIR = DEFAULT_ROOT / "IEC61850总站设备"
ASSET_APP_DIR = APP_DIR
_PROTOCOL_DISPLAY_SUFFIX = re.compile(
    r"\s*Modbus\s+V10(?:\.0)?\s*转\s*IEC\s*61850\s*$", re.IGNORECASE
)


def configure_station_paths(base_dir: Path, asset_app_dir: Path | None = None) -> None:
    global STATION_STORE_PATH, STATION_IMPORT_DIR, ASSET_APP_DIR, _manager
    root = Path(base_dir).resolve()
    STATION_STORE_PATH = root / "iec61850_station.json"
    STATION_IMPORT_DIR = root / "IEC61850总站设备"
    ASSET_APP_DIR = Path(asset_app_dir).resolve() if asset_app_dir else APP_DIR
    if _manager is not None:
        _manager.stop_all()
        _manager = None


def _tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _clean_display_name(value: Any, fallback: str = "") -> str:
    cleaned = _PROTOCOL_DISPLAY_SUFFIX.sub("", str(value or "").strip()).strip()
    return cleaned or str(fallback or "").strip()


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if _tag_name(child) == name]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in list(element) if _tag_name(child) == name), None)


def _descendant(element: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in element.iter() if _tag_name(item) == name), None)


def _safe_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return normalized[:48] or uuid.uuid4().hex[:12]


def _dai_value(doi: ET.Element | None, name: str) -> str:
    if doi is None:
        return ""
    for dai in _children(doi, "DAI"):
        if dai.get("name") == name:
            val = _child(dai, "Val")
            return (val.text or "").strip() if val is not None else ""
    return ""


def _flatten_da_path(da: ET.Element, da_types: dict[str, ET.Element]) -> tuple[str, str]:
    name = str(da.get("name") or "")
    b_type = str(da.get("bType") or "")
    type_id = str(da.get("type") or "")
    if b_type != "Struct" or not type_id or type_id not in da_types:
        return name, b_type
    leaves = _children(da_types[type_id], "BDA")
    preferred = next((leaf for leaf in leaves if leaf.get("name") in {"f", "i"}), leaves[0] if leaves else None)
    if preferred is None:
        return name, b_type
    nested_path, nested_type = _flatten_da_path(preferred, da_types)
    return f"{name}.{nested_path}", nested_type


def parse_icd(content: str, file_name: str) -> dict[str, Any]:
    if len(content.encode("utf-8")) > 1024 * 1024:
        raise ValueError("ICD 文件超过 1 MiB 限制")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError(f"ICD XML 解析失败: {exc}") from exc
    if _tag_name(root) != "SCL":
        raise ValueError("文件根节点不是 SCL")

    ied = _descendant(root, "IED")
    if ied is None:
        raise ValueError("ICD 中没有 IED")
    ied_name = str(ied.get("name") or "").strip()
    if not ied_name:
        raise ValueError("ICD 中的 IED 缺少 name")
    display_name = _clean_display_name(ied.get("desc"), ied_name)

    ip = ""
    port = 102
    for connected_ap in (item for item in root.iter() if _tag_name(item) == "ConnectedAP"):
        if connected_ap.get("iedName") not in {None, ied_name}:
            continue
        address = _child(connected_ap, "Address")
        if address is None:
            continue
        for parameter in _children(address, "P"):
            kind = str(parameter.get("type") or "").upper()
            value = (parameter.text or "").strip()
            if kind == "IP":
                ip = value
            elif kind in {"IP-PORT", "PORT"} and value.isdigit():
                port = int(value)

    templates = _descendant(root, "DataTypeTemplates")
    ln_types: dict[str, ET.Element] = {}
    do_types: dict[str, ET.Element] = {}
    da_types: dict[str, ET.Element] = {}
    if templates is not None:
        for item in list(templates):
            item_id = str(item.get("id") or "")
            if _tag_name(item) == "LNodeType":
                ln_types[item_id] = item
            elif _tag_name(item) == "DOType":
                do_types[item_id] = item
            elif _tag_name(item) == "DAType":
                da_types[item_id] = item

    access_point = _descendant(ied, "AccessPoint")
    server = _descendant(access_point, "Server") if access_point is not None else None
    if server is None:
        raise ValueError("ICD 中没有 AccessPoint/Server")

    logical_devices: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    rcbs: list[dict[str, Any]] = []

    for ldevice in _children(server, "LDevice"):
        ld_inst = str(ldevice.get("inst") or "")
        domain = f"{ied_name}{ld_inst}"
        nodes: list[dict[str, Any]] = []
        ln_elements = [item for item in list(ldevice) if _tag_name(item) in {"LN0", "LN"}]
        node_lookup: dict[tuple[str, str, str], ET.Element] = {}
        for ln in ln_elements:
            ln_class = "LLN0" if _tag_name(ln) == "LN0" else str(ln.get("lnClass") or "")
            ln_inst = str(ln.get("inst") or "")
            prefix = str(ln.get("prefix") or "")
            ln_name = f"{prefix}{ln_class}{ln_inst}"
            node_lookup[(prefix, ln_class, ln_inst)] = ln
            nodes.append({"name": ln_name, "class": ln_class, "inst": ln_inst})

        ln0 = next((item for item in ln_elements if _tag_name(item) == "LN0"), None)
        if ln0 is not None:
            for dataset in _children(ln0, "DataSet"):
                ds_name = str(dataset.get("name") or "")
                members: list[dict[str, Any]] = []
                for fcda in _children(dataset, "FCDA"):
                    member = {key: str(fcda.get(key) or "") for key in ("ldInst", "prefix", "lnClass", "lnInst", "doName", "daName", "fc")}
                    members.append(member)
                datasets.append({
                    "name": ds_name,
                    "description": str(dataset.get("desc") or ""),
                    "reference": f"{domain}/LLN0${ds_name}",
                    "domain": domain,
                    "members": members,
                })
            for report in _children(ln0, "ReportControl"):
                ds_name = str(report.get("datSet") or "")
                rcbs.append({
                    "name": str(report.get("name") or ""),
                    "reference": f"{domain}/LLN0.RP.{report.get('name') or ''}",
                    "rptId": str(report.get("rptID") or ""),
                    "dataset": ds_name,
                    "datasetReference": f"{domain}/LLN0${ds_name}",
                    "integrityMs": int(report.get("intgPd") or 10000),
                    "buffered": str(report.get("buffered") or "false").lower() == "true",
                })

        dataset_by_name = {item["name"]: item for item in datasets if item["domain"] == domain}
        for dataset_name, dataset in dataset_by_name.items():
            for index, member in enumerate(dataset["members"]):
                ln = node_lookup.get((member["prefix"], member["lnClass"], member["lnInst"]))
                if ln is None:
                    continue
                ln_name = f"{member['prefix']}{member['lnClass']}{member['lnInst']}"
                do_name = member["doName"]
                doi = next((item for item in _children(ln, "DOI") if item.get("name") == do_name), None)
                ln_type = ln_types.get(str(ln.get("lnType") or ""))
                do_decl = next((item for item in _children(ln_type, "DO") if item.get("name") == do_name), None) if ln_type is not None else None
                do_type = do_types.get(str(do_decl.get("type") or "")) if do_decl is not None else None
                fc = member["fc"]
                da_path = member["daName"]
                b_type = ""
                quality_ref = ""
                time_ref = ""
                if not da_path and do_type is not None:
                    candidates = [da for da in _children(do_type, "DA") if str(da.get("fc") or "") == fc and str(da.get("name") or "") not in {"q", "t", "d", "dU"}]
                    preferred = next((da for da in candidates if da.get("name") in {"mag", "stVal", "actVal", "instMag"}), candidates[0] if candidates else None)
                    if preferred is not None:
                        da_path, b_type = _flatten_da_path(preferred, da_types)
                    if any(da.get("name") == "q" and da.get("fc") == fc for da in _children(do_type, "DA")):
                        quality_ref = f"{domain}/{ln_name}.{do_name}.q"
                    if any(da.get("name") == "t" and da.get("fc") == fc for da in _children(do_type, "DA")):
                        time_ref = f"{domain}/{ln_name}.{do_name}.t"
                reference = f"{domain}/{ln_name}.{do_name}" + (f".{da_path}" if da_path else "")
                display = _dai_value(doi, "dU") or str(doi.get("desc") or "") if doi is not None else ""
                display = display or str(do_decl.get("desc") or "") if do_decl is not None else display
                points.append({
                    "id": hashlib.sha1(reference.encode("utf-8")).hexdigest()[:12],
                    "displayName": display or do_name,
                    "reference": reference,
                    "doReference": f"{domain}/{ln_name}.{do_name}",
                    "qualityReference": quality_ref,
                    "timeReference": time_ref,
                    "fc": fc,
                    "bType": b_type,
                    "domain": domain,
                    "logicalNode": ln_name,
                    "dataObject": do_name,
                    "dataset": dataset_name,
                    "datasetIndex": index,
                    "unit": "",
                })

        logical_devices.append({"inst": ld_inst, "name": domain, "description": str(ldevice.get("desc") or ""), "logicalNodes": nodes})

    if not points:
        raise ValueError("ICD 中没有可显示的 DataSet/FCDA 测点")

    return {
        "fileName": Path(file_name).name,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "iedName": ied_name,
        "displayName": display_name,
        "host": ip or "192.168.0.123",
        "port": port,
        "logicalDevices": logical_devices,
        "points": points,
        "datasets": datasets,
        "rcbs": rcbs,
    }


class DeviceWorker:
    def __init__(self, manager: "StationManager", device_id: str) -> None:
        self.manager = manager
        self.device_id = device_id
        self.process: subprocess.Popen[str] | None = None
        self.write_lock = threading.Lock()
        self.request_seq = 0

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        python_exe = DEFAULT_ROOT / "runtime" / "python32" / "python.exe"
        worker_script = ASSET_APP_DIR / "iec61850_worker.py"
        if not python_exe.exists():
            python_exe = STATION_STORE_PATH.parent / "runtime" / "python32" / "python.exe"
        if not python_exe.exists():
            raise FileNotFoundError(f"缺少32位IEC61850运行时: {python_exe}")
        if not worker_script.exists():
            raise FileNotFoundError(f"缺少IEC61850工作进程: {worker_script}")
        self.process = subprocess.Popen(
            [str(python_exe), str(worker_script)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        threading.Thread(target=self._read_stdout, name=f"iec61850-{self.device_id}", daemon=True).start()
        threading.Thread(target=self._read_stderr, name=f"iec61850-{self.device_id}-stderr", daemon=True).start()

    def send(self, command: dict[str, Any]) -> str:
        self.start()
        assert self.process and self.process.stdin
        with self.write_lock:
            self.request_seq += 1
            request_id = f"{self.device_id}-{self.request_seq}"
            command = {"id": request_id, **command}
            self.process.stdin.write(json.dumps(command, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
        return request_id

    def stop(self) -> None:
        process = self.process
        if not process:
            return
        if process.poll() is None:
            try:
                self.send({"cmd": "shutdown"})
                process.wait(timeout=3)
            except Exception:
                process.terminate()
        self.process = None

    def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                payload = {"event": "error", "operation": "worker_output", "error": line.strip()}
            self.manager.handle_worker_event(self.device_id, payload)
        code = self.process.poll() if self.process else None
        self.manager.handle_worker_event(self.device_id, {"event": "worker_exit", "exitCode": code})

    def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            self.manager.handle_worker_event(self.device_id, {"event": "worker_stderr", "error": line.strip()})


class StationManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.payload = self._load()
        self.workers: dict[str, DeviceWorker] = {}
        self.subscribers: list[queue.Queue[dict[str, Any]]] = []
        self.running = True
        threading.Thread(target=self._poll_loop, name="iec61850-station-poll", daemon=True).start()

    def _load(self) -> dict[str, Any]:
        if STATION_STORE_PATH.exists():
            try:
                payload = json.loads(STATION_STORE_PATH.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("devices"), list):
                    for item in payload["devices"]:
                        item["displayName"] = _clean_display_name(
                            item.get("displayName"), item.get("iedName")
                        )
                        item.update({"status": "offline", "statusText": "未连接", "onlineModel": None, "values": {}, "reportStates": {}})
                    payload.setdefault("events", [])
                    return payload
            except Exception:
                pass
        return {"version": 1, "selectedDeviceId": None, "devices": [], "events": []}

    def _save(self) -> None:
        persistent = deepcopy(self.payload)
        persistent["events"] = []
        for item in persistent["devices"]:
            for key in ("status", "statusText", "onlineModel", "values", "reportStates", "lastSeen", "lastError"):
                item.pop(key, None)
        STATION_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATION_STORE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(persistent, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(STATION_STORE_PATH)

    def import_icd(self, content: str, file_name: str, display_name: str = "", host: str = "") -> dict[str, Any]:
        parsed = parse_icd(content, file_name)
        device_id = _safe_id(display_name or parsed["iedName"])
        with self.lock:
            existing_ids = {item["id"] for item in self.payload["devices"]}
            base_id = device_id
            suffix = 2
            while device_id in existing_ids:
                device_id = f"{base_id}-{suffix}"
                suffix += 1
            device = {
                "id": device_id,
                **parsed,
                "displayName": _clean_display_name(display_name, parsed["displayName"]),
                "host": host.strip() or parsed["host"],
                "importedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                "status": "offline", "statusText": "未连接", "values": {}, "onlineModel": None,
                "reportStates": {}, "autoConnect": False,
            }
            self.payload["devices"].append(device)
            self.payload["selectedDeviceId"] = device_id
            STATION_IMPORT_DIR.mkdir(parents=True, exist_ok=True)
            (STATION_IMPORT_DIR / f"{device_id}.icd").write_text(content, encoding="utf-8")
            self._save()
            self._publish("device_imported", device_id)
            return deepcopy(device)

    def update_device(self, device_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            device = self._device(device_id)
            if "displayName" in changes:
                device["displayName"] = _clean_display_name(
                    str(changes["displayName"])[:100], device["displayName"]
                )
            if "host" in changes:
                host = str(changes["host"]).strip()
                if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
                    raise ValueError("设备IP格式错误")
                device["host"] = host
            if "port" in changes:
                port = int(changes["port"])
                if not 1 <= port <= 65535:
                    raise ValueError("端口必须在1到65535之间")
                device["port"] = port
            self._save()
            self._publish("device_updated", device_id)
            return deepcopy(device)

    def select_device(self, device_id: str) -> dict[str, Any]:
        with self.lock:
            self._device(device_id)
            self.payload["selectedDeviceId"] = device_id
            self._save()
            return self.snapshot()

    def delete_device(self, device_id: str) -> dict[str, Any]:
        self.disconnect(device_id)
        with self.lock:
            self.payload["devices"] = [item for item in self.payload["devices"] if item["id"] != device_id]
            if self.payload.get("selectedDeviceId") == device_id:
                self.payload["selectedDeviceId"] = self.payload["devices"][0]["id"] if self.payload["devices"] else None
            self._save()
            (STATION_IMPORT_DIR / f"{device_id}.icd").unlink(missing_ok=True)
            self._publish("device_deleted", device_id)
            return self.snapshot()

    def connect(self, device_id: str) -> dict[str, Any]:
        with self.lock:
            device = self._device(device_id)
            device["status"] = "connecting"
            device["statusText"] = "正在建立MMS关联"
            device["lastError"] = ""
            worker = self.workers.setdefault(device_id, DeviceWorker(self, device_id))
            worker.send({"cmd": "connect", "host": device["host"], "port": device["port"]})
            self._event(device_id, "connect_start", f"正在连接 {device['host']}:{device['port']}")
            return self.device_snapshot(device_id)

    def disconnect(self, device_id: str) -> dict[str, Any]:
        worker = self.workers.pop(device_id, None)
        with self.lock:
            device = self._device(device_id)
            device["status"] = "offline"
            device["statusText"] = "已断开"
            device["lastError"] = ""
            device["reportStates"] = {}
            self._event(device_id, "disconnected", "MMS连接已断开")
            snapshot = deepcopy(device)
        if worker:
            worker.stop()
        return snapshot

    def read_now(self, device_id: str, reference: str, fc: str) -> dict[str, Any]:
        with self.lock:
            device = self._device(device_id)
            if not any(point["reference"] == reference for point in device["points"]):
                raise ValueError("测点不属于当前ICD")
            worker = self.workers.get(device_id)
            if not worker:
                raise ValueError("设备尚未连接")
            request_id = worker.send({"cmd": "read", "reference": reference, "fc": fc})
            return {"ok": True, "requestId": request_id}

    def subscribe_rcb(self, device_id: str, reference: str) -> dict[str, Any]:
        with self.lock:
            device = self._device(device_id)
            rcb = next((item for item in device["rcbs"] if item["reference"] == reference), None)
            if rcb is None:
                raise ValueError("RCB不属于当前ICD")
            worker = self.workers.get(device_id)
            if not worker:
                raise ValueError("设备尚未连接")
            request_id = worker.send({"cmd": "subscribe", "reference": reference, "integrityMs": rcb["integrityMs"]})
            device["reportStates"][reference] = {"status": "enabling", "text": "正在启用"}
            return {"ok": True, "requestId": request_id}

    def handle_worker_event(self, device_id: str, payload: dict[str, Any]) -> None:
        with self.lock:
            try:
                device = self._device(device_id)
            except KeyError:
                return
            event = payload.get("event")
            if event == "response":
                command = payload.get("cmd")
                if payload.get("ok") and command == "connect":
                    device["status"] = "online"
                    device["statusText"] = "MMS已连接"
                    device["lastSeen"] = payload.get("at")
                    worker = self.workers.get(device_id)
                    if worker:
                        worker.send({"cmd": "browse"})
                        self._send_read_batch(device, worker)
                    self._event(device_id, "connected", "MMS关联成功")
                elif payload.get("ok") and command == "browse":
                    device["onlineModel"] = payload.get("result")
                    device["modelComparison"] = self._compare_model(device)
                elif payload.get("ok") and command == "read_batch":
                    self._apply_values(device, payload.get("result", {}).get("values", []), "poll")
                elif payload.get("ok") and command == "read":
                    self._apply_values(device, [payload.get("result", {})], "manual")
                elif payload.get("ok") and command == "subscribe":
                    result = payload.get("result", {})
                    reference = str(result.get("reference") or "")
                    device["reportStates"][reference] = {"status": "enabled", "text": "已启用", **result}
                    self._event(device_id, "report_enabled", f"报告已启用: {reference}")
                elif not payload.get("ok"):
                    error = str(payload.get("error") or "工作进程命令失败")
                    if device["status"] == "connecting":
                        device["status"] = "error"
                        device["statusText"] = "连接失败"
                    device["lastError"] = error
                    self._event(device_id, "error", error)
            elif event == "report":
                device["lastSeen"] = payload.get("at")
                rcb = next((item for item in device["rcbs"] if item["reference"] == payload.get("rcbReference")), None)
                dataset_name = rcb.get("dataset") if rcb else ""
                dataset_points = [point for point in device["points"] if point["dataset"] == dataset_name]
                for entry in payload.get("entries", []):
                    index = int(entry.get("index", -1))
                    if 0 <= index < len(dataset_points):
                        point = dataset_points[index]
                        current = device["values"].setdefault(point["reference"], {})
                        current.update({
                            "ok": True, "value": entry.get("value"), "text": entry.get("text"),
                            "mmsType": entry.get("mmsType"), "reportText": entry.get("reportText"),
                            "reason": entry.get("reason"),
                            "source": "report", "receivedAt": payload.get("at"), "stale": False,
                        })
                self._event(device_id, "report", f"收到报告 {payload.get('rptId') or payload.get('rcbReference')}", payload)
            elif event in {"fatal", "worker_exit", "worker_stderr", "error"}:
                if device.get("status") == "offline" and device_id not in self.workers:
                    return
                error = str(payload.get("error") or f"工作进程退出: {payload.get('exitCode')}")
                device["status"] = "error"
                device["statusText"] = "IEC61850工作进程异常"
                device["lastError"] = error
                self._event(device_id, "error", error)
            self._publish(str(event or "update"), device_id)

    def _send_read_batch(self, device: dict[str, Any], worker: DeviceWorker) -> None:
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for point in device["points"]:
            for reference in (point["reference"], point.get("qualityReference"), point.get("timeReference")):
                if reference and reference not in seen:
                    items.append({"reference": reference, "fc": point["fc"]})
                    seen.add(reference)
        worker.send({"cmd": "read_batch", "items": items})
        device["lastPollSent"] = time.monotonic()

    def _apply_values(self, device: dict[str, Any], values: list[dict[str, Any]], source: str) -> None:
        received_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        for value in values:
            reference = str(value.get("reference") or "")
            if not reference:
                continue
            point = next((item for item in device["points"] if item["reference"] == reference), None)
            if point is not None:
                device["values"][reference] = {
                    **device["values"].get(reference, {}), **value,
                    "source": source, "receivedAt": received_at,
                    "stale": not bool(value.get("ok")),
                }
                continue
            quality_point = next((item for item in device["points"] if item.get("qualityReference") == reference), None)
            if quality_point is not None:
                current = device["values"].setdefault(quality_point["reference"], {})
                quality_text = str(value.get("text") or "")
                current.update({
                    "qualityText": "good" if value.get("ok") and quality_text and set(quality_text) <= {"0"} else quality_text or "未知",
                    "qualityRaw": value.get("value"), "receivedAt": received_at,
                })
                continue
            time_point = next((item for item in device["points"] if item.get("timeReference") == reference), None)
            if time_point is not None:
                current = device["values"].setdefault(time_point["reference"], {})
                current.update({"sourceTimeText": value.get("text"), "receivedAt": received_at})
        device["lastSeen"] = received_at

    def _compare_model(self, device: dict[str, Any]) -> dict[str, Any]:
        expected_lds = {item["name"] for item in device["logicalDevices"]}
        online = device.get("onlineModel") or {}
        actual_lds = {item["name"] for item in online.get("logicalDevices", [])}
        missing_lds = sorted(expected_lds - actual_lds)
        extra_lds = sorted(actual_lds - expected_lds)
        missing_lns: list[str] = []
        extra_lns: list[str] = []
        for ld in device["logicalDevices"]:
            actual_ld = next((item for item in online.get("logicalDevices", []) if item["name"] == ld["name"]), None)
            expected = {item["name"] for item in ld["logicalNodes"]}
            actual = {item["name"] for item in (actual_ld or {}).get("logicalNodes", [])}
            missing_lns.extend(f"{ld['name']}/{name}" for name in sorted(expected - actual))
            extra_lns.extend(f"{ld['name']}/{name}" for name in sorted(actual - expected))
        return {
            "matched": not missing_lds and not extra_lds and not missing_lns and not extra_lns,
            "missingLogicalDevices": missing_lds, "extraLogicalDevices": extra_lds,
            "missingLogicalNodes": missing_lns, "extraLogicalNodes": extra_lns,
        }

    def _poll_loop(self) -> None:
        while self.running:
            time.sleep(2)
            with self.lock:
                for device in self.payload["devices"]:
                    if device.get("status") != "online":
                        continue
                    worker = self.workers.get(device["id"])
                    if not worker or not worker.process or worker.process.poll() is not None:
                        continue
                    if time.monotonic() - float(device.get("lastPollSent") or 0) >= 5:
                        self._send_read_batch(device, worker)

    def _device(self, device_id: str) -> dict[str, Any]:
        device = next((item for item in self.payload["devices"] if item["id"] == device_id), None)
        if device is None:
            raise KeyError(f"IEC61850设备不存在: {device_id}")
        return device

    def _event(self, device_id: str, event_type: str, message: str, detail: dict[str, Any] | None = None) -> None:
        event = {
            "id": uuid.uuid4().hex, "deviceId": device_id, "type": event_type,
            "message": message, "at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        }
        if detail:
            event["detail"] = detail
        self.payload["events"].insert(0, event)
        del self.payload["events"][500:]

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return deepcopy(self.payload)

    def device_snapshot(self, device_id: str) -> dict[str, Any]:
        with self.lock:
            return deepcopy(self._device(device_id))

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=4)
        with self.lock:
            self.subscribers.append(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def _publish(self, reason: str, device_id: str) -> None:
        event = {"reason": reason, "deviceId": device_id, "snapshot": self.snapshot()}
        for subscriber in list(self.subscribers):
            try:
                if subscriber.full():
                    subscriber.get_nowait()
                subscriber.put_nowait(event)
            except (queue.Empty, queue.Full):
                pass

    def stop_all(self) -> None:
        self.running = False
        for worker in list(self.workers.values()):
            worker.stop()
        self.workers.clear()


_manager: StationManager | None = None


def get_station_manager() -> StationManager:
    global _manager
    if _manager is None:
        _manager = StationManager()
    return _manager
