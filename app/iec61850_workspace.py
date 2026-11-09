"""IEC61850 转发配置工作台。

上位机只允许选择固件当前真实提供的 V10 转发点。生成结果包含设备运行时
使用的单一 cfg、总站核对点表和 ICD 初稿。Modbus绑定通过cfg的sAddr字段内嵌。
网络参数用于生成 ICD 和现场连接校验；本工作台只生成、校验和导出配置包。
"""
from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
import re
import socket
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from live_register_catalog import get_register_catalog


SCHEMA_VERSION = 1
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

_ANALOG = {
    "input_register.sensor_3.temperature": ("v10_ir0_temp", "AnIn1", "℃"),
    "input_register.sensor_3.humidity": ("v10_ir2_hum", "AnIn2", "g/m³"),
    "input_register.pressure": ("v10_ir4_pres", "AnIn3", "kPa"),
    "input_register.flow": ("v10_ir6_flow", "AnIn4", "L/min"),
}
_BINARY_ADDRESSES = list(range(20)) + list(range(34, 44))
_STATS = {
    "input_register.heat_session_1.session_run_seconds": ("v10_ir32_heat1_run", "RunTm1", "uint32"),
    "input_register.heat_session_2.session_run_seconds": ("v10_ir34_heat2_run", "RunTm2", "uint32"),
    "input_register.output.htc1_open_count": ("v10_ir44_heat1_count", "OpCnt1", "int64"),
    "input_register.output.htc2_open_count": ("v10_ir48_heat2_count", "OpCnt2", "int64"),
    "input_register.output.antifreeze_open_count": ("v10_ir52_anti_count", "OpCnt3", "int64"),
}


def _catalog_by_key() -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    items = get_register_catalog()
    return ({str(item["id"]): item for item in items},
            {int(item["address"]): item for item in items if item["area"] == "discrete_input"})


def forwarding_catalog() -> list[dict[str, Any]]:
    """返回固件当前 UpdateV10Forwarding 确实会更新的点。"""
    by_id, di_by_address = _catalog_by_key()
    result: list[dict[str, Any]] = []
    for point_id, (alias, object_name, unit) in _ANALOG.items():
        item = by_id[point_id]
        result.append(_point(item, alias, "analog", "GGIO1", object_name, "float", unit))
    for index, address in enumerate(_BINARY_ADDRESSES, start=1):
        item = di_by_address[address]
        result.append(_point(item, f"v10_di{address}", "binary", "GGIO100", f"Ind{index}", "bool", ""))
    for point_id, (alias, object_name, mapping_type) in _STATS.items():
        item = by_id[point_id]
        result.append(_point(item, alias, "statistics", "GGIO200", object_name, mapping_type, str(item.get("unit") or "")))
    return result


def _point(item: dict[str, Any], alias: str, category: str, logical_node: str,
           object_name: str, mapping_type: str, unit: str) -> dict[str, Any]:
    area = "DI" if item["area"] == "discrete_input" else "IR"
    return {
        "pointId": str(item["id"]), "sourceName": str(item["name"]),
        "area": area, "address": int(item["address"]), "wordLength": int(item["wordLength"]),
        "dataType": str(item["dataType"]), "unit": unit, "alias": alias,
        "category": category, "logicalNode": logical_node,
        "defaultObjectName": object_name, "mappingType": mapping_type,
        "description": str(item.get("notes") or item["name"]),
        "firmwareSupported": True,
    }


def default_profile() -> dict[str, Any]:
    points = [{"pointId": item["pointId"], "enabled": True,
               "objectName": item["defaultObjectName"], "stationName": item["sourceName"]}
              for item in forwarding_catalog()]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "default_yldq_v10", "name": "YLDQ V10 默认转发",
        "deviceId": "", "iedName": "YLDQ01", "logicalDevice": "LD_Device_1",
        "pointPrefix": "", "stationPrefix": "", "manufacturer": "YLDQ", "description": "YLDQ V10 只读转发",
        "network": {"ip": "192.168.0.123", "netmask": "255.255.255.0",
                    "gateway": "192.168.0.1", "port": 102},
        "report": {"analogIntegrityMs": 10000, "binaryIntegrityMs": 10000,
                   "statisticsIntegrityMs": 30000, "bufferTimeMs": 100},
        "points": points,
    }


def load_profiles(path: Path) -> dict[str, Any]:
    if not path.exists():
        profile = default_profile()
        return {"schemaVersion": SCHEMA_VERSION, "selectedProfileId": profile["id"], "profiles": [profile]}
    payload = json.loads(path.read_text(encoding="utf-8"))
    profiles = [normalize_profile(item) for item in payload.get("profiles", [])]
    if not profiles:
        profiles = [default_profile()]
    selected = str(payload.get("selectedProfileId") or profiles[0]["id"])
    if selected not in {item["id"] for item in profiles}:
        selected = profiles[0]["id"]
    return {"schemaVersion": SCHEMA_VERSION, "selectedProfileId": selected, "profiles": profiles}


def save_profile(path: Path, raw_profile: dict[str, Any]) -> dict[str, Any]:
    profile = normalize_profile(raw_profile)
    payload = load_profiles(path)
    profiles = payload["profiles"]
    for index, item in enumerate(profiles):
        if item["id"] == profile["id"]:
            profiles[index] = profile
            break
    else:
        profiles.append(profile)
    payload["selectedProfileId"] = profile["id"]
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(path, payload)
    return profile


def normalize_profile(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("IEC61850配置必须是JSON对象")
    base = default_profile()
    profile_id = _safe_id(raw.get("id") or base["id"], "配置ID", 48)
    ied_name = _safe_id(raw.get("iedName") or base["iedName"], "IED名称", 64)
    logical_device = _safe_id(raw.get("logicalDevice") or base["logicalDevice"], "逻辑设备名称", 64)
    point_prefix = str(raw.get("pointPrefix") or "").strip()
    if point_prefix:
        _safe_id(point_prefix, "点名前缀", 4)
    station_prefix = str(raw.get("stationPrefix") or "").strip()[:60]
    phase = _station_phase(station_prefix)
    if phase and re.search(r"_[ABC]$", logical_device, re.IGNORECASE):
        logical_device = f"{logical_device[:-1]}{phase}"
    profile_name = str(raw.get("name") or base["name"]).strip()[:80]
    description = profile_name
    network = raw.get("network") if isinstance(raw.get("network"), dict) else {}
    normalized_network = {
        "ip": _ipv4(network.get("ip", base["network"]["ip"]), "IP地址"),
        "netmask": _netmask(network.get("netmask", base["network"]["netmask"])),
        "gateway": _ipv4(network.get("gateway", base["network"]["gateway"]), "网关"),
        "port": _integer(network.get("port", 102), "MMS端口", 1, 65535),
    }
    interface = ipaddress.IPv4Interface(f"{normalized_network['ip']}/{normalized_network['netmask']}")
    if ipaddress.IPv4Address(normalized_network["gateway"]) not in interface.network:
        raise ValueError("网关必须与设备IP位于同一子网")

    report_raw = raw.get("report") if isinstance(raw.get("report"), dict) else {}
    report = {
        "analogIntegrityMs": _integer(report_raw.get("analogIntegrityMs", 10000), "模拟量完整周期", 1000, 3600000),
        "binaryIntegrityMs": _integer(report_raw.get("binaryIntegrityMs", 10000), "状态量完整周期", 1000, 3600000),
        "statisticsIntegrityMs": _integer(report_raw.get("statisticsIntegrityMs", 30000), "统计量完整周期", 1000, 3600000),
        "bufferTimeMs": _integer(report_raw.get("bufferTimeMs", 100), "报告合并时间", 0, 60000),
    }
    supported = {item["pointId"]: item for item in forwarding_catalog()}
    raw_points = raw.get("points") if isinstance(raw.get("points"), list) else base["points"]
    seen: set[str] = set()
    points: list[dict[str, Any]] = []
    for raw_point in raw_points:
        if not isinstance(raw_point, dict):
            continue
        point_id = str(raw_point.get("pointId") or "")
        meta = supported.get(point_id)
        if meta is None:
            raise ValueError(f"固件当前不支持转发点: {point_id}")
        if point_id in seen:
            raise ValueError(f"转发点重复: {point_id}")
        seen.add(point_id)
        object_name = str(raw_point.get("objectName") or meta["defaultObjectName"]).strip()
        if point_prefix and not object_name.startswith(point_prefix):
            object_name = f"{point_prefix}{object_name}"
        object_name = _safe_id(object_name, f"{meta['sourceName']}对象名", 12)
        points.append({"pointId": point_id, "enabled": bool(raw_point.get("enabled", True)),
                       "objectName": object_name,
                       "stationName": str(raw_point.get("stationName") or meta["sourceName"]).strip()[:80]})
    enabled_names = [item["objectName"] for item in points if item["enabled"]]
    if not enabled_names:
        raise ValueError("至少选择一个转发点")
    if len(enabled_names) != len(set(enabled_names)):
        raise ValueError("启用点的IEC61850对象名不能重复")
    if len(enabled_names) * 3 > 128:
        raise ValueError("映射属性超过固件128条上限")
    return {
        "schemaVersion": SCHEMA_VERSION, "id": profile_id,
        "name": profile_name,
        "deviceId": str(raw.get("deviceId") or "").strip()[:80],
        "iedName": ied_name, "logicalDevice": logical_device, "pointPrefix": point_prefix,
        "stationPrefix": station_prefix,
        "manufacturer": str(raw.get("manufacturer") or "YLDQ").strip()[:40],
        "description": description,
        "network": normalized_network, "report": report, "points": points,
    }


def _station_phase(station_prefix: str) -> str:
    match = re.search(r"([ABC])相", station_prefix, re.IGNORECASE)
    return match.group(1).upper() if match else ""


def generate_package(raw_profile: dict[str, Any], export_root: Path) -> dict[str, Any]:
    profile = normalize_profile(raw_profile)
    meta = {item["pointId"]: item for item in forwarding_catalog()}
    selected = [(item, meta[item["pointId"]]) for item in profile["points"] if item["enabled"]]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = export_root / f"{profile['iedName']}_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=False)
    base_name = f"{profile['iedName']}_YLDQ_V10"
    files = {
        "profile": output_dir / f"{base_name}_profile.json",
        "cfg": output_dir / f"{base_name}.cfg",
        "pointTable": output_dir / f"{base_name}_point_table.csv",
        "mapping": output_dir / f"{base_name}_mapping.txt",
        "icd": output_dir / f"{base_name}.icd",
        "manifest": output_dir / "manifest.json",
        "validation": output_dir / "校验报告.txt",
        "readme": output_dir / "部署说明.txt",
    }
    cfg_text, rows = _generate_cfg(profile, selected)
    files["profile"].write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    files["cfg"].write_text(cfg_text, encoding="utf-8", newline="\n")
    _write_point_table(files["pointTable"], rows)
    _write_mapping(files["mapping"], rows)
    files["icd"].write_text(_generate_icd(profile, selected), encoding="utf-8", newline="\n")
    validation = _validate_generated_files(files, selected, rows, cfg_text)
    files["validation"].write_text(validation["text"], encoding="utf-8", newline="\n")
    files["readme"].write_text(_deployment_readme(profile, files), encoding="utf-8")
    manifest = {"schemaVersion": SCHEMA_VERSION, "generatedAt": datetime.now().isoformat(timespec="seconds"),
                "iedName": profile["iedName"], "logicalDevice": profile["logicalDevice"],
                "selectedPointCount": len(selected), "mappingCount": len(selected) * 3,
                "validation": validation["checks"], "files": {}}
    for key, path in files.items():
        if key != "manifest":
            manifest["files"][key] = {"name": path.name, "sha256": _sha256(path)}
    files["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"profile": profile, "outputDirectory": str(output_dir), "manifest": manifest,
            "files": {key: str(path) for key, path in files.items()},
            "preview": {"cfg": "\n".join(cfg_text.splitlines()[:35])}}


def _generate_cfg(profile: dict[str, Any], selected: list[tuple[dict[str, Any], dict[str, Any]]]) -> tuple[str, list[dict[str, Any]]]:
    grouped = {"analog": [], "binary": [], "statistics": []}
    for configured, meta in selected:
        grouped[meta["category"]].append((configured, meta))
    lines = [f"MODEL({profile['iedName']}){{", f"LD({profile['logicalDevice']}){{", "LN(LLN0){", _common_ln(profile)]
    datasets = (("analog", "dsAin1", "MX", "urcbAin", "AIN", profile["report"]["analogIntegrityMs"]),
                ("binary", "dsDin1", "ST", "urcbDin", "DIN", profile["report"]["binaryIntegrityMs"]),
                ("statistics", "dsStats1", "ST", "urcbStats", "STATS", profile["report"]["statisticsIntegrityMs"]))
    for category, ds_name, fc, *_ in datasets:
        if grouped[category]:
            lines.append(f"DS({ds_name}){{")
            lines.extend(f"DE({meta['logicalNode']}${fc}${configured['objectName']});" for configured, meta in grouped[category])
            lines.append("}")
    for category, ds_name, _fc, rcb_name, suffix, integrity in datasets:
        if grouped[category]:
            lines.append(f"RC({rcb_name} {profile['iedName']}_{suffix} 0 {ds_name} 1 27 159 {profile['report']['bufferTimeMs']} {integrity});")
    lines.append("}")
    lines.extend(["LN(LPHD1){", _common_ln(profile), _lphd(), "}"])
    rows: list[dict[str, Any]] = []
    for category, ln in (("analog", "GGIO1"), ("binary", "GGIO100"), ("statistics", "GGIO200")):
        if not grouped[category]:
            continue
        lines.extend([f"LN({ln}){{", _common_ln(profile)])
        for configured, meta in grouped[category]:
            desc = _cfg_string(configured["stationName"])
            name = configured["objectName"]
            saddr = _short_address(meta)
            if category == "analog":
                lines.extend([f"DO({name} 0){{", "DA(mag 0 27 1 0 0){", f"DA(f 0 10 1 1 {saddr})=0;", "}",
                              f"DA(q 0 23 1 2 {saddr + 1});", f"DA(t 0 22 1 0 {saddr + 2});", f'DA(dU 0 21 5 0 0)="{desc}";', "}"])
                value_path = f"{profile['logicalDevice']}/{ln}${name}$mag$f"
                client_reference = f"{profile['iedName']}{profile['logicalDevice']}/{ln}.{name}.mag.f"
                functional_constraint = "MX"
            else:
                btype = 0 if category == "binary" else (9 if meta["mappingType"] == "uint32" else 4)
                default = 0
                lines.extend([f"DO({name} 0){{", f"DA(stVal 0 {btype} 0 1 {saddr})={default};",
                              f"DA(q 0 23 0 2 {saddr + 1});", f"DA(t 0 22 0 0 {saddr + 2});", f'DA(dU 0 21 5 0 0)="{desc}";', "}"])
                value_path = f"{profile['logicalDevice']}/{ln}${name}$stVal"
                client_reference = f"{profile['iedName']}{profile['logicalDevice']}/{ln}.{name}.stVal"
                functional_constraint = "ST"
            rows.append({"Modbus区域": meta["area"], "Modbus地址": meta["address"], "字数": meta["wordLength"],
                         "源点名称": meta["sourceName"], "总站名称": configured["stationName"],
                         "IEC61850引用": client_reference, "功能约束": functional_constraint,
                         "数据类型": meta["mappingType"],
                         "单位": meta["unit"], "报告组": category})
        lines.append("}")
    lines.extend(["}", "}"])
    return "\n".join(lines) + "\n", rows


def _short_address(meta: dict[str, Any]) -> int:
    """返回固件与cfg共同使用的稳定绑定键。"""
    address = int(meta["address"])
    if meta["category"] == "analog":
        return 10000 + address * 10
    if meta["category"] == "binary":
        return 20000 + address * 10
    return 30000 + address * 10


def _common_ln(profile: dict[str, Any]) -> str:
    desc = _cfg_string(profile["description"])
    vendor = _cfg_string(profile["manufacturer"])
    return "\n".join([
        "DO(Mod 0){\nDA(stVal 0 12 0 1 0)=1;\nDA(q 0 23 0 2 0);\nDA(t 0 22 0 0 0);\n}",
        "DO(Beh 0){\nDA(stVal 0 12 0 1 0)=1;\nDA(q 0 23 0 2 0);\nDA(t 0 22 0 0 0);\n}",
        "DO(Health 0){\nDA(stVal 0 12 0 1 0)=1;\nDA(q 0 23 0 2 0);\nDA(t 0 22 0 0 0);\n}",
        f'DO(NamPlt 0){{\nDA(vendor 0 20 5 0 0)="{vendor}";\nDA(swRev 0 20 5 0 0)="6.4.0";\nDA(d 0 20 5 0 0)="{desc}";\n}}',
    ])


def _lphd() -> str:
    return "DO(PhyNam 0){\nDA(vendor 0 20 5 0 0)=\"YLDQ\";\nDA(swRev 0 20 5 0 0)=\"6.4.0\";\n}\nDO(PhyHealth 0){\nDA(stVal 0 12 0 1 0)=1;\nDA(q 0 23 0 2 0);\nDA(t 0 22 0 0 0);\n}\nDO(Proxy 0){\nDA(stVal 0 0 0 1 0)=0;\nDA(q 0 23 0 2 0);\nDA(t 0 22 0 0 0);\n}"


def _generate_icd(profile: dict[str, Any], selected: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    ns = "http://www.iec.ch/61850/2003/SCL"
    ET.register_namespace("", ns)
    tag = lambda name: f"{{{ns}}}{name}"
    scl = ET.Element(tag("SCL"))
    ET.SubElement(scl, tag("Header"), {
        "version": "1.0.0", "revision": "1", "toolID": "YLDQ IEC61850配置工作台",
        "id": f"{profile['iedName']}.ICD", "nameStructure": "IEDName",
    })
    communication = ET.SubElement(scl, f"{{{ns}}}Communication")
    subnet = ET.SubElement(communication, tag("SubNetwork"), {"type": "8-MMS", "name": "StationBus"})
    cap = ET.SubElement(subnet, tag("ConnectedAP"), {"iedName": profile["iedName"], "apName": "S1"})
    address = ET.SubElement(cap, tag("Address"))
    for kind, value in (("IP", profile["network"]["ip"]), ("IP-SUBNET", profile["network"]["netmask"]),
                        ("IP-GATEWAY", profile["network"]["gateway"])):
        node = ET.SubElement(address, tag("P"), {"type": kind})
        node.text = str(value)

    ied = ET.SubElement(scl, tag("IED"), {
        "configVersion": "1.0", "desc": profile["description"], "type": "YLDQ_V10",
        "name": profile["iedName"], "manufacturer": profile["manufacturer"],
    })
    services = ET.SubElement(ied, tag("Services"))
    for service in ("DynAssociation", "GetDirectory", "GetDataObjectDefinition", "DataObjectDirectory",
                    "GetDataSetValue", "DataSetDirectory", "ReadWrite", "GetCBValues", "FileHandling"):
        ET.SubElement(services, tag(service))
    ET.SubElement(services, tag("ConfDataSet"), {"max": "8", "maxAttributes": "128"})
    ET.SubElement(services, tag("ConfReportControl"), {"max": "8"})
    ET.SubElement(services, tag("ReportSettings"), {
        "optFields": "Fix", "bufTime": "Fix", "cbName": "Fix", "rptID": "Fix",
        "trgOps": "Fix", "intgPd": "Fix", "datSet": "Fix",
    })
    access = ET.SubElement(ied, tag("AccessPoint"), {"clock": "false", "router": "false", "name": "S1"})
    server = ET.SubElement(access, tag("Server"), {"desc": "YLDQ IEC61850 server", "timeout": "60"})
    ET.SubElement(server, tag("Authentication"))
    ld = ET.SubElement(server, tag("LDevice"), {
        "desc": f"DEV-{profile['logicalDevice']}", "inst": profile["logicalDevice"],
    })
    ln0 = ET.SubElement(ld, tag("LN0"), {"inst": "", "lnType": "YLDQ_LLN0", "lnClass": "LLN0"})
    grouped = {category: [(configured, meta) for configured, meta in selected if meta["category"] == category]
               for category in ("analog", "binary", "statistics")}
    dataset_specs = (
        ("analog", "dsAin1", "遥测数据集", "MX", "1", "urcbAin", "AIN", profile["report"]["analogIntegrityMs"]),
        ("binary", "dsDin1", "遥信数据集", "ST", "100", "urcbDin", "DIN", profile["report"]["binaryIntegrityMs"]),
        ("statistics", "dsStats1", "统计数据集", "ST", "200", "urcbStats", "STATS", profile["report"]["statisticsIntegrityMs"]),
    )
    for category, ds_name, ds_desc, fc, ln_inst, *_ in dataset_specs:
        if not grouped[category]:
            continue
        dataset = ET.SubElement(ln0, tag("DataSet"), {"desc": ds_desc, "name": ds_name})
        for configured, _meta in grouped[category]:
            ET.SubElement(dataset, tag("FCDA"), {
                "doName": configured["objectName"], "lnInst": ln_inst,
                "ldInst": profile["logicalDevice"], "fc": fc, "lnClass": "GGIO",
            })
    for category, ds_name, _ds_desc, _fc, _ln_inst, rc_name, rpt_suffix, integrity in dataset_specs:
        if not grouped[category]:
            continue
        attributes = {
            "confRev": "1", "rptID": f"{profile['iedName']}_{rpt_suffix}",
            "intgPd": str(integrity), "datSet": ds_name, "name": rc_name,
        }
        rc = ET.SubElement(ln0, tag("ReportControl"), attributes)
        ET.SubElement(rc, tag("TrgOps"), {"qchg": "true", "period": "true", "dchg": "true"})
        ET.SubElement(rc, tag("OptFields"), {
            "configRef": "true", "dataSet": "true", "reasonCode": "true", "entryID": "true",
            "seqNum": "true", "dataRef": "true", "timeStamp": "true",
        })
        ET.SubElement(rc, tag("RptEnabled"), {"max": "8"})

    def add_doi(parent: ET.Element, name: str, desc: str, value_name: str | None = None,
                value: str | None = None) -> ET.Element:
        doi = ET.SubElement(parent, tag("DOI"), {"desc": desc, "name": name})
        if value_name is not None:
            dai = ET.SubElement(doi, tag("DAI"), {"name": value_name})
            ET.SubElement(dai, tag("Val")).text = value or ""
        return doi

    for name, desc, value_name, value in (("Mod", "模式", "stVal", "on"),
                                           ("Beh", "行为状态", "stVal", "on"),
                                           ("Health", "健康状态", "stVal", "Ok"),
                                           ("NamPlt", "铭牌", "dU", profile["description"])):
        add_doi(ln0, name, desc, value_name, value)
    lphd = ET.SubElement(ld, tag("LN"), {"inst": "1", "lnType": "YLDQ_LPHD1", "lnClass": "LPHD"})
    add_doi(lphd, "PhyNam", "YLDQ吸湿器", "dU", profile["description"])
    add_doi(lphd, "PhyHealth", "设备健康状态", "stVal", "Ok")
    add_doi(lphd, "Proxy", "代理设备", "stVal", "false")

    for category, ln_inst in (("analog", "1"), ("binary", "100"), ("statistics", "200")):
        if not grouped[category]:
            continue
        ln_type = f"YLDQ_GGIO{ln_inst}_{profile['logicalDevice']}"
        ln = ET.SubElement(ld, tag("LN"), {"inst": ln_inst, "lnType": ln_type, "lnClass": "GGIO"})
        for name, desc, value_name, value in (("Mod", "模式", "stVal", "on"),
                                               ("Beh", "行为状态", "stVal", "on"),
                                               ("Health", "健康状态", "stVal", "Ok"),
                                               ("NamPlt", "铭牌", "dU", profile["description"])):
            add_doi(ln, name, desc, value_name, value)
        for configured, _meta in grouped[category]:
            add_doi(ln, configured["objectName"], configured["stationName"], "dU", configured["stationName"])

    templates = ET.SubElement(scl, tag("DataTypeTemplates"))

    def add_common_dos(lnt: ET.Element) -> None:
        for name, type_id in (("Mod", "YLDQ_ENC_Mod"), ("Beh", "YLDQ_ENS_Beh"),
                              ("Health", "YLDQ_ENS_Health"), ("NamPlt", "YLDQ_LPL_NamPlt")):
            ET.SubElement(lnt, tag("DO"), {"name": name, "type": type_id})

    lnt = ET.SubElement(templates, tag("LNodeType"), {"id": "YLDQ_LLN0", "lnClass": "LLN0"})
    add_common_dos(lnt)
    lnt = ET.SubElement(templates, tag("LNodeType"), {"id": "YLDQ_LPHD1", "lnClass": "LPHD"})
    for name, type_id in (("PhyNam", "YLDQ_DPL_PhyNam"), ("PhyHealth", "YLDQ_ENS_Health"),
                          ("Proxy", "YLDQ_SPS")):
        ET.SubElement(lnt, tag("DO"), {"name": name, "type": type_id})
    for category, ln_inst in (("analog", "1"), ("binary", "100"), ("statistics", "200")):
        if not grouped[category]:
            continue
        lnt = ET.SubElement(templates, tag("LNodeType"), {
            "id": f"YLDQ_GGIO{ln_inst}_{profile['logicalDevice']}", "lnClass": "GGIO",
        })
        add_common_dos(lnt)
        for configured, meta in grouped[category]:
            if category == "analog":
                type_id = "YLDQ_MV"
            elif category == "binary":
                type_id = "YLDQ_SPS"
            else:
                type_id = "YLDQ_INS32" if meta["mappingType"] == "uint32" else "YLDQ_INS64"
            ET.SubElement(lnt, tag("DO"), {
                "desc": configured["stationName"], "type": type_id, "name": configured["objectName"],
            })

    def add_status_type(type_id: str, cdc: str, btype: str, enum_type: str | None = None) -> None:
        dot = ET.SubElement(templates, tag("DOType"), {"id": type_id, "cdc": cdc})
        attrs = {"bType": btype, "name": "stVal", "fc": "ST", "dchg": "true"}
        if enum_type:
            attrs["type"] = enum_type
        ET.SubElement(dot, tag("DA"), attrs)
        ET.SubElement(dot, tag("DA"), {"qchg": "true", "bType": "Quality", "name": "q", "fc": "ST"})
        ET.SubElement(dot, tag("DA"), {"bType": "Timestamp", "name": "t", "fc": "ST"})
        ET.SubElement(dot, tag("DA"), {"bType": "Unicode255", "name": "dU", "fc": "DC"})

    add_status_type("YLDQ_ENC_Mod", "INC", "Enum", "YLDQ_Mod")
    add_status_type("YLDQ_ENS_Beh", "INS", "Enum", "YLDQ_Beh")
    add_status_type("YLDQ_ENS_Health", "INS", "Enum", "YLDQ_Health")
    add_status_type("YLDQ_SPS", "SPS", "BOOLEAN")
    add_status_type("YLDQ_INS32", "INS", "INT32")
    add_status_type("YLDQ_INS64", "INS", "INT64")
    mv = ET.SubElement(templates, tag("DOType"), {"id": "YLDQ_MV", "cdc": "MV"})
    ET.SubElement(mv, tag("DA"), {"bType": "Struct", "type": "YLDQ_AnalogueValue", "name": "mag", "fc": "MX", "dchg": "true"})
    ET.SubElement(mv, tag("DA"), {"qchg": "true", "bType": "Quality", "name": "q", "fc": "MX"})
    ET.SubElement(mv, tag("DA"), {"bType": "Timestamp", "name": "t", "fc": "MX"})
    ET.SubElement(mv, tag("DA"), {"bType": "Unicode255", "name": "dU", "fc": "DC"})
    for type_id, cdc in (("YLDQ_LPL_NamPlt", "LPL"), ("YLDQ_DPL_PhyNam", "DPL")):
        dot = ET.SubElement(templates, tag("DOType"), {"id": type_id, "cdc": cdc})
        ET.SubElement(dot, tag("DA"), {"bType": "VisString255", "name": "vendor", "fc": "DC"})
        ET.SubElement(dot, tag("DA"), {"bType": "VisString255", "name": "swRev", "fc": "DC"})
        ET.SubElement(dot, tag("DA"), {"bType": "Unicode255", "name": "dU", "fc": "DC"})
    dat = ET.SubElement(templates, tag("DAType"), {"id": "YLDQ_AnalogueValue"})
    ET.SubElement(dat, tag("BDA"), {"name": "f", "bType": "FLOAT32"})
    for enum_id, values in (("YLDQ_Mod", ((1, "on"), (2, "blocked"), (3, "test"), (4, "test/blocked"), (5, "off"))),
                            ("YLDQ_Beh", ((1, "on"), (2, "blocked"), (3, "test"), (4, "test/blocked"), (5, "off"))),
                            ("YLDQ_Health", ((1, "Ok"), (2, "Warning"), (3, "Alarm")))):
        enum = ET.SubElement(templates, tag("EnumType"), {"id": enum_id})
        for ordinal, label in values:
            ET.SubElement(enum, tag("EnumVal"), {"ord": str(ordinal)}).text = label
    ET.indent(scl, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(scl, encoding="unicode") + "\n"


def _write_point_table(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def _write_mapping(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = ["# YLDQ IEC61850映射清单（CFG的sAddr绑定）",
             "# Modbus区域\t地址\t字数\tIEC61850引用\t源点名称\t总站名称"]
    for row in rows:
        lines.append("\t".join(str(row.get(key, "")) for key in
                                 ("Modbus区域", "Modbus地址", "字数", "IEC61850引用", "源点名称", "总站名称")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _validate_generated_files(files: dict[str, Path], selected: list[tuple[dict[str, Any], dict[str, Any]]],
                              rows: list[dict[str, Any]], cfg_text: str) -> dict[str, Any]:
    checks = {
        "cfg": bool(cfg_text.strip()) and cfg_text.count("DA(") >= len(selected) * 3,
        "mapping": len(rows) == len(selected), "icd": False, "csv": False,
    }
    try:
        root = ET.parse(files["icd"]).getroot()
        checks["icd"] = root.tag.endswith("SCL") and root.find(".//{*}IED") is not None
    except (ET.ParseError, OSError):
        pass
    try:
        with files["pointTable"].open(newline="", encoding="utf-8-sig") as stream:
            checks["csv"] = sum(1 for _ in csv.DictReader(stream)) == len(rows)
    except (OSError, csv.Error):
        pass
    if not all(checks.values()):
        raise ValueError("生成文件校验失败，请检查CFG、映射、ICD和CSV")
    text = "IEC61850配置包校验报告\n" + "\n".join(f"通过：{name.upper()}" for name in checks)
    text += "\n结论：通过\n"
    return {"passed": True, "checks": checks, "text": text}


def _deployment_readme(profile: dict[str, Any], files: dict[str, Path]) -> str:
    return (f"IED名称：{profile['iedName']}\n逻辑设备：{profile['logicalDevice']}\n"
            f"计划网络：{profile['network']['ip']} / {profile['network']['netmask']}，网关 {profile['network']['gateway']}\n\n"
            "当前版本说明：\n"
            "1. 板卡运行只使用一个cfg文件；Modbus绑定已写入cfg的sAddr字段。\n"
            "2. point_table.csv 用于总站逐点核对，ICD为总站导入初稿，正式工程需由总站工具校验。\n"
            "3. mapping.txt和point_table.csv用于现场逐点核对，ICD用于总站导入。\n"
            f"4. 现有SD部署时，只将 {files['cfg'].name} 放在SD根目录，并确保根目录没有其他cfg。\n")


def _safe_id(value: Any, label: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"{label}须以字母开头，仅含字母、数字、下划线，长度不超过{maximum}")
    return text


def _ipv4(value: Any, label: str) -> str:
    try: return str(ipaddress.IPv4Address(str(value).strip()))
    except ipaddress.AddressValueError as exc: raise ValueError(f"{label}无效") from exc


def _netmask(value: Any) -> str:
    text = str(value).strip()
    try: return str(ipaddress.IPv4Network(f"0.0.0.0/{text}").netmask)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc: raise ValueError("子网掩码无效") from exc


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    try: number = int(value)
    except (TypeError, ValueError) as exc: raise ValueError(f"{label}必须是整数") from exc
    if not minimum <= number <= maximum: raise ValueError(f"{label}范围为{minimum}–{maximum}")
    return number


def _cfg_string(value: Any) -> str:
    return str(value or "").replace('"', "'").replace("\r", " ").replace("\n", " ")[:120]


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workspace_payload(profile_path: Path) -> dict[str, Any]:
    return {"catalog": forwarding_catalog(), "profiles": load_profiles(profile_path),
            "capabilities": {"generate": True, "saveProfile": True, "probeMms": True}}


def probe_network(raw: dict[str, Any]) -> dict[str, Any]:
    ip = _ipv4(raw.get("ip"), "IP地址")
    mms_port = _integer(raw.get("port", 102), "MMS端口", 1, 65535)
    timeout = max(0.2, min(float(raw.get("timeoutSeconds", 1.2)), 5.0))
    return {
        "ip": ip, "mms": _probe_tcp(ip, mms_port, timeout),
    }


def _probe_tcp(ip: str, port: int, timeout: float) -> dict[str, Any]:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return {"reachable": True, "port": port, "message": "TCP连接成功"}
    except OSError as exc:
        return {"reachable": False, "port": port, "message": str(exc)}
