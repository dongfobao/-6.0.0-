from pathlib import Path
import json
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from iec61850_workspace import (
    default_profile,
    forwarding_catalog,
    generate_package,
    normalize_profile,
    save_profile,
    workspace_payload,
)


class Iec61850WorkspaceTests(unittest.TestCase):
    def test_catalog_matches_current_firmware_forwarding_scope(self):
        catalog = forwarding_catalog()
        self.assertEqual(len(catalog), 39)
        self.assertEqual([item["address"] for item in catalog[:4]], [0, 2, 4, 6])
        self.assertEqual([item["address"] for item in catalog[4:34]], list(range(20)) + list(range(34, 44)))
        self.assertEqual([item["address"] for item in catalog[-5:]], [32, 34, 44, 48, 52])

    def test_default_profile_uses_valid_identifiers_and_117_mappings(self):
        profile = normalize_profile(default_profile())
        self.assertEqual(profile["id"], "default_yldq_v10")
        self.assertEqual(sum(item["enabled"] for item in profile["points"]), 39)
        self.assertEqual(sum(item["enabled"] for item in profile["points"]) * 3, 117)

    def test_prefix_is_applied_to_generated_object_names(self):
        profile = default_profile()
        profile["pointPrefix"] = "A1"
        normalized = normalize_profile(profile)
        self.assertTrue(all(item["objectName"].startswith("A1") for item in normalized["points"]))

    def test_station_chinese_prefix_is_written_to_icd_desc_and_du(self):
        profile = default_profile()
        prefix = "三江变电站A相吸湿器"
        profile["stationPrefix"] = prefix
        catalog = {item["pointId"]: item for item in forwarding_catalog()}
        for point in profile["points"]:
            point["stationName"] = prefix + catalog[point["pointId"]]["sourceName"]
        with tempfile.TemporaryDirectory() as temp:
            result = generate_package(profile, Path(temp))
            root = ET.parse(result["files"]["icd"]).getroot()
            ns = {"s": "http://www.iec.ch/61850/2003/SCL"}
            doi = root.find(".//s:LN[@lnClass='GGIO'][@inst='1']/s:DOI[@name='AnIn1']", ns)
            self.assertIsNotNone(doi)
            self.assertEqual(doi.attrib["desc"], "三江变电站A相吸湿器上部温度")
            self.assertEqual(doi.find("s:DAI[@name='dU']/s:Val", ns).text, "三江变电站A相吸湿器上部温度")
            do_type = root.find(".//s:DOType[@id='YLDQ_MV']/s:DA[@name='dU']", ns)
            self.assertEqual(do_type.attrib["bType"], "Unicode255")

    def test_configuration_name_is_used_verbatim_as_device_description(self):
        profile = default_profile()
        profile["name"] = "现场自定义C相设备名称"
        profile["stationPrefix"] = "三江变电站B相吸湿器"
        profile["description"] = "三江变电站A相吸湿器 Modbus V10 转 IEC61850"
        profile["logicalDevice"] = "LD_Device_A"
        normalized = normalize_profile(profile)
        self.assertEqual(normalized["name"], "现场自定义C相设备名称")
        self.assertEqual(normalized["description"], "现场自定义C相设备名称")
        self.assertEqual(normalized["logicalDevice"], "LD_Device_B")
        with tempfile.TemporaryDirectory() as temp:
            result = generate_package(normalized, Path(temp))
            cfg = Path(result["files"]["cfg"]).read_text(encoding="utf-8")
            icd = Path(result["files"]["icd"]).read_text(encoding="utf-8")
            root = ET.fromstring(icd)
            ns = {"s": "http://www.iec.ch/61850/2003/SCL"}
            self.assertEqual(root.find(".//s:IED", ns).attrib["desc"], "现场自定义C相设备名称")
            self.assertNotIn("A相", cfg + icd)
            self.assertIn("现场自定义C相设备名称", cfg + icd)
            self.assertNotIn("Modbus V10 转 IEC61850", cfg + icd)

    def test_icd_contains_field_style_datasets_and_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            result = generate_package(default_profile(), Path(temp))
            root = ET.parse(result["files"]["icd"]).getroot()
            ns = {"s": "http://www.iec.ch/61850/2003/SCL"}
            self.assertEqual(root.find(".//s:IED", ns).attrib["name"], "YLDQ01")
            self.assertEqual(root.find(".//s:ConnectedAP/s:Address/s:P[@type='IP']", ns).text, "192.168.0.123")
            self.assertEqual(len(root.findall(".//s:LN0/s:DataSet", ns)), 3)
            self.assertEqual(len(root.findall(".//s:LN0/s:ReportControl", ns)), 3)
            self.assertIsNotNone(root.find(".//s:ReportControl[@name='urcbAin']", ns))
            self.assertIsNotNone(root.find(".//s:ReportControl[@name='urcbDin']", ns))
            self.assertIsNotNone(root.find(".//s:ReportControl[@name='urcbStats']", ns))
            self.assertIsNone(root.find(".//s:ReportControl[@buffered='true']", ns))

    def test_invalid_profile_is_rejected(self):
        profile = default_profile()
        profile["points"][1]["objectName"] = profile["points"][0]["objectName"]
        with self.assertRaisesRegex(ValueError, "不能重复"):
            normalize_profile(profile)
        profile = default_profile()
        profile["network"]["gateway"] = "10.0.0.1"
        with self.assertRaisesRegex(ValueError, "同一子网"):
            normalize_profile(profile)

    def test_generate_package_contains_runtime_and_station_files(self):
        with tempfile.TemporaryDirectory() as temp:
            result = generate_package(default_profile(), Path(temp))
            output = Path(result["outputDirectory"])
            self.assertEqual(result["manifest"]["selectedPointCount"], 39)
            self.assertEqual(result["manifest"]["mappingCount"], 117)
            self.assertTrue(all(result["manifest"]["validation"].values()))
            for path in result["files"].values():
                self.assertTrue(Path(path).is_file())
            self.assertIn("mapping", result["files"])
            self.assertIn("validation", result["files"])
            cfg = Path(result["files"]["cfg"]).read_text(encoding="utf-8")
            self.assertIn("DA(f 0 10 1 1 10000)=0;", cfg)
            self.assertIn("DA(q 0 23 1 2 10001);", cfg)
            self.assertIn("DA(t 0 22 1 0 10002);", cfg)
            self.assertIn("DA(stVal 0 0 0 1 20000)=0;", cfg)
            self.assertIn("DA(stVal 0 9 0 1 30320)=0;", cfg)
            point_table = Path(result["files"]["pointTable"]).read_text(encoding="utf-8-sig")
            self.assertIn("YLDQ01LD_Device_1/GGIO1.AnIn1.mag.f", point_table)
            self.assertIn("功能约束", point_table)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["files"]), 7)

    def test_saved_profile_is_returned_by_workspace_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profiles.json"
            profile = default_profile()
            profile["name"] = "一号设备"
            save_profile(path, profile)
            payload = workspace_payload(path)
            self.assertEqual(payload["profiles"]["profiles"][0]["name"], "一号设备")
            self.assertTrue(payload["capabilities"]["generate"])
            self.assertNotIn("applyToDevice", payload["capabilities"])


if __name__ == "__main__":
    unittest.main()
