from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from iec61850_station import StationManager, parse_icd  # noqa: E402


SAMPLE_ICD = """<?xml version="1.0" encoding="UTF-8"?>
<SCL xmlns="http://www.iec.ch/61850/2003/SCL">
  <Communication><SubNetwork name="LAN"><ConnectedAP iedName="DEV1" apName="S1"><Address><P type="IP">192.168.0.123</P></Address></ConnectedAP></SubNetwork></Communication>
  <IED name="DEV1" desc="三江变电站A相吸湿器"><AccessPoint name="S1"><Server><LDevice inst="LD1"><LN0 lnClass="LLN0" inst="" lnType="T_LLN0">
    <DataSet name="dsAin"><FCDA ldInst="LD1" lnClass="GGIO" lnInst="1" doName="AnIn1" fc="MX"/></DataSet>
    <ReportControl name="urcbAin" rptID="DEV1_AIN" datSet="dsAin" intgPd="10000"/>
  </LN0><LN lnClass="GGIO" inst="1" lnType="T_GGIO"><DOI name="AnIn1" desc="三江变电站A相吸湿器上部温度"><DAI name="dU"><Val>三江变电站A相吸湿器上部温度</Val></DAI></DOI></LN></LDevice></Server></AccessPoint></IED>
  <DataTypeTemplates><LNodeType id="T_LLN0" lnClass="LLN0"/><LNodeType id="T_GGIO" lnClass="GGIO"><DO name="AnIn1" type="T_MV"/></LNodeType><DOType id="T_MV" cdc="MV"><DA name="mag" bType="Struct" type="T_AV" fc="MX"/><DA name="q" bType="Quality" fc="MX"/><DA name="t" bType="Timestamp" fc="MX"/><DA name="dU" bType="Unicode255" fc="DC"/></DOType><DAType id="T_AV"><BDA name="f" bType="FLOAT32"/></DAType></DataTypeTemplates>
</SCL>"""


class Iec61850StationParserTests(unittest.TestCase):
    def test_parse_point_reference_and_chinese_name(self) -> None:
        payload = parse_icd(SAMPLE_ICD, "sample.icd")
        self.assertEqual(payload["host"], "192.168.0.123")
        self.assertEqual(payload["iedName"], "DEV1")
        self.assertEqual(payload["points"][0]["displayName"], "三江变电站A相吸湿器上部温度")
        self.assertEqual(payload["points"][0]["reference"], "DEV1LD1/GGIO1.AnIn1.mag.f")
        self.assertEqual(payload["points"][0]["qualityReference"], "DEV1LD1/GGIO1.AnIn1.q")
        self.assertEqual(payload["rcbs"][0]["reference"], "DEV1LD1/LLN0.RP.urcbAin")

    def test_import_removes_protocol_suffix_from_device_name(self) -> None:
        content = SAMPLE_ICD.replace(
            'desc="三江变电站A相吸湿器"',
            'desc="三江变电站C相吸湿器 Modbus V10 转 IEC61850"',
            1,
        )
        payload = parse_icd(content, "sample.icd")
        self.assertEqual(payload["displayName"], "三江变电站C相吸湿器")

    def test_model_comparison_detects_different_online_logical_device(self) -> None:
        manager = StationManager.__new__(StationManager)
        device = {
            "logicalDevices": [{"name": "kaokaoLD_Device_F", "logicalNodes": [{"name": "GGIO1"}]}],
            "onlineModel": {"logicalDevices": [{"name": "SANJIANGBIANLD_Device_A", "logicalNodes": [{"name": "GGIO1"}]}]},
        }
        comparison = manager._compare_model(device)
        self.assertFalse(comparison["matched"])
        self.assertEqual(comparison["missingLogicalDevices"], ["kaokaoLD_Device_F"])
        self.assertEqual(comparison["extraLogicalDevices"], ["SANJIANGBIANLD_Device_A"])

    def test_same_endpoint_cannot_be_connected_twice(self) -> None:
        manager = StationManager.__new__(StationManager)
        manager.lock = threading.RLock()
        manager.workers = {}
        manager.payload = {"devices": [
            {"id": "first", "displayName": "设备一", "host": "192.168.0.16", "port": 102, "status": "online"},
            {"id": "second", "displayName": "设备二", "host": "192.168.0.16", "port": 102, "status": "offline"},
        ]}
        with self.assertRaisesRegex(ValueError, "请先断开重复设备"):
            manager.connect("second")

    def test_successful_read_clears_previous_error(self) -> None:
        manager = StationManager.__new__(StationManager)
        reference = "kaokaoLD_Device_F/GGIO1.AnIn1.mag.f"
        device = {
            "points": [{"reference": reference, "qualityReference": "", "timeReference": ""}],
            "values": {reference: {"ok": False, "error": 3, "stale": True}},
        }
        manager._apply_values(device, [{"reference": reference, "ok": True, "value": 26.9}], "poll")
        current = device["values"][reference]
        self.assertTrue(current["ok"])
        self.assertFalse(current["stale"])
        self.assertNotIn("error", current)

    def test_poll_pauses_when_any_report_is_enabled(self) -> None:
        class FakeWorker:
            def __init__(self) -> None:
                self.commands = []

            def send(self, command):
                self.commands.append(command)

        manager = StationManager.__new__(StationManager)
        worker = FakeWorker()
        device = {
            "lastPollSent": 0,
            "points": [
                {"reference": "IEDLD/GGIO1.AnIn1.mag.f", "qualityReference": "", "timeReference": "", "fc": "MX", "dataset": "dsAin"},
                {"reference": "IEDLD/GGIO1.Ind1.stVal", "qualityReference": "", "timeReference": "", "fc": "ST", "dataset": "dsDin"},
            ],
            "rcbs": [
                {"reference": "IEDLD/LLN0.RP.urcbAin", "dataset": "dsAin"},
                {"reference": "IEDLD/LLN0.RP.urcbDin", "dataset": "dsDin"},
            ],
            "reportStates": {"IEDLD/LLN0.RP.urcbAin": {"status": "enabled"}},
        }

        manager._send_read_batch(device, worker)

        self.assertEqual(worker.commands, [])
        self.assertGreater(device["lastPollSent"], 0)

    def test_poll_sends_nothing_when_all_datasets_have_enabled_reports(self) -> None:
        class FakeWorker:
            def __init__(self) -> None:
                self.commands = []

            def send(self, command):
                self.commands.append(command)

        manager = StationManager.__new__(StationManager)
        worker = FakeWorker()
        device = {
            "lastPollSent": 0,
            "points": [
                {"reference": "IEDLD/GGIO1.AnIn1.mag.f", "qualityReference": "", "timeReference": "", "fc": "MX", "dataset": "dsAin"},
            ],
            "rcbs": [{"reference": "IEDLD/LLN0.RP.urcbAin", "dataset": "dsAin"}],
            "reportStates": {"IEDLD/LLN0.RP.urcbAin": {"status": "enabled"}},
        }

        manager._send_read_batch(device, worker)

        self.assertEqual(worker.commands, [])
        self.assertGreater(device["lastPollSent"], 0)

    def test_reject_non_scl_document(self) -> None:
        with self.assertRaisesRegex(ValueError, "根节点不是 SCL"):
            parse_icd("<root/>", "bad.icd")


if __name__ == "__main__":
    unittest.main()
