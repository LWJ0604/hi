"""Shared export theme. Values remain in SI units; only tick text is formatted."""
from functools import wraps
import math

import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.ticker import AutoMinorLocator, EngFormatter, LogLocator, NullFormatter


LINE_WIDTH = 3.0  # points, independent of export DPI
EXPORT_DPI = 300
RAINBOW = LinearSegmentedColormap.from_list(
    "measurement_rainbow", ["#d000ff", "#6500ff", "#004cff", "#00d5ff",
                            "#00c957", "#d8ef00", "#ff9900", "#ff0000"]
)
RC = {
    "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "savefig.transparent": False,
    "lines.linewidth": LINE_WIDTH, "lines.markersize": 3,
    "axes.edgecolor": "black", "axes.linewidth": 1.5,
    "axes.labelsize": 11, "axes.titlesize": 12, "font.size": 10,
    "font.family": "sans-serif",
    "font.sans-serif": ["Malgun Gothic", "Noto Sans CJK KR", "Noto Sans CJK JP", "Noto Sans KR", "NanumGothic", "DejaVu Sans"],
    # Some Windows font installations lack U+2212. This covers ScalarFormatter,
    # EngFormatter and colorbar ticks without changing signed measurement values.
    "axes.unicode_minus": False,
    # LogFormatterMathtext also needs a font with the mathematical minus.
    # Keep Korean labels in the sans-serif stack, but use bundled DejaVu for math.
    "mathtext.rm": "DejaVu Sans", "mathtext.fontset": "dejavusans",
    "xtick.direction": "in", "ytick.direction": "in",
    "xtick.top": True, "ytick.right": True,
    "xtick.major.width": 1.2, "ytick.major.width": 1.2,
    "xtick.minor.width": 1, "ytick.minor.width": 1,
    "xtick.major.size": 5, "ytick.major.size": 5,
    "xtick.minor.size": 3, "ytick.minor.size": 3,
    "grid.color": "#909090", "grid.linewidth": .8, "grid.alpha": .8,
    "legend.framealpha": 1, "legend.fancybox": False,
    "legend.edgecolor": "#505050", "legend.fontsize": 8,
    "savefig.dpi": EXPORT_DPI,
}


def export_theme(function):
    @wraps(function)
    def themed(*args, **kwargs):
        with mpl.rc_context(RC):
            return function(*args, **kwargs)
    return themed


def voltage_label(axis):
    return (r"Drain voltage, $V_{DS}$ (V)" if axis == "vd"
            else r"Gate voltage, $V_G$ (V)")


def format_axes(ax, axis, ylabel):
    ax.set_xlabel(voltage_label(axis))
    ax.set_ylabel(ylabel)
    ax.grid(True, which="major")
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(EngFormatter(unit="", sep=""))
    if ax.get_xscale() == "linear":
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    if ax.get_yscale() == "linear":
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    else:
        ax.minorticks_on()
        # A sub-decade log range (e.g. 20–60 pA) needs visible major labels.
        lower, upper = ax.get_ylim()
        if 0 < lower < upper and upper / lower < 10:
            ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1., 2., 3., 4., 6.)))
        ax.yaxis.set_minor_formatter(NullFormatter())


def bias_colors(groups, axis):
    """Same fixed voltage gets the same color, including repeated traces.

    Missing biases are gray rather than implied voltage values. With one known
    bias use the purple end of the rainbow; do not create a spurious range.
    """
    fixed = "vg" if axis == "vd" else "vd"
    values = {}
    for group in groups:
        value = group["conditions"].get(fixed)
        if isinstance(value, (int, float)) and math.isfinite(value):
            values[group["group_id"]] = float(value)
    norm = Normalize(min(values.values()), max(values.values())) if values else None
    colors = {group["group_id"]: RAINBOW(norm(values[group["group_id"]]))
              if group["group_id"] in values else "#555555" for group in groups}
    return colors, values, norm, fixed


def palette(count):
    return [RAINBOW(index / max(count - 1, 1)) for index in range(count)]
