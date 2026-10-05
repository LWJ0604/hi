from research_automation import __version__
import copy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

import httpx
import numpy as np
import pandas as pd

from test_system import Base
from research_automation.ai import interpret
from research_automation.config import Config
from research_automation.ingest import load_measurements
from research_automation.organization import component, dates_in, identify
from research_automation.pipeline import scan
from research_automation.reports import weekly
from research_automation.util import filename_hints, parse_filename


SUMMARY = {"axis": "vg", "groups": [{"axis": "vg", "x_min_v": -40., "x_max_v": 40., "conditions": {"vd": 2.}}]}


class ClassificationTests(Base):
    def context(self, relative, instrument=None, summary=None):
        return identify(relative, parse_filename(Path(relative).name), instrument or {}, summary or copy.deepcopy(SUMMARY), self.cfg)

    def test_user_device_date_layout(self):
        value = self.context("drain-fold/2026-09-23/Id-Vg_Vd=2V_dark.xls")
        self.assertEqual(value["device_name"], "drain-fold")
        self.assertEqual(value["fold"], "drain fold")
        self.assertEqual(value["measurement_date"], "2026-09-23")
        self.assertEqual(value["vault_subfolder"], "drain-fold/2026-09-23/Id-Vg__dark__Vd=2V")
        self.assertEqual(value["warnings"], [])

    def test_unmarked_filename_remains_unknown_with_no_default_evidence(self):
        value = self.context("drain-fold/2026-09-23/Id-Vg_Vd=2V.xls")
        self.assertEqual(value["illumination"], "unknown")
        self.assertEqual(value["illumination_source"], "unavailable/unmarked_filename")
        self.assertIn("Id-Vg__unknown__Vd=2V", value["vault_subfolder"])
        self.assertEqual(value["evidence"]["illumination"], [])

    def test_filename_lighting_conflicts_are_retained(self):
        value = self.context("drain-fold/2026-09-23/dark/Id-Vg_Vd=2V_LIGHT.xls")
        self.assertEqual(value["illumination"], "conflict")
        self.assertEqual(value["illumination_source"], "filename")
        self.assertTrue(any("illumination 후보 불일치" in warning for warning in value["warnings"]))

    def test_unmarked_filename_unknown_even_in_light_folder(self):
        value = self.context("drain-fold/2026-09-23/light/Id-Vg_Vd=2V.xls")
        self.assertEqual(value["illumination"], "unknown")
        self.assertEqual(value["illumination_source"], "unavailable/unmarked_filename")
        self.assertEqual(value["condition_label"], "Id-Vg__unknown__Vd=2V")
        self.assertTrue(value["evidence"]["illumination"])

    def test_explicit_filename_light_and_dark_are_preserved(self):
        for marker, expected in (("DARK", "dark"), ("with light", "light")):
            value = self.context(f"새 소자/2026-09-23/IdVg_Vd=2V_{marker}.xls")
            self.assertEqual(value["illumination"], expected)
            self.assertEqual(value["illumination_source"], "filename")

    def test_devices_are_open_ended(self):
        for name in ("center-fold", "source fold", "sample-03", "새 소자 이름", "light-device"):
            value = self.context(f"{name}/2026-09-23/IdVg_Vd=2V_dark.xls")
            self.assertEqual(value["device_name"], name)
            self.assertTrue(value["vault_subfolder"].startswith(name + "/"))
            self.assertEqual(value["illumination"], "dark")

    def test_full_device_hierarchy_preserved(self):
        a = self.context("ReS2/sample-03/center-fold/2026-09-23/IdVg_dark.xls")
        b = self.context("MoS2/sample-03/center-fold/2026-09-23/IdVg_dark.xls")
        self.assertEqual(a["device_type"], "ReS2")
        self.assertEqual(a["device_name"], "center-fold")
        self.assertEqual(a["device_path"], "ReS2/sample-03/center-fold")
        self.assertNotEqual(a["vault_subfolder"], b["vault_subfolder"])

    def test_folder_date_and_separate_equipment_clock(self):
        value = self.context("drain-fold/2026-09-23/IdVg_dark.xls", {"measurement_timestamp_raw": "09/24/2026 13:02:00"})
        self.assertEqual(value["measurement_date"], "2026-09-23")
        self.assertFalse(any("measurement_date 후보 불일치" in warning for warning in value["warnings"]))
        self.assertEqual({item["value"] for item in value["evidence"]["measurement_date"]}, {"2026-09-23"})

    def test_equipment_clock_is_not_actual_measurement_date(self):
        value = self.context("sample-03/IdVg_dark.xls", {"measurement_timestamp_raw": "09/24/2026 13:02:00"})
        self.assertIsNone(value["measurement_date"])
        self.assertEqual(value["instrument_timestamp_raw"], "09/24/2026 13:02:00")
        value = self.context("sample-03/IdVg_dark.xls")
        self.assertIsNone(value["measurement_date"])
        self.assertIn("측정일 미확인", value["vault_subfolder"])

    def test_dates_are_strict_and_year_is_required(self):
        for text in ("2026-02-30", "09-23", "260923"):
            self.assertEqual(dates_in(text), [])
        for text in ("20260923", "2026.9.23", "2026년 9월 23일"):
            self.assertEqual(dates_in(text), ["2026-09-23"])
        value = self.context("sample-03/2026/09/23/IdVg_dark.xls")
        self.assertEqual(value["measurement_date"], "2026-09-23")
        self.assertEqual(value["device_path"], "sample-03")

    def test_filename_bias_conflict_uses_measured_value(self):
        value = self.context("center-fold/2026-09-23/Id-Vg@99V_dark.xls")
        self.assertEqual(value["fixed_conditions_v"], {"vd": [2.]})
        self.assertIn("Vd=2V", value["condition_label"])
        self.assertTrue(any("파일명 Vd=99" in warning for warning in value["warnings"]))

    def test_actual_axis_precedes_filename_type(self):
        value = self.context("sample-03/2026-09-23/Id-Vd_dark.xls")
        self.assertEqual(value["measurement_type"], "Id-Vg")
        self.assertTrue(any("파일명 유형" in warning for warning in value["warnings"]))

    def test_manual_path_capture_override(self):
        self.data["organization"]["path_rules"] = [r"^(?P<device_type>[^/]+)/(?P<device_name>[^/]+)/(?P<measurement_date>\d{4}-\d{2}-\d{2})/"]
        self.cfg = self.configure()
        value = self.context("custom material/새 소자/2026-09-23/IdVg_dark.xls")
        self.assertEqual(value["device_name"], "새 소자")
        self.assertEqual(value["device_type"], "custom material")
        self.assertEqual(value["device_name_source"], "path_rules[0]")

    def test_invalid_capture_and_regex_rejected(self):
        for rule in ("[", "(?P<unsupported>.*)"):
            self.data["organization"]["path_rules"] = [rule]
            with self.assertRaises(ValueError):
                self.configure()

    def test_old_config_default_backfill(self):
        self.data.pop("organization")
        self.assertEqual(self.configure().data["organization"], {"path_rules": []})

    def test_path_component_is_windows_and_wikilink_safe(self):
        self.assertEqual(component("CON"), "_CON")
        value = component('../device:[x]#|*?/\\')
        self.assertIsNone(re.search(r'[\\/:*?"<>|\[\]#]', value))
        self.assertFalse(value.startswith("."))

    def test_no_false_device_from_admin_folders(self):
        value = self.context("vps 측정/측정일 미확인/날짜 미상_루트 파일/원본/IdVg_dark.xls")
        self.assertIsNone(value["device_name"])


class OrganizationPipelineTests(Base):
    def transfer(self, folder, filename="Id-Vg_Vd=2V_dark.csv"):
        source = self.cfg.paths["inbox"] / folder / filename
        source.parent.mkdir(parents=True, exist_ok=True)
        x = np.linspace(-2, 2, 9)
        pd.DataFrame({"GateV": x, "DrainI": (x + 3) * 1e-9, "GateI": 1e-12}).to_csv(source, index=False)
        return source

    def test_filename_bias_fallback_has_provenance(self):
        source = self.transfer("sample-03/2026-09-23", "Id-Vg@2V_dark.csv")
        metadata = parse_filename(source.name)
        metadata["_filename_hints"] = filename_hints(source.name)
        sheets, _ = load_measurements(source, self.cfg, metadata)
        self.assertEqual(sheets[0]["data"]["vd"].unique().tolist(), [2.])
        self.assertEqual(sheets[0]["column_mapping"]["vd"]["origin"], "filename_bias")
        self.assertNotIn("vd", filename_hints("I-V#1@1 with light.xls"))

    def test_nested_notes_assets_properties_and_weekly_links(self):
        self.transfer("drain-fold/2026-09-23")
        self.transfer("center-fold/2026-09-23", "IdVg_Vd=3V_light.csv")
        self.transfer("새 소자/2026-09-24", "IdVg_Vd=2V_dark.csv")
        outcome = scan(self.cfg)
        self.assertEqual(outcome["counts"]["completed"], 3)
        for entry in outcome["files"]:
            note = Path(entry["note"])
            text = note.read_text(encoding="utf-8")
            self.assertIn('measurement_date: "2026-09-', text)
            self.assertIn("device_name:", text)
            for link in re.findall(r'\[\[([^\]|]+)(?:\|[^\]]*)?\]\]', text):
                self.assertTrue((self.cfg.paths["vault"] / link).exists(), link)
            result = json.loads((self.cfg.paths["analysis"] / "runs" / ("v" + __version__) / entry["job_id"] / "result.json").read_text())
            self.assertEqual(result["vault_note_relative_path"], note.relative_to(self.cfg.paths["vault"]).as_posix())
            table = pd.read_csv(self.cfg.paths["analysis"] / "runs" / ("v" + __version__) / entry["job_id"] / "normalized.csv")
            self.assertEqual(table["device_name"].unique().tolist(), [result["research_context"]["device_name"]])
            self.assertEqual(table["vd"].unique().tolist(), result["research_context"]["fixed_conditions_v"]["vd"])
        from research_automation.science_exports import catalog_path
        catalog = catalog_path(self.cfg).read_text()
        self.assertIn("새 소자", catalog)
        self.assertIn("center-fold", catalog)
        report = weekly(self.cfg)
        text = Path(report["report"]).read_text()
        self.assertIn("Vd=3V", text)
        self.assertIn("2026-09-23", text)
        for link in re.findall(r'\[\[([^\]|]+)', text):
            self.assertTrue((self.cfg.paths["vault"] / (link + ".md")).exists())
        self.assertEqual(scan(self.cfg)["counts"]["unchanged"], 3)

    def test_move_to_new_device_reclassifies_without_touching_source(self):
        source = self.transfer("drain-fold/2026-09-23")
        original = source.read_bytes()
        first = scan(self.cfg)
        new = self.cfg.paths["inbox"] / "new device" / "2026-09-24" / source.name
        new.parent.mkdir(parents=True)
        source.rename(new)
        second = scan(self.cfg)
        self.assertEqual(second["counts"]["completed"], 1)
        self.assertIn("new device/2026-09-24", second["files"][0]["note"])
        self.assertTrue(Path(first["files"][0]["note"]).exists())
        self.assertEqual(new.read_bytes(), original)

    def test_ai_gets_device_context_without_source_paths(self):
        self.transfer("drain-fold/2026-09-23")
        outcome = scan(self.cfg)
        summary = json.loads((self.cfg.paths["analysis"] / "runs" / ("v" + __version__) / outcome["files"][0]["job_id"] / "result.json").read_text())
        self.data["science"]["offline"] = False  # Mock HTTP only: legacy opt-in contract
        self.data["ai"]["enabled"] = True
        self.cfg = self.configure()
        seen = []
        def transport(request):
            seen.append(json.loads(request.content))
            return httpx.Response(401)
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), httpx.Client(transport=httpx.MockTransport(transport)) as client:
            interpret(summary, self.cfg, client)
        payload = json.loads(seen[0]["input"])
        self.assertEqual(payload["research_context"]["device_name"], "drain-fold")
        self.assertEqual(payload["research_context"]["measurement_date"], "2026-09-23")
        self.assertNotIn("source_relative_path", seen[0]["input"])
        self.assertNotIn(str(self.cfg.paths["inbox"]), seen[0]["input"])


if __name__ == "__main__":
    unittest.main()
