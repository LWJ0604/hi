"""Synthetic fixtures reproducing uploaded schema; no private raw data in CI."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from research_automation.analysis import analyze
from research_automation.config import Config, DEFAULT
from research_automation.ingest import column_info, load_measurements, normalize


class KeithleyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.options = copy.deepcopy(DEFAULT)
        self.cfg = self.config()

    def tearDown(self):
        self.temp.cleanup()

    def config(self):
        path = self.root / "config.json"
        path.write_text(json.dumps(self.options), encoding="utf-8")
        return Config(path)

    def test_exact_chart_helper_copies_use_settings_and_keep_gate_current(self):
        f=pd.DataFrame(np.column_stack([[-1,0,1],[1e-10,2e-10,3e-10],[1e-12]*3,[-1,0,1],[1e-10,2e-10,3e-10]]),
            columns=['GateV','DrainI','GateI','GateV','DrainI'])
        sheets,_=load_measurements(self.book(f,drain_bias=-.5),self.cfg,{})
        self.assertEqual(len(sheets),1)
        self.assertEqual(sheets[0]['data']['vd'].unique().tolist(),[-.5])
        self.assertEqual(len(sheets[0]['duplicate_export_columns']),2)
        self.assertIn('ig',sheets[0]['data'])

    def test_different_repeated_currents_without_vds_remain_rejected(self):
        f=pd.DataFrame([[-1,1e-10,2e-10],[0,2e-10,3e-10],[1,3e-10,4e-10]],columns=['GateV','DrainI','DrainI'])
        with self.assertRaisesRegex(ValueError,'missing/conflicting Vds'):
            load_measurements(self.book(f),self.cfg,{})

    def test_indexed_chart_copy_does_not_hide_other_traces(self):
        f=pd.DataFrame([[-1,1e-10,-1,2e-10,1e-10],[0,2e-10,0,3e-10,2e-10],[1,3e-10,1,4e-10,3e-10]],
            columns=['GateV(1)','DrainI(1)','GateV(2)','DrainI(2)','DrainI(1)'])
        sheets,_=load_measurements(self.book(f),self.cfg,{})
        self.assertEqual(len(sheets),2)
        self.assertEqual(len(sheets[0]['duplicate_export_columns']),1)
        self.assertNotEqual(sheets[0]['data']['id'].tolist(),sheets[1]['data']['id'].tolist())

    def test_forward_only_chart_copy_preserves_entire_reverse_sweep(self):
        f=pd.DataFrame([[-1,1e-10,1e-12,-1,1e-10],[0,2e-10,1e-12,0,2e-10],[1,3e-10,1e-12,1,3e-10],
            [0,4e-10,1e-12,np.nan,np.nan],[-1,5e-10,1e-12,np.nan,np.nan]],columns=['GateV','DrainI','GateI','GateV','DrainI'])
        sheets,_=load_measurements(self.book(f),self.cfg,{})
        self.assertEqual(len(sheets),1);self.assertEqual(len(sheets[0]['data']),5)
        self.assertEqual(sheets[0]['data']['id'].iloc[-1],5e-10)

    def book(self, frame, axis="vg", drain_bias=2):
        settings = pd.DataFrame([
            ["Test Name", "Test@misleading99", None, None],
            ["KTEI Version", "V8.2", None, None],
            ["Last Executed", "09/24/2026 02:27:29", None, None],
            ["Device Terminal", "Drain", "Source", "Gate"],
            ["Name", "DrainV", "SourceV", "GateV"],
            ["Forcing Function", "Voltage Bias" if axis == "vg" else "Voltage Sweep", "Common", "Voltage Sweep" if axis == "vg" else "Voltage Step"],
            ["Start/Level", drain_bias if axis == "vg" else -1, None, -2 if axis == "vg" else 0],
            ["Stop", None if axis == "vg" else 1, None, 2],
            ["Compliance", .1, .105, 1.1e-7],
            ["Measure I", "Measured", None, "Measured" if axis == "vg" else "No"],
            ["Measure V", "No" if axis == "vg" else "Programmed", None, "Programmed"],
        ])
        path = self.root / "Id-Vg@99V.xlsx"
        with pd.ExcelWriter(path) as writer:
            frame.to_excel(writer, sheet_name="Data", index=False)
            pd.DataFrame().to_excel(writer, sheet_name="Calc", index=False)
            settings.to_excel(writer, sheet_name="Settings", index=False, header=False)
        return path

    def transfer(self):
        x = np.linspace(-2, 2, 9)
        return pd.DataFrame({"DrainI": (x + 3) * 1e-8, "GateI": 1e-12, "GateV": x, "GM": ["#REF"] + [1e-8] * 8, "GM2": ["#REF", "#REF"] + [0] * 7})

    def wide(self):
        x = np.linspace(-1, 1, 9)
        return pd.DataFrame({"DrainI(1)": 1e-8 * x, "DrainV(1)": x, "GateV(1)": 0., "DrainI(2)": 2e-8 * x, "DrainV(2)": x, "GateV(2)": 0.})

    def test_trace_suffix_is_not_a_unit(self):
        self.assertEqual(column_info("DrainI(44)", self.cfg)[:2], ("id", 1))
        self.assertEqual(column_info("DrainI (nA)(2)", self.cfg)[:2], ("id", 1e-9))

    def test_wide_traces_with_same_gate_stay_independent(self):
        path = self.book(self.wide(), "vd")
        sheets, ignored = load_measurements(path, self.cfg, {})
        summary, curves = analyze(sheets, self.cfg)
        self.assertEqual(len(summary["groups"]), 2)
        self.assertEqual([g["trace_id"] for g in summary["groups"]], [1, 2])
        self.assertEqual([g["n"] for g in summary["groups"]], [9, 9])
        self.assertEqual({g["direction"] for g in summary["groups"]}, {"forward"})
        self.assertEqual(len(curves), 18)
        self.assertTrue(all(c["status"] == "SKIP" for c in summary["qc"]["checks"] if c["code"] == "hysteresis"))
        self.assertEqual({s["sheet"] for s in ignored}, {"Calc", "Settings"})
        exported = pd.read_excel(path, sheet_name="Data")
        np.testing.assert_array_equal(sheets[0]["data"]["id"], exported["DrainI(1)"])
        np.testing.assert_array_equal(sheets[1]["data"]["id"], exported["DrainI(2)"])

    def test_fixed_drain_bias_comes_from_settings_not_filename(self):
        sheets, _ = load_measurements(self.book(self.transfer()), self.cfg, {})
        summary, _ = analyze(sheets, self.cfg)
        self.assertEqual(summary["axis"], "vg")
        self.assertEqual(summary["groups"][0]["conditions"], {"vd": 2.})
        self.assertEqual(sheets[0]["column_mapping"]["vd"]["origin"], "programmed_bias")

    def test_formula_errors_do_not_drop_measurement_rows(self):
        sheets, _ = load_measurements(self.book(self.transfer()), self.cfg, {})
        self.assertEqual(sheets[0]["invalid_rows"], 0)
        self.assertEqual(len(sheets[0]["data"]), 9)
        self.assertEqual(sheets[0]["ignored_derived_columns"], ["GM", "GM2"])

    def test_transfer_derivative_and_ratio_use_measured_range(self):
        sheets, _ = load_measurements(self.book(self.transfer()), self.cfg, {})
        summary, curves = analyze(sheets, self.cfg)
        metrics = summary["groups"][0]["transfer_metrics"]
        np.testing.assert_allclose(curves["gm_a_per_v"], 1e-8, rtol=1e-12)
        self.assertAlmostEqual(metrics["current_range_ratio_abs"], 5.)
        self.assertEqual(summary["groups"][0]["rectification"]["status"], "SKIP")
        self.assertEqual({fit["model"] for fit in summary["groups"][0]["fits"]}, {"linear"})

    def test_transfer_without_settings_does_not_guess_bias_from_filename(self):
        path = self.root / "Id-Vg@99V.csv"
        self.transfer().to_csv(path, index=False)
        sheets, _ = load_measurements(path, self.cfg, {})
        summary, _ = analyze(sheets, self.cfg)
        self.assertEqual(summary["axis"], "vg")
        self.assertEqual(summary["groups"][0]["conditions"], {})

    def test_manual_axis_is_respected(self):
        self.options["analysis"]["auto_detect_axis"] = False
        self.cfg = self.config()
        frame = self.transfer()
        frame["DrainV"] = 2.
        sheets, _ = load_measurements(self.book(frame), self.cfg, {})
        self.assertEqual(sheets[0]["axis"], "vd")

    def test_excel_numeric_cells_keep_original_precision(self):
        current = np.array([np.nextafter(1e-7, np.inf), np.nextafter(2e-7, np.inf), np.nextafter(3e-7, np.inf)])
        frame = pd.DataFrame({"DrainV": [-1., 0., 1.], "DrainI": current})
        sheet = normalize(frame, "Data", 0, self.cfg, {})
        np.testing.assert_array_equal(sheet["data"]["id"], current)

    def test_old_settings_gain_auto_detection_defaults(self):
        self.options["analysis"].pop("auto_detect_axis")
        self.options["analysis"].pop("transfer_models")
        self.options["ingest"].pop("extensions")
        self.options["ingest"].pop("exclude_globs")
        self.cfg = self.config()
        self.assertTrue(self.cfg.data["analysis"]["auto_detect_axis"])
        self.assertEqual(self.cfg.data["analysis"]["transfer_models"], ["linear"])

    def test_gate_leakage_uses_gate_current(self):
        frame = self.transfer()
        frame["GateI"] = 2e-7
        sheets, _ = load_measurements(self.book(frame), self.cfg, {})
        summary, _ = analyze(sheets, self.cfg)
        checks = [c for c in summary["qc"]["checks"] if c["code"] == "gate_leakage"]
        self.assertEqual(checks[0]["status"], "WARN")
        self.assertAlmostEqual(checks[0]["value"], 2e-7)


if __name__ == "__main__":
    unittest.main()
