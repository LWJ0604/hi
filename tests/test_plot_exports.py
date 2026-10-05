"""Check exported scientific figures without changing measurement values."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import matplotlib
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from research_automation.render import plots


def fixture(axis, biases):
    groups, frames = [], []
    for index, bias in enumerate(biases):
        gid = f"g{index:04d}"
        conditions = {} if bias is None else {"vg" if axis == "vd" else "vd": bias}
        groups.append({"group_id": gid, "axis": axis, "conditions": conditions,
                       "trace_id": index, "direction": "forward",
                       "fits": [{"model": "linear"}]})
        x = np.array([-1., 0., 1.])
        frames.append(pd.DataFrame({"group_id": gid, "x_v": x,
            "id_a": np.array([-2e-9, 0., 3e-9]),
            "linear_predicted_a": x * 2.5e-9, "gm_a_per_v": [2e-9] * 3,
            "ig_a": [1e-12, 0., -2e-12]}))
    return pd.concat(frames, ignore_index=True), {"groups": groups,
        "research_context": {"device_name": "new-device", "illumination": "dark"}}


class PlotExportTests(unittest.TestCase):
    def render(self, curves, summary):
        figures = {}

        def capture(figure, path, **options):
            self.assertEqual(options["dpi"], 300)
            figures[Path(path).name] = figure

        with patch.object(Figure, "savefig", capture):
            files = plots(curves, summary, Path("/unused"))
        self.assertEqual(set(files), set(figures))
        return figures

    def test_all_export_panels_use_theme_units_and_preserve_log_values(self):
        curves, summary = fixture("vg", [2.])
        before_curves, before_summary = curves.copy(deep=True), copy.deepcopy(summary)
        old_width = matplotlib.rcParams["lines.linewidth"]
        figures = self.render(curves, summary)
        for figure in figures.values():
            self.assertEqual(figure.get_facecolor(), (1., 1., 1., 1.))
            for ax in figure.axes:
                self.assertIn("voltage", ax.get_xlabel())
                self.assertIn("(V)", ax.get_xlabel())
                self.assertTrue("(A)" in ax.get_ylabel() or "(A/V)" in ax.get_ylabel())
                self.assertTrue(all(line.get_linewidth() == 3 for line in ax.lines))
        transfer = figures["g0000_transfer.png"]
        self.assertEqual(transfer.axes[0].get_yscale(), "log")
        self.assertEqual(transfer.axes[2].get_yscale(), "log")
        narrow_range = transfer.axes[2]
        narrow_range.set_ylim(2e-11, 6e-11)
        from research_automation.plot_style import format_axes
        format_axes(narrow_range, "vg", "Gate current (A)")
        narrow_range.figure.canvas.draw()
        self.assertTrue(any("p" in label.get_text() for label in narrow_range.get_yticklabels()))
        np.testing.assert_equal(transfer.axes[0].lines[0].get_ydata(), [2e-9, np.nan, 3e-9])
        np.testing.assert_equal(transfer.axes[2].lines[0].get_ydata(), [1e-12, np.nan, 2e-12])
        pd.testing.assert_frame_equal(curves, before_curves)
        self.assertEqual(summary, before_summary)
        self.assertEqual(matplotlib.rcParams["lines.linewidth"], old_width)

    def test_voltage_colors_match_repeated_traces_and_ignore_group_order(self):
        curves, summary = fixture("vd", [20., -1., 20., 5.])
        first = self.render(curves, summary)["overview_vd.png"].axes[0]
        colors = {line.get_label(): line.get_color() for line in first.lines}
        self.assertEqual(colors["VG = 20 V / g0000"], colors["VG = 20 V / g0002"])
        low, high = colors["VG = -1 V / g0001"], colors["VG = 20 V / g0000"]
        self.assertGreater(low[2], .9)  # purple end
        self.assertEqual(tuple(high[:3]), (1., 0., 0.))  # red end
        summary["groups"].reverse()
        second = self.render(curves, summary)["overview_vd.png"].axes[0]
        self.assertEqual(colors, {line.get_label(): line.get_color() for line in second.lines})
        np.testing.assert_equal(first.lines[0].get_ydata(), [-2e-9, 0., 3e-9])

    def test_many_curves_show_correct_fixed_voltage_colorbar(self):
        curves, summary = fixture("vg", list(range(-5, 6)))
        overview = self.render(curves, summary)["overview_vg.png"]
        self.assertEqual(len(overview.axes), 2)
        colorbar = overview.axes[1]
        self.assertIn("Drain voltage", colorbar.get_ylabel())
        self.assertIn("(V)", colorbar.get_ylabel())
        self.assertEqual(colorbar.get_ylim(), (-5., 5.))
        self.assertEqual(len(overview.axes[0].lines), 11)

    def test_unknown_or_single_bias_does_not_imply_voltage_range(self):
        for biases in ([None] * 11, [2.] * 11):
            curves, summary = fixture("vd", biases)
            overview = self.render(curves, summary)["overview_vd.png"]
            self.assertEqual(len(overview.axes), 1)
            self.assertEqual(len({tuple(line.get_color()) for line in overview.axes[0].lines}), 1)

    def test_negative_ticks_on_axes_and_colorbar_use_supported_ascii_minus(self):
        from research_automation.plot_style import RC
        curves, summary = fixture('vd', list(range(-20, 21, 2)))
        with matplotlib.rc_context(RC):
            overview = self.render(curves, summary)['overview_vd.png']
            overview.canvas.draw()
            x = [label.get_text() for label in overview.axes[0].get_xticklabels()]
            y = [label.get_text() for label in overview.axes[0].get_yticklabels()]
            colorbar = [label.get_text() for label in overview.axes[1].get_yticklabels()]
            for labels in (x, y, colorbar):
                self.assertTrue(any('-' in text for text in labels), labels)
                self.assertFalse(any('\N{MINUS SIGN}' in text for text in labels), labels)
        np.testing.assert_array_equal(curves[curves['group_id']=='g0000']['id_a'].to_numpy(),[-2e-9,0.,3e-9])


if __name__ == "__main__":
    unittest.main()
