"""
SLDM — Module 3: Visualization
Interactive chart builder.
"""

import json
import csv as _csv
from collections import defaultdict

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame, QGridLayout, QSizePolicy,
    QSpinBox, QFileDialog, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QToolButton, QButtonGroup, QStackedWidget, QCheckBox,
    QSplitter, QMessageBox, QListWidget, QListWidgetItem,
    QColorDialog, QLineEdit, QDoubleSpinBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QColor, QFont

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from core.database import Database
from core.widgets import Panel, make_btn, EmptyState, Toast
from core.theme import COLORS

plt.rcParams.update({
    "figure.facecolor":   COLORS["bg_card"],
    "axes.facecolor":     COLORS["bg_card"],
    "axes.edgecolor":     COLORS["border"],
    "axes.labelcolor":    COLORS["text_secondary"],
    "axes.titlecolor":    COLORS["text_primary"],
    "text.color":         COLORS["text_primary"],
    "xtick.color":        COLORS["text_secondary"],
    "ytick.color":        COLORS["text_secondary"],
    "grid.color":         COLORS["border"],
    "grid.alpha":         0.4,
    "legend.facecolor":   COLORS["bg_secondary"],
    "legend.edgecolor":   COLORS["border"],
    "legend.labelcolor":  COLORS["text_secondary"],
    "axes.titlesize":     10,
    "axes.labelsize":     9,
    "xtick.labelsize":    8,
    "ytick.labelsize":    8,
    "font.family":        "DejaVu Sans",
})

PALETTE = [
    COLORS["accent_blue"], COLORS["accent_teal"], COLORS["accent_amber"],
    COLORS["accent_violet"], COLORS["accent_rose"], COLORS["accent_green"],
    "#fb923c", "#38bdf8", "#e879f9", "#4ade80", "#fbbf24", "#a3e635",
    "#94a3b8", "#f472b6", "#34d399", "#60a5fa",
]

CHART_TYPES = [
    ("bar",         "Bar",          "▬",  "Compare values across categories",               "Category (X)", "Value (Y)",           True,  False),
    ("stacked_bar", "Stacked Bar",  "▭",  "Bar split into color segments",                  "Category (X)", "Value (Y)",           True,  False),
    ("line",        "Line",         "╱",  "Trends over a continuous axis",                  "X axis",       "Y axis",              True,  False),
    ("area",        "Area",         "◭",  "Filled line — good for volume/trends",           "X axis",       "Y axis",              True,  False),
    ("scatter",     "Scatter",      "⬤",  "Relationship between two numeric variables",     "X (numeric)",  "Y (numeric)",         True,  True),
    ("bubble",      "Bubble",       "◎",  "Scatter with size as a third dimension",         "X (numeric)",  "Y (numeric)",         True,  True),
    ("pie",         "Pie",          "◔",  "Part-to-whole proportions",                      "Label",        "Value",               False, False),
    ("donut",       "Donut",        "◯",  "Pie with a hole",                                "Label",        "Value",               False, False),
    ("heatmap",     "Heatmap",      "▦",  "Matrix intensity chart",                         "X (category)", "Y (category)",        False, False),
    ("histogram",   "Histogram",    "▐",  "Distribution of a numeric variable",             "Numeric field","Count (auto)",        True,  False),
    ("boxplot",     "Box Plot",     "⊡",  "Distribution summary by group",                  "Group",        "Value (numeric)",     False, False),
]
CHART_KEY_MAP = {c[0]: c for c in CHART_TYPES}

FIELDS = [
    dict(key="obj_name",     label="Object name",         type="categorical", group="Objects"),
    dict(key="obj_notes",    label="Object notes",        type="text",        group="Objects"),
    dict(key="art_year",     label="Publication year",    type="temporal",    group="Articles"),
    dict(key="art_journal",  label="Journal",             type="categorical", group="Articles"),
    dict(key="art_authors",  label="Authors",             type="text",        group="Articles"),
    dict(key="art_title",    label="Article title",       type="text",        group="Articles"),
    dict(key="cit_count",    label="Citation count",      type="numeric",     group="Measures"),
    dict(key="rv_parameter", label="Parameter",           type="categorical", group="Review data"),
    dict(key="rv_species",   label="Species / matrix",    type="categorical", group="Review data"),
    dict(key="rv_value",     label="Numeric value",       type="numeric",     group="Review data"),
    dict(key="rv_unit",      label="Unit",                type="categorical", group="Review data"),
    dict(key="rv_location",  label="Location",            type="categorical", group="Review data"),
]
# NOTE: obj_cat_N dynamic fields are injected per-engine at populate time
FIELD_MAP = {f["key"]: f for f in FIELDS}

AXIS_COMPAT = {
    "bar":         dict(x=["cat","temporal"],       y=["num"],              color=["cat"],        size=[]),
    "stacked_bar": dict(x=["cat","temporal"],       y=["num"],              color=["cat"],        size=[]),
    "line":        dict(x=["cat","temporal","num"], y=["num"],              color=["cat"],        size=[]),
    "area":        dict(x=["cat","temporal","num"], y=["num"],              color=["cat"],        size=[]),
    "scatter":     dict(x=["num","temporal"],       y=["num"],              color=["cat","num"],  size=["num"]),
    "bubble":      dict(x=["num","temporal"],       y=["num"],              color=["cat"],        size=["num"]),
    "pie":         dict(x=["cat"],                  y=["num"],              color=[],             size=[]),
    "donut":       dict(x=["cat"],                  y=["num"],              color=[],             size=[]),
    "heatmap":     dict(x=["cat","temporal"],       y=["cat"],              color=["num"],        size=[]),
    "histogram":   dict(x=["num"],                  y=[],                   color=["cat"],        size=[]),
    "boxplot":     dict(x=["cat"],                  y=["num"],              color=[],             size=[]),
}
FIELD_TYPE_TOKENS = {
    "categorical": ["cat"],
    "temporal":    ["cat","temporal"],
    "numeric":     ["num"],
    "text":        [],
}

def field_compatible(field_key, axis_role, chart_key, extra_fields=None):
    # Dynamic category fields (obj_cat_0, obj_cat_1, ...) are always categorical
    if field_key.startswith("obj_cat_"):
        f_type = "categorical"
    else:
        fm = dict(FIELD_MAP)
        if extra_fields:
            for ef in extra_fields:
                fm[ef["key"]] = ef
        f = fm.get(field_key)
        if not f: return False
        f_type = f["type"]
    allowed = AXIS_COMPAT.get(chart_key, {}).get(axis_role, [])
    if not allowed: return False
    tokens = FIELD_TYPE_TOKENS.get(f_type, [])
    return any(t in allowed for t in tokens)


class MplCanvas(FigureCanvasQTAgg):
    def __init__(self, w=7, h=5, dpi=100):
        self.fig = Figure(figsize=(w, h), dpi=dpi)
        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background:{COLORS['bg_card']};border:none;")

    def clear(self):
        self.fig.clear()

    def draw_safe(self):
        try:
            self.fig.tight_layout()
            self.draw()
        except Exception:
            pass



# ── CHART ELEMENT MOVER ───────────────────────────────────────────────────────
# Replaces the unreliable mouse-drag approach with explicit arrow-key / WASD
# nudging controlled via toolbar buttons.  The active "target" (legend, title,
# or the axes itself) is set by the toolbar toggle buttons and then moved with
# the keyboard or on-screen arrow buttons.

MOVE_STEP      = 0.02   # fraction of axes per key-press (normal)
MOVE_STEP_FAST = 0.08   # fraction of axes per key-press (shift held)

class ChartElementMover:
    """
    Manages keyboard-driven nudging of chart elements.

    target: one of  'legend' | 'title' | 'axes'
    canvas: the MplCanvas that owns the figure
    config: the live chart config dict (used to persist legend_xy)
    """

    def __init__(self, canvas, config: dict):
        self._canvas = canvas
        self._config = config
        self._target = "legend"   # default

    def set_target(self, target: str):
        self._target = target

    def set_config(self, config: dict):
        self._config = config

    # ── helpers ───────────────────────────────────────────────────────────────
    def _axes(self):
        axs = self._canvas.fig.get_axes()
        return axs[0] if axs else None

    def _legend(self):
        ax = self._axes()
        return ax.get_legend() if ax else None

    # ── nudge ─────────────────────────────────────────────────────────────────
    def nudge(self, dx: float, dy: float):
        """Move the active element by (dx, dy) in axes-fraction units."""
        t = self._target
        if t == "legend":
            self._nudge_legend(dx, dy)
        elif t == "title":
            self._nudge_title(dx, dy)
        elif t == "axes":
            self._nudge_axes(dx, dy)
        try:
            self._canvas.draw()
        except Exception:
            pass

    def _nudge_legend(self, dx, dy):
        leg = self._legend()
        if leg is None:
            return
        ax = self._axes()
        try:
            # Get current anchor
            ba = leg.get_bbox_to_anchor()
            # ba is in display coords; convert to axes fraction
            inv = ax.transAxes.inverted()
            bbox = leg.get_window_extent()
            cx = bbox.x0 + bbox.width  / 2
            cy = bbox.y0 + bbox.height / 2
            xf, yf = inv.transform((cx, cy))
        except Exception:
            xf, yf = 0.8, 0.9
        xf = max(0.0, min(1.3, xf + dx))
        yf = max(0.0, min(1.1, yf + dy))
        leg.set_bbox_to_anchor((xf, yf), transform=ax.transAxes)
        # Persist in config
        self._config.setdefault("style", {})["legend_xy"] = (xf, yf)
        try:
            self._canvas.fig.set_tight_layout(False)
        except Exception:
            pass

    def _nudge_title(self, dx, dy):
        ax = self._axes()
        if ax is None:
            return
        title = ax.title
        x, y = title.get_position()   # axes fraction
        title.set_position((max(-0.2, min(1.2, x + dx)),
                            max(-0.2, min(1.5, y + dy))))

    def _nudge_axes(self, dx, dy):
        ax = self._axes()
        if ax is None:
            return
        pos = list(ax.get_position().bounds)  # [x0, y0, w, h]
        pos[0] = max(0.0, min(0.9, pos[0] + dx))
        pos[1] = max(0.0, min(0.9, pos[1] + dy))
        ax.set_position(pos)


class DataEngine:
    def __init__(self, db):
        self.db = db
        self._cache = {}

    def invalidate(self):
        self._cache.clear()

    def _get(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    @property
    def objects(self):   return self._get("objects",   self.db.get_objects)
    @property
    def articles(self):  return self._get("articles",  self.db.get_articles)
    @property
    def citations(self): return self._get("citations", self.db.get_citations)
    @property
    def review(self):    return self._get("review",    self.db.get_review_data)

    @property
    def obj_by_name(self):
        return self._get("obn", lambda: {o["name"]: o for o in self.objects})

    @property
    def art_by_id(self):
        return self._get("abi", lambda: {a["id"]: a for a in self.articles})

    @property
    def cit_count_by_obj(self):
        def _b():
            d = defaultdict(int)
            for c in self.citations: d[c["object_name"]] += 1
            return dict(d)
        return self._get("ccbo", _b)

    @property
    def cited_names(self):
        """Set of object names that appear in at least one citation."""
        return self._get("cited_names",
                         lambda: {c["object_name"] for c in self.citations})

    @property
    def cat_column_names(self) -> list:
        """
        Return the real CSV column names for each category level,
        inferred from project_meta (stored during import) or derived
        from the objects data.  Falls back to 'Category 1', 'Category 2', ...
        """
        def _build():
            # Try to read stored column names from project_meta
            try:
                raw = self.db.get_meta("category_col_names")
                if raw:
                    import json as _j
                    names = _j.loads(raw)
                    if names: return names
            except Exception:
                pass
            # Fall back: derive count from objects data
            mx = max((len(o.get("categories") or []) for o in self.objects), default=0)
            return [f"Category {i+1}" for i in range(mx)]
        return self._get("cat_col_names", _build)

    def dynamic_cat_fields(self) -> list:
        """Return FIELDS-style dicts for each real category column."""
        return [
            dict(key=f"obj_cat_{i}", label=name, type="categorical", group="Objects")
            for i, name in enumerate(self.cat_column_names)
        ]

    def get_flat_records(self, source="citations"):
        records = []
        if source == "citations":
            for cit in self.citations:
                on  = cit["object_name"]
                obj = self.obj_by_name.get(on, {})
                art = self.art_by_id.get(cit.get("article_id",""), {})
                cats = obj.get("categories") or []
                r = {
                    "obj_name": on,
                    "obj_cat":    obj.get("category","")    or "",
                    "obj_subcat": obj.get("subcategory","") or "",
                    "obj_notes":  obj.get("notes","")       or "",
                    "art_year":   art.get("year"),
                    "art_journal":art.get("journal","")     or "",
                    "art_authors":art.get("authors","")     or "",
                    "art_title":  art.get("title","")       or "",
                    "cit_count":  1, "art_count": 1, "obj_count": 1,
                    "rv_parameter":"","rv_species":"","rv_value":None,"rv_unit":"","rv_location":"",
                }
                for i, v in enumerate(cats):
                    r[f"obj_cat_{i}"] = v or ""
                records.append(r)
        elif source in ("objects", "cited_objects"):
            cited = self.cited_names if source == "cited_objects" else None
            for obj in self.objects:
                if cited is not None and obj["name"] not in cited:
                    continue
                cats = obj.get("categories") or []
                r = {
                    "obj_name":   obj["name"],
                    "obj_cat":    obj.get("category","")    or "",
                    "obj_subcat": obj.get("subcategory","") or "",
                    "obj_notes":  obj.get("notes","")       or "",
                    "art_year":None,"art_journal":"","art_authors":"","art_title":"",
                    "cit_count":  self.cit_count_by_obj.get(obj["name"],0),
                    "art_count":0,"obj_count":1,
                    "rv_parameter":"","rv_species":"","rv_value":None,"rv_unit":"","rv_location":"",
                }
                for i, v in enumerate(cats):
                    r[f"obj_cat_{i}"] = v or ""
                records.append(r)
        elif source == "review":
            for rv in self.review:
                on  = rv.get("object_name","")
                obj = self.obj_by_name.get(on, {})
                art = self.art_by_id.get(rv.get("article_id",""), {})
                cats = obj.get("categories") or []
                r = {
                    "obj_name":   on,
                    "obj_cat":    obj.get("category","")    or "",
                    "obj_subcat": obj.get("subcategory","") or "",
                    "obj_notes":  obj.get("notes","")       or "",
                    "art_year":   art.get("year"),
                    "art_journal":art.get("journal","")     or "",
                    "art_authors":art.get("authors","")     or "",
                    "art_title":  art.get("title","")       or "",
                    "cit_count":  self.cit_count_by_obj.get(on,0),
                    "art_count":1,"obj_count":1,
                    "rv_parameter":rv.get("parameter","") or "",
                    "rv_species":  rv.get("species","")   or "",
                    "rv_value":    rv.get("value_num"),
                    "rv_unit":     rv.get("unit","")      or "",
                    "rv_location": rv.get("location","")  or "",
                }
                for i, v in enumerate(cats):
                    r[f"obj_cat_{i}"] = v or ""
                records.append(r)
        return records

    def aggregate(self, records, x_key, y_key, color_key=None, agg_func="sum", filters=None):
        if filters:
            for fk, fv in filters:
                if fv: records = [r for r in records if str(r.get(fk,"")).strip() == str(fv).strip()]
        grouped = defaultdict(lambda: defaultdict(list))
        for r in records:
            xv = r.get(x_key); yv = r.get(y_key)
            cv = str(r.get(color_key,"_")) if color_key else "_"
            if xv is None: xv = "Unknown"
            grouped[cv][str(xv)].append(yv)
        result = {}
        for cv, xdict in grouped.items():
            result[cv] = {}
            for xv, vals in xdict.items():
                # Coerce to float, skip non-numeric
                nums = []
                for v in vals:
                    if v is None: continue
                    try: nums.append(float(v))
                    except (TypeError, ValueError): pass
                if agg_func == "sum":     result[cv][xv] = sum(nums) if nums else len(vals)
                elif agg_func == "count": result[cv][xv] = len(vals)
                elif agg_func == "mean":  result[cv][xv] = sum(nums)/len(nums) if nums else 0
                elif agg_func == "max":   result[cv][xv] = max(nums) if nums else 0
                elif agg_func == "min":   result[cv][xv] = min(nums) if nums else 0
        return result

    def unique_values(self, field_key, source="citations"):
        return sorted({str(r.get(field_key,"")) for r in self.get_flat_records(source)
                       if r.get(field_key) not in (None,"")})



# ── COLOR BUTTON ──────────────────────────────────────────────────────────────
class ColorButton(QPushButton):
    """A button that shows a color swatch and opens a color picker on click."""
    colorChanged = pyqtSignal(str)   # emits hex string

    def __init__(self, color: str = "#4f8ef7", parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(32, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._refresh()
        self.clicked.connect(self._pick)

    def _refresh(self):
        c = self._color
        self.setStyleSheet(
            f"QPushButton{{background:{c};border:1px solid {COLORS['border']};"
            f"border-radius:3px;}} "
            f"QPushButton:hover{{border:1px solid {COLORS['text_secondary']};}}"
        )

    def _pick(self):
        dlg = QColorDialog(QColor(self._color), self)
        dlg.setOption(QColorDialog.ShowAlphaChannel, False)
        if dlg.exec_() == QColorDialog.Accepted:
            self._color = dlg.selectedColor().name()
            self._refresh()
            self.colorChanged.emit(self._color)

    def color(self) -> str:
        return self._color

    def set_color(self, c: str):
        self._color = c
        self._refresh()


class ChartRenderer:
    def render(self, canvas, config, engine):
        canvas.clear()
        try:
            self._dispatch(canvas, config, engine)
        except Exception as e:
            ax = canvas.fig.add_subplot(111)
            ax.text(0.5, 0.5, f"Cannot draw chart:\n{e}",
                    ha='center', va='center', transform=ax.transAxes,
                    color=COLORS["text_muted"], fontsize=9)
            ax.axis('off')
        canvas.draw_safe()

    # ── Style helpers ─────────────────────────────────────────────────────────
    def _style(self, config) -> dict:
        return config.get("style", {})

    def _legend_loc(self, config) -> str:
        return "best"

    def _legend_xy(self, config):
        return self._style(config).get("legend_xy", None)

    def _show_legend(self, config) -> bool:
        return self._style(config).get("show_legend", True)

    def _attach_legend(self, leg, canvas, config):
        """Restore a previously saved legend position (set by the mover)."""
        if leg is None:
            return
        xy = self._legend_xy(config)
        if xy:
            try:
                ax = leg.axes
                leg.set_bbox_to_anchor(xy, transform=ax.transAxes)
                canvas.fig.set_tight_layout(False)
            except Exception:
                pass

    def _make_legend(self, ax, canvas, config, **kwargs):
        """
        Safe legend creator — always forces the legend visible even when
        matplotlib decides there are no labeled artists.  Applies _attach_legend
        to restore saved position.
        """
        if not self._show_legend(config):
            return None
        try:
            leg = ax.legend(fontsize=kwargs.pop("fontsize", 8), **kwargs)
        except Exception:
            leg = None
        if leg is None:
            # No labeled artists — nothing to show
            return None
        # Force visible (matplotlib sometimes hides it)
        leg.set_visible(True)
        self._attach_legend(leg, canvas, config)
        return leg

    def _make_legend_handles(self, ax, canvas, config, handles, labels, **kwargs):
        """Legend from explicit handles list."""
        if not self._show_legend(config) or not handles:
            return None
        try:
            leg = ax.legend(handles=handles, labels=labels,
                            fontsize=kwargs.pop("fontsize", 8), **kwargs)
        except Exception:
            leg = None
        if leg:
            leg.set_visible(True)
            self._attach_legend(leg, canvas, config)
        return leg

    def _series_colors(self, config) -> list:
        """Custom per-series colors; falls back to PALETTE for missing entries."""
        custom = self._style(config).get("series_colors", [])
        result = list(custom)
        while len(result) < len(PALETTE):
            result.append(PALETTE[len(result) % len(PALETTE)])
        return result

    def _elem_style(self, config, elem: str) -> dict:
        """Return style dict for a specific element: 'legend', 'title', 'axes'."""
        return self._style(config).get(f"{elem}_style", {})

    def _apply_fig_style(self, canvas, config):
        """Apply per-element styling (bg, font family/size/color) to the figure."""
        s = self._style(config)
        # Figure background
        fig_bg = s.get("bg_color", COLORS["bg_card"])
        canvas.fig.patch.set_facecolor(fig_bg)

        for ax in canvas.fig.get_axes():
            ax_s  = self._elem_style(config, "axes")
            ax_bg = ax_s.get("bg_color", fig_bg)
            ax.set_facecolor(ax_bg)

            # Title styling
            t_s   = self._elem_style(config, "title")
            t_ff  = t_s.get("font_family", s.get("font_family", "DejaVu Sans"))
            t_fs  = int(t_s.get("font_size",  s.get("font_size",  10)))
            t_fc  = t_s.get("font_color", COLORS["text_primary"])
            ax.title.set_fontfamily(t_ff)
            ax.title.set_fontsize(t_fs)
            ax.title.set_color(t_fc)

            # Axes labels and ticks
            ax_ff = ax_s.get("font_family", s.get("font_family", "DejaVu Sans"))
            ax_fs = int(ax_s.get("font_size",  s.get("font_size",  9)))
            ax_fc = ax_s.get("font_color", COLORS["text_secondary"])
            for item in ([ax.xaxis.label, ax.yaxis.label]
                         + ax.get_xticklabels() + ax.get_yticklabels()):
                item.set_fontfamily(ax_ff)
                item.set_fontsize(ax_fs)
                item.set_color(ax_fc)

            # Legend styling
            leg = ax.get_legend()
            if leg:
                l_s  = self._elem_style(config, "legend")
                l_ff = l_s.get("font_family", s.get("font_family", "DejaVu Sans"))
                l_fs = int(l_s.get("font_size",  s.get("font_size",  8)))
                l_fc = l_s.get("font_color", COLORS["text_secondary"])
                l_bg = l_s.get("bg_color",   COLORS["bg_secondary"])
                leg.get_frame().set_facecolor(l_bg)
                for txt in leg.get_texts():
                    txt.set_fontfamily(l_ff)
                    txt.set_fontsize(l_fs)
                    txt.set_color(l_fc)

    def _filter_by_objects(self, records, config) -> list:
        """Keep only records whose obj_name is in the allowed set (if any)."""
        allowed = config.get("object_filter")   # set or None
        if not allowed:
            return records
        return [r for r in records if r.get("obj_name","") in allowed]

    def _dispatch(self, canvas, config, engine):
        k = config.get("chart_key","bar")
        if k == "heatmap":   self._heatmap(canvas, config, engine)
        elif k == "histogram": self._histogram(canvas, config, engine)
        elif k == "boxplot":   self._boxplot(canvas, config, engine)
        elif k in ("scatter","bubble"): self._scatter(canvas, config, engine, k=="bubble")
        elif k in ("pie","donut"):      self._pie(canvas, config, engine, k=="donut")
        else:                           self._agg(canvas, config, engine, k)
        self._apply_fig_style(canvas, config)

    def _src(self, config):
        keys = {config.get(k) or "" for k in ("x_field","y_field","color_field","size_field")}
        keys = {k for k in keys if k}   # remove None / empty strings
        if any(k.startswith("rv_") for k in keys): return "review"
        scope = config.get("scope","cited")   # "cited" | "all"
        obj_src = "cited_objects" if scope == "cited" else "objects"
        if all((k.startswith("obj_") or k in ("cit_count","")) for k in keys): return obj_src
        return "citations"

    def _filters(self, config):
        return [(k,v) for k,v in config.get("filters",{}).items() if v]

    def _no_data(self, ax, msg="No data for this configuration."):
        ax.text(0.5,0.5,msg,ha='center',va='center',transform=ax.transAxes,
                color=COLORS["text_muted"],fontsize=10)
        ax.axis('off')

    def _lbl(self, key, engine=None):
        if key and key.startswith("obj_cat_") and engine:
            try:
                idx = int(key.split("_")[-1])
                names = engine.cat_column_names
                if idx < len(names): return names[idx]
            except (ValueError, AttributeError):
                pass
        return FIELD_MAP.get(key,{}).get("label", key or "")

    def _agg(self, canvas, config, engine, chart_key):
        x_key  = config.get("x_field","obj_name")
        y_key  = config.get("y_field") or "cit_count"
        c_key  = config.get("color_field") or None
        max_n  = config.get("max_items", 20)
        agg    = config.get("agg_func","sum")
        src    = self._src(config)
        recs   = engine.get_flat_records(src)
        recs   = self._filter_by_objects(recs, config)
        data   = engine.aggregate(recs, x_key, y_key, c_key, agg, self._filters(config))
        groups = list(data.keys())
        if not groups or not any(data[g] for g in groups):
            ax = canvas.fig.add_subplot(111); self._no_data(ax); return

        all_x = sorted({xv for gd in data.values() for xv in gd.keys()},
                       key=lambda v: (not str(v).lstrip('-').isdigit(), v))
        if len(groups) == 1:
            items = sorted(list(data[groups[0]].items()), key=lambda kv: -kv[1])[:max_n]
            all_x = [i[0] for i in items]

        ax = canvas.fig.add_subplot(111)
        xl, yl = self._lbl(x_key, engine), self._lbl(y_key, engine)
        colors = self._series_colors(config)
        show_leg = self._show_legend(config)

        if chart_key == "stacked_bar":
            bottoms = [0.0]*len(all_x)
            for gi,(grp,gd) in enumerate(data.items()):
                vals = [gd.get(xv,0) for xv in all_x]
                ax.bar(all_x, vals, bottom=bottoms, color=colors[gi],
                       label=grp if grp!="_" else None, edgecolor='none', width=0.65)
                bottoms = [b+v for b,v in zip(bottoms,vals)]
            if any(g!="_" for g in groups):
                self._make_legend(ax, canvas, config)
            ax.set_ylabel(yl)
            plt.setp(ax.get_xticklabels(), rotation=35, ha='right')

        elif chart_key == "bar":
            if len(groups)==1:
                vals = [data[groups[0]].get(xv,0) for xv in all_x]
                clrs = [colors[i % len(colors)] for i in range(len(all_x))]
                ax.bar(all_x, vals, color=clrs, edgecolor='none', width=0.65)
            else:
                import numpy as np
                w = 0.8/len(groups)
                xpos = range(len(all_x))
                for gi,(grp,gd) in enumerate(data.items()):
                    vals = [gd.get(xv,0) for xv in all_x]
                    offs = [p+gi*w-0.4 for p in xpos]
                    ax.bar(offs, vals, width=w, color=colors[gi],
                           label=grp, edgecolor='none')
                ax.set_xticks(list(xpos)); ax.set_xticklabels(all_x)
                self._make_legend(ax, canvas, config)
            ax.set_ylabel(yl)
            plt.setp(ax.get_xticklabels(), rotation=35, ha='right')

        elif chart_key in ("line","area"):
            for gi,(grp,gd) in enumerate(data.items()):
                try:    sx = sorted(all_x, key=lambda v: float(v))
                except: sx = all_x
                vals = [gd.get(xv,0) for xv in sx]
                col  = colors[gi % len(colors)]
                ax.plot(sx, vals, color=col, linewidth=2.5, marker='o', markersize=4,
                        label=grp if grp!="_" else None)
                if chart_key=="area":
                    ax.fill_between(range(len(sx)), vals, alpha=0.15, color=col)
                    ax.set_xticks(range(len(sx)))
                    ax.set_xticklabels(sx, rotation=35, ha='right')
            ax.set_xlabel(xl); ax.set_ylabel(yl)
            if any(g!="_" for g in groups):
                self._make_legend(ax, canvas, config)
            ax.grid(axis='y',linestyle='--',alpha=0.4)
            plt.setp(ax.get_xticklabels(), rotation=35, ha='right')

        ax.set_title(config.get("title") or f"{yl}  by  {xl}")
        ax.spines[['top','right']].set_visible(False)

    def _scatter(self, canvas, config, engine, bubble):
        x_key = config.get("x_field","rv_value")
        y_key = config.get("y_field","cit_count")
        c_key = config.get("color_field")
        s_key = config.get("size_field") if bubble else None
        src   = self._src(config)
        recs  = engine.get_flat_records(src)
        recs  = self._filter_by_objects(recs, config)
        for fk,fv in self._filters(config):
            recs = [r for r in recs if str(r.get(fk,""))==str(fv)]
        pts = [(r.get(x_key),r.get(y_key),
                str(r.get(c_key,"")) if c_key else "_",
                r.get(s_key,1) or 1, r.get("obj_name",""))
               for r in recs if r.get(x_key) is not None and r.get(y_key) is not None]
        if not pts:
            ax=canvas.fig.add_subplot(111); self._no_data(ax,"No numeric data."); return
        ax   = canvas.fig.add_subplot(111)
        ucol = list(dict.fromkeys(p[2] for p in pts))
        colors = self._series_colors(config)
        cmap = {c:colors[i%len(colors)] for i,c in enumerate(ucol)}
        xs   = [float(p[0]) for p in pts]
        ys   = [float(p[1]) for p in pts]
        cs   = [cmap[p[2]] for p in pts]
        sz   = [max(20,float(p[3])*5) for p in pts] if bubble else [45]*len(pts)
        ax.scatter(xs, ys, c=cs, s=sz, alpha=0.75, edgecolors='none')
        for x,y,_,_,name in pts[:60]:
            ax.annotate(name,(float(x),float(y)),textcoords="offset points",
                        xytext=(4,4),fontsize=6.5,color=COLORS["text_secondary"])
        if len(ucol)>1:
            patches=[mpatches.Patch(color=cmap[c],label=c) for c in ucol[:12]]
            self._make_legend_handles(ax, canvas, config, patches,
                                      [c for c in ucol[:12]],
                                      title=self._lbl(c_key, engine))
        ax.set_xlabel(self._lbl(x_key, engine)); ax.set_ylabel(self._lbl(y_key, engine))
        ax.set_title(config.get("title") or f"{self._lbl(y_key, engine)} vs {self._lbl(x_key, engine)}")
        ax.spines[['top','right']].set_visible(False)
        ax.grid(linestyle='--',alpha=0.4)

    def _pie(self, canvas, config, engine, donut):
        x_key = config.get("x_field","obj_cat")
        y_key = config.get("y_field","cit_count")
        max_n = config.get("max_items",12)
        src   = self._src(config)
        recs  = engine.get_flat_records(src)
        recs  = self._filter_by_objects(recs, config)
        for fk,fv in self._filters(config):
            recs = [r for r in recs if str(r.get(fk,""))==str(fv)]
        agg = defaultdict(float)
        for r in recs:
            xv = str(r.get(x_key,"") or "Unknown")
            yv = r.get(y_key,1) or 1
            try: agg[xv] += float(yv)
            except: agg[xv] += 1
        if not agg:
            ax=canvas.fig.add_subplot(111); self._no_data(ax); return
        top = sorted(agg.items(),key=lambda kv:-kv[1])[:max_n]
        rest = sum(v for _,v in sorted(agg.items(),key=lambda kv:-kv[1])[max_n:])
        if rest: top.append(("Other",rest))
        labels=[t[0] for t in top]; vals=[t[1] for t in top]
        colors = self._series_colors(config)
        pie_colors=[colors[i%len(colors)] for i in range(len(labels))]
        ax=canvas.fig.add_subplot(111)
        wkw={"edgecolor":COLORS["bg_card"],"linewidth":2}
        if donut: wkw["width"]=0.55
        wedges,texts,autos=ax.pie(vals, labels=None,
            autopct='%1.1f%%', colors=pie_colors, pctdistance=0.82,
            wedgeprops=wkw, startangle=90)
        for t in texts: t.set_fontsize(8)
        for a in autos: a.set_fontsize(7)
        if self._show_legend(config):
            self._make_legend_handles(ax, canvas, config, wedges, labels, frameon=True)
        ax.set_title(config.get("title") or f"{self._lbl(y_key, engine)} by {self._lbl(x_key, engine)}")

    def _heatmap(self, canvas, config, engine):
        import numpy as np
        x_key = config.get("x_field","art_year")
        y_key = config.get("y_field","obj_name")
        v_key = config.get("color_field","cit_count")
        max_n = config.get("max_items",20)
        src   = self._src(config)
        recs  = engine.get_flat_records(src)
        recs  = self._filter_by_objects(recs, config)
        for fk,fv in self._filters(config):
            recs=[r for r in recs if str(r.get(fk,""))==str(fv)]
        mat   = defaultdict(lambda: defaultdict(float))
        for r in recs:
            xv=str(r.get(x_key,"") or "?"); yv=str(r.get(y_key,"") or "?")
            val=r.get(v_key,1) or 1
            try: mat[yv][xv]+=float(val)
            except: mat[yv][xv]+=1
        if not mat:
            ax=canvas.fig.add_subplot(111); self._no_data(ax); return
        all_x  = sorted({xv for yd in mat.values() for xv in yd})
        rtots  = {yv:sum(xd.values()) for yv,xd in mat.items()}
        all_y  = sorted(rtots,key=lambda k:-rtots[k])[:max_n]
        data_np= np.array([[mat[yv].get(xv,0) for xv in all_x] for yv in all_y],dtype=float)
        ax=canvas.fig.add_subplot(111)
        im=ax.imshow(data_np,aspect='auto',cmap='Blues',interpolation='nearest')
        ax.set_xticks(range(len(all_x)))
        ax.set_xticklabels([str(v) for v in all_x],rotation=45,ha='right',fontsize=7)
        ax.set_yticks(range(len(all_y)))
        ax.set_yticklabels(all_y,fontsize=8)
        canvas.fig.colorbar(im,ax=ax,shrink=0.6,label=self._lbl(v_key, engine))
        ax.set_title(config.get("title") or f"Heatmap: {self._lbl(y_key, engine)} × {self._lbl(x_key, engine)}")

    def _histogram(self, canvas, config, engine):
        x_key = config.get("x_field","rv_value")
        c_key = config.get("color_field")
        bins  = config.get("bins",20)
        src   = self._src(config)
        recs  = engine.get_flat_records(src)
        recs  = self._filter_by_objects(recs, config)
        for fk,fv in self._filters(config):
            recs=[r for r in recs if str(r.get(fk,""))==str(fv)]
        colors = self._series_colors(config)
        if c_key:
            groups=defaultdict(list)
            for r in recs:
                v=r.get(x_key)
                if v is not None:
                    try: groups[str(r.get(c_key,"_"))].append(float(v))
                    except: pass
        else:
            groups={"_":[float(r[x_key]) for r in recs if r.get(x_key) is not None]}
        if not any(groups.values()):
            ax=canvas.fig.add_subplot(111); self._no_data(ax,"No numeric data."); return
        ax=canvas.fig.add_subplot(111)
        for gi,(grp,vals) in enumerate(groups.items()):
            ax.hist(vals,bins=bins,alpha=0.7,color=colors[gi%len(colors)],
                    label=grp if grp!="_" else None,edgecolor=COLORS["bg_card"])
        if len(groups)>1:
            self._make_legend(ax, canvas, config)
        ax.set_xlabel(self._lbl(x_key, engine)); ax.set_ylabel("Count")
        ax.set_title(config.get("title") or f"Distribution of {self._lbl(x_key, engine)}")
        ax.spines[['top','right']].set_visible(False)

    def _boxplot(self, canvas, config, engine):
        x_key = config.get("x_field","obj_cat")
        y_key = config.get("y_field","rv_value")
        max_n = config.get("max_items",15)
        src   = self._src(config)
        recs  = engine.get_flat_records(src)
        recs  = self._filter_by_objects(recs, config)
        for fk,fv in self._filters(config):
            recs=[r for r in recs if str(r.get(fk,""))==str(fv)]
        colors = self._series_colors(config)
        groups=defaultdict(list)
        for r in recs:
            xv=str(r.get(x_key,"") or "?"); yv=r.get(y_key)
            if yv is not None:
                try: groups[xv].append(float(yv))
                except: pass
        if not groups:
            ax=canvas.fig.add_subplot(111); self._no_data(ax,"No numeric data."); return
        sg=sorted(groups.items(),key=lambda kv:-(sum(kv[1])/len(kv[1]) if kv[1] else 0))[:max_n]
        labels=[g[0] for g in sg]; data=[g[1] for g in sg]
        ax=canvas.fig.add_subplot(111)
        ax.boxplot(data,labels=labels,patch_artist=True,
                   medianprops={"color":COLORS["accent_amber"],"linewidth":2},
                   boxprops={"facecolor":colors[0]+"33","edgecolor":colors[0]},
                   whiskerprops={"color":COLORS["text_muted"]},
                   capprops={"color":COLORS["text_muted"]},
                   flierprops={"marker":"o","color":COLORS["text_muted"],"markersize":3,"alpha":0.5})
        plt.setp(ax.get_xticklabels(),rotation=35,ha='right',fontsize=8)
        ax.set_ylabel(self._lbl(y_key, engine))
        ax.set_title(config.get("title") or f"{self._lbl(y_key, engine)} by {self._lbl(x_key, engine)}")
        ax.spines[['top','right']].set_visible(False)
        ax.grid(axis='y',linestyle='--',alpha=0.4)


class FieldCombo(QComboBox):
    NONE = "— none —"
    def __init__(self, parent=None, nullable=True):
        super().__init__(parent)
        self._nullable = nullable
        self.setStyleSheet(
            f"QComboBox{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
            f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 8px;font-size:9pt;}}"
            f"QComboBox::drop-down{{border:none;padding-right:6px;}}"
            f"QComboBox QAbstractItemView{{background:{COLORS['bg_secondary']};"
            f"border:1px solid {COLORS['border']};"
            f"selection-background-color:{COLORS['bg_hover']};"
            f"color:{COLORS['text_primary']};}}"
        )

    def populate(self, chart_key, axis_role, current=None, extra_fields=None):
        self.blockSignals(True)
        self.clear()
        if self._nullable: self.addItem(self.NONE, userData=None)
        # Merge static + dynamic fields
        all_fields = list(FIELDS)
        if extra_fields:
            all_fields = extra_fields + all_fields   # dynamic cats first in Objects group
        by_group = defaultdict(list)
        for f in all_fields:
            if field_compatible(f["key"], axis_role, chart_key, extra_fields):
                by_group[f["group"]].append(f)
        for group, flist in by_group.items():
            self.addItem(f"── {group} ──", userData="__sep__")
            item = self.model().item(self.count()-1)
            item.setEnabled(False)
            item.setForeground(QColor(COLORS["text_muted"]))
            for f in flist:
                self.addItem(f["label"], userData=f["key"])
        if current:
            for i in range(self.count()):
                if self.itemData(i) == current:
                    self.setCurrentIndex(i); break
        self.blockSignals(False)

    def current_field(self):
        d = self.currentData()
        return d if d and d != "__sep__" else None


class ChartBuilderPanel(QWidget):
    chart_saved = pyqtSignal(dict)

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine   = engine
        self.renderer = ChartRenderer()
        self._current_type = "bar"
        self._dynamic_fields = []   # populated by refresh_filters
        self._obj_filter: set = None
        self._mover = None   # created inside _build after canvas exists
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)

        # Left gallery
        gallery = QWidget()
        gallery.setFixedWidth(112)
        gallery.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-right:1px solid {COLORS['border']};"
        )
        gl = QVBoxLayout(gallery)
        gl.setContentsMargins(6,10,6,10)
        gl.setSpacing(4)
        lbl = QLabel("Chart type")
        lbl.setStyleSheet(
            f"font-size:7.5pt;font-weight:700;color:{COLORS['text_muted']};"
            "text-transform:uppercase;letter-spacing:1px;background:transparent;border:none;"
        )
        gl.addWidget(lbl)
        self._type_btns = {}
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        for ct in CHART_TYPES:
            key,name,icon,desc=ct[0],ct[1],ct[2],ct[3]
            btn = QToolButton()
            btn.setText(f"{icon}\n{name}")
            btn.setToolTip(desc)
            btn.setCheckable(True)
            btn.setFixedSize(92,52)
            btn.setStyleSheet(
                f"QToolButton{{background:{COLORS['bg_tertiary']};border:1px solid transparent;"
                f"border-radius:6px;color:{COLORS['text_secondary']};font-size:8pt;}}"
                f"QToolButton:hover{{background:{COLORS['bg_hover']};color:{COLORS['text_primary']};}}"
                f"QToolButton:checked{{background:{COLORS['accent_blue']}22;"
                f"border:1px solid {COLORS['accent_blue']}88;"
                f"color:{COLORS['accent_blue']};font-weight:700;}}"
            )
            btn.clicked.connect(lambda checked,k=key: self._on_type(k))
            self._btn_group.addButton(btn)
            self._type_btns[key] = btn
            gl.addWidget(btn)
        gl.addStretch()
        root.addWidget(gallery)

        # Center canvas
        center = QWidget()
        center.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0,0,0,0)
        cl.setSpacing(0)
        tbar_w = QWidget()
        tbar_w.setFixedHeight(42)
        tbar_w.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        tl = QHBoxLayout(tbar_w)
        tl.setContentsMargins(10,0,10,0)
        tl.setSpacing(6)
        self._title_lbl = QLabel("Select a chart type →")
        self._title_lbl.setStyleSheet(
            f"font-size:10pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        tl.addWidget(self._title_lbl,1)
        # Scope toggle: cited-only vs all objects
        self._scope_btn = QPushButton("🔬 Found in articles")
        self._scope_btn.setCheckable(True)
        self._scope_btn.setChecked(True)
        self._scope_btn.setFixedHeight(28)
        self._scope_btn.setToolTip(
            "Toggle between objects found in scanned articles (default) "
            "and all objects in the list"
        )
        self._scope_btn.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent_teal']}22;"
            f"border:1px solid {COLORS['accent_teal']}66;"
            f"border-radius:5px;color:{COLORS['accent_teal']};"
            f"padding:2px 10px;font-size:8pt;font-weight:600;}}"
            f"QPushButton:!checked{{background:{COLORS['bg_tertiary']};"
            f"border:1px solid {COLORS['border']};"
            f"color:{COLORS['text_muted']};}}"
            f"QPushButton:hover{{border-color:{COLORS['accent_teal']};}}"
        )
        self._scope_btn.toggled.connect(self._on_scope_toggle)
        tl.addWidget(self._scope_btn)
        for txt,fn,pri in [("▶  Draw",self._draw,True),
                           ("📌  Pin",self._pin,False),
                           ("⬇  Save",self._save,False)]:
            b = make_btn(txt, primary=pri)
            b.clicked.connect(fn)
            tl.addWidget(b)
        cl.addWidget(tbar_w)

        # ── Mover toolbar (below main toolbar) ────────────────────────────────
        mover_bar = QWidget()
        mover_bar.setFixedHeight(36)
        mover_bar.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        ml = QHBoxLayout(mover_bar)
        ml.setContentsMargins(10, 0, 10, 0)
        ml.setSpacing(4)

        move_lbl = QLabel("Move:")
        move_lbl.setStyleSheet(
            f"font-size:7.5pt;font-weight:700;color:{COLORS['text_muted']};"
            "text-transform:uppercase;background:transparent;border:none;"
        )
        ml.addWidget(move_lbl)

        # Target toggle buttons
        self._mover_group = QButtonGroup(self)
        self._mover_group.setExclusive(True)
        self._mover_btns = {}
        for key, label, tip in [
            ("legend", "📌 Legend", "Move the legend (arrows / WASD)"),
            ("title",  "📝 Title",  "Move the chart title (arrows / WASD)"),
            ("axes",   "📐 Chart",  "Move the chart axes area (arrows / WASD)"),
        ]:
            b = QToolButton()
            b.setText(label)
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setStyleSheet(
                f"QToolButton{{background:{COLORS['bg_tertiary']};"
                f"border:1px solid {COLORS['border']};border-radius:4px;"
                f"color:{COLORS['text_secondary']};font-size:8pt;padding:0 8px;}}"
                f"QToolButton:checked{{background:{COLORS['accent_violet']}22;"
                f"border:1px solid {COLORS['accent_violet']}88;"
                f"color:{COLORS['accent_violet']};font-weight:700;}}"
                f"QToolButton:hover{{background:{COLORS['bg_hover']};}}"
            )
            b.clicked.connect(lambda checked, k=key: self._set_move_target(k))
            self._mover_group.addButton(b)
            self._mover_btns[key] = b
            ml.addWidget(b)

        self._mover_btns["legend"].setChecked(True)

        ml.addSpacing(10)
        sep = QFrame(); sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color:{COLORS['border']};"); ml.addWidget(sep)
        ml.addSpacing(6)

        # On-screen arrow buttons
        arrow_lbl = QLabel("Nudge:")
        arrow_lbl.setStyleSheet(
            f"font-size:7.5pt;font-weight:700;color:{COLORS['text_muted']};"
            "text-transform:uppercase;background:transparent;border:none;"
        )
        ml.addWidget(arrow_lbl)

        arrow_style = (
            f"QPushButton{{background:{COLORS['bg_tertiary']};"
            f"border:1px solid {COLORS['border']};border-radius:4px;"
            f"color:{COLORS['text_primary']};font-size:11pt;"
            f"min-width:26px;max-width:26px;min-height:24px;max-height:24px;}}"
            f"QPushButton:pressed{{background:{COLORS['bg_hover']};}}"
        )
        for arrow, ddx, ddy in [("←", -MOVE_STEP, 0), ("→", MOVE_STEP, 0),
                                  ("↑",  0, MOVE_STEP), ("↓", 0, -MOVE_STEP)]:
            ab = QPushButton(arrow)
            ab.setStyleSheet(arrow_style)
            ab.setToolTip(f"Nudge {arrow}  (also: keyboard arrow keys / WASD)")
            ab.clicked.connect(lambda _, dx=ddx, dy=ddy: self._nudge(dx, dy))
            ml.addWidget(ab)

        ml.addSpacing(6)
        hint = QLabel("  Shift = faster")
        hint.setStyleSheet(
            f"font-size:7.5pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;"
        )
        ml.addWidget(hint)
        ml.addStretch()
        cl.addWidget(mover_bar)

        self.canvas = MplCanvas(9, 6)
        # Give canvas keyboard focus so arrow keys work directly
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.keyPressEvent = self._canvas_key_press
        # Init mover (needs canvas; config assigned per-draw)
        self._mover = ChartElementMover(self.canvas, {})

        tb = NavigationToolbar2QT(self.canvas, center)
        tb.setStyleSheet(
            f"background:{COLORS['bg_secondary']};border:none;"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        cl.addWidget(tb)
        cl.addWidget(self.canvas, 1)
        root.addWidget(center, 1)

        # Right controls
        rscroll = QScrollArea()
        rscroll.setWidgetResizable(True)
        rscroll.setFixedWidth(234)
        rscroll.setStyleSheet(
            f"QScrollArea{{background:{COLORS['bg_secondary']};"
            f"border-left:1px solid {COLORS['border']};"
            "border-right:none;border-top:none;border-bottom:none;}}"
        )
        ri = QWidget()
        ri.setStyleSheet(f"background:{COLORS['bg_secondary']};border:none;")
        rl = QVBoxLayout(ri)
        rl.setContentsMargins(12,14,12,14)
        rl.setSpacing(8)

        def sec(t):
            l=QLabel(t)
            l.setStyleSheet(
                f"font-size:7.5pt;font-weight:700;color:{COLORS['text_muted']};"
                "text-transform:uppercase;letter-spacing:1px;"
                "background:transparent;border:none;margin-top:6px;"
            )
            return l

        def lbl(t):
            l=QLabel(t)
            l.setStyleSheet(f"font-size:8.5pt;color:{COLORS['text_secondary']};background:transparent;border:none;")
            return l

        cb_s = (
            f"QComboBox{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
            f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 8px;font-size:9pt;}}"
            f"QComboBox::drop-down{{border:none;padding-right:6px;}}"
            f"QComboBox QAbstractItemView{{background:{COLORS['bg_secondary']};"
            f"border:1px solid {COLORS['border']};"
            f"selection-background-color:{COLORS['bg_hover']};"
            f"color:{COLORS['text_primary']};}}"
        )
        sp_s = (
            f"QSpinBox{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
            f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 6px;}}"
        )

        rl.addWidget(sec("Axes"))
        rl.addWidget(lbl("X axis"))
        self._x = FieldCombo(nullable=False); rl.addWidget(self._x)
        rl.addWidget(lbl("Y axis / value"))
        self._y = FieldCombo(nullable=True);  rl.addWidget(self._y)
        rl.addWidget(lbl("Color / group by"))
        self._c = FieldCombo(nullable=True);  rl.addWidget(self._c)
        rl.addWidget(lbl("Size  (bubble only)"))
        self._sz = FieldCombo(nullable=True); rl.addWidget(self._sz)

        rl.addWidget(sec("Aggregation"))
        rl.addWidget(lbl("Y aggregation"))
        self._agg = QComboBox(); self._agg.setStyleSheet(cb_s)
        for k,l_ in [("sum","Sum"),("count","Count"),("mean","Average"),
                     ("max","Maximum"),("min","Minimum")]:
            self._agg.addItem(l_, userData=k)
        rl.addWidget(self._agg)
        rl.addWidget(lbl("Max items shown"))
        self._max = QSpinBox(); self._max.setRange(3,100); self._max.setValue(20)
        self._max.setStyleSheet(sp_s); rl.addWidget(self._max)
        rl.addWidget(lbl("Bins  (histogram)"))
        self._bins = QSpinBox(); self._bins.setRange(3,100); self._bins.setValue(20)
        self._bins.setStyleSheet(sp_s); rl.addWidget(self._bins)

        rl.addWidget(sec("Filters"))
        # Dynamic category filter rows are injected here by refresh_filters()
        # We store the layout and a reference widget to know the insertion point
        self._filter_layout = rl   # reference for dynamic insertion
        lbl_style = f"font-size:8pt;color:{COLORS['text_secondary']};background:transparent;border:none;"
        self._f_par_lbl = QLabel("Parameter"); self._f_par_lbl.setStyleSheet(lbl_style)
        rl.addWidget(self._f_par_lbl)
        self._f_par = QComboBox(); self._f_par.setStyleSheet(cb_s); rl.addWidget(self._f_par)
        rl.addWidget(lbl("Journal"))
        self._f_jrn = QComboBox(); self._f_jrn.setStyleSheet(cb_s); rl.addWidget(self._f_jrn)

        # ── Object selection ──────────────────────────────────────────────────
        rl.addWidget(sec("Objects"))
        self._obj_filter: set = None   # None = show all

        self._obj_search = QLineEdit()
        self._obj_search.setPlaceholderText("Filter objects…")
        self._obj_search.setClearButtonEnabled(True)
        self._obj_search.setStyleSheet(
            f"QLineEdit{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
            f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 7px;font-size:9pt;}}"
            f"QLineEdit:focus{{border:1px solid {COLORS['accent_blue']};}}"
        )
        self._obj_search.textChanged.connect(self._on_obj_search)
        rl.addWidget(self._obj_search)

        self._obj_list = QListWidget()
        self._obj_list.setFixedHeight(110)
        self._obj_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self._obj_list.setStyleSheet(
            f"QListWidget{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
            f"border-radius:4px;color:{COLORS['text_primary']};font-size:8.5pt;outline:none;}}"
            f"QListWidget::item{{padding:3px 8px;border-bottom:1px solid {COLORS['border']}22;}}"
            f"QListWidget::item:selected{{background:{COLORS['accent_blue']}33;"
            f"color:{COLORS['accent_blue']};}}"
            f"QListWidget::item:hover:!selected{{background:{COLORS['bg_hover']};}}"
        )
        self._obj_list.itemSelectionChanged.connect(self._on_obj_selection)
        rl.addWidget(self._obj_list)

        self._obj_lbl = QLabel("All objects")
        self._obj_lbl.setStyleSheet(
            f"font-size:7.5pt;color:{COLORS['text_muted']};background:transparent;border:none;"
        )
        rl.addWidget(self._obj_lbl)

        self._obj_nomatch_lbl = QLabel("No matching objects.")
        self._obj_nomatch_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};background:transparent;border:none;"            "font-style:italic;"
        )
        self._obj_nomatch_lbl.hide()
        rl.addWidget(self._obj_nomatch_lbl)

        # ── Style — unified per-element ───────────────────────────────────────
        rl.addWidget(sec("Style"))

        style_hint = QLabel("Select Legend / Title / Chart above\nthen adjust its style below.")
        style_hint.setWordWrap(True)
        style_hint.setStyleSheet(
            f"font-size:7.5pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;font-style:italic;"
        )
        rl.addWidget(style_hint)

        # Background color row
        bg_row = QHBoxLayout(); bg_row.setSpacing(6)
        bg_row.addWidget(lbl("Background"))
        self._bg_btn = ColorButton(COLORS["bg_card"])
        bg_row.addWidget(self._bg_btn); bg_row.addStretch()
        rl.addLayout(bg_row)

        # Font color row
        fc_row = QHBoxLayout(); fc_row.setSpacing(6)
        fc_row.addWidget(lbl("Font color"))
        self._fc_btn = ColorButton(COLORS["text_primary"])
        fc_row.addWidget(self._fc_btn); fc_row.addStretch()
        rl.addLayout(fc_row)

        # Font family
        rl.addWidget(lbl("Font family"))
        self._font_cb = QComboBox(); self._font_cb.setStyleSheet(cb_s)
        for f in ["DejaVu Sans","Arial","Times New Roman","Courier New",
                  "Verdana","Georgia","Trebuchet MS"]:
            self._font_cb.addItem(f, userData=f)
        rl.addWidget(self._font_cb)

        # Font size
        rl.addWidget(lbl("Font size (pt)"))
        self._font_sz = QSpinBox(); self._font_sz.setRange(6, 28)
        self._font_sz.setValue(9); self._font_sz.setStyleSheet(sp_s)
        rl.addWidget(self._font_sz)

        # Apply button
        btn_apply_style = make_btn("✔  Apply style to selection")
        btn_apply_style.clicked.connect(self._apply_elem_style)
        rl.addWidget(btn_apply_style)

        # Show/hide legend
        self._show_leg = QCheckBox("Show legend")
        self._show_leg.setChecked(True)
        self._show_leg.setStyleSheet(
            f"QCheckBox{{color:{COLORS['text_primary']};font-size:8.5pt;"
            "background:transparent;border:none;}")
        rl.addWidget(self._show_leg)

        # Global figure background (always applies)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{COLORS['border']};"); rl.addWidget(sep2)
        rl.addWidget(lbl("Figure background"))
        fig_bg_row = QHBoxLayout(); fig_bg_row.setSpacing(6)
        self._fig_bg_btn = ColorButton(COLORS["bg_card"])
        fig_bg_row.addWidget(self._fig_bg_btn); fig_bg_row.addStretch()
        rl.addLayout(fig_bg_row)

        # Series color swatches
        rl.addWidget(lbl("Series colors  (bars / lines / groups)"))
        self._color_btns: list = []
        colors_grid = QGridLayout(); colors_grid.setSpacing(4)
        for i in range(8):
            cb = ColorButton(PALETTE[i % len(PALETTE)])
            self._color_btns.append(cb)
            colors_grid.addWidget(cb, i // 4, i % 4)
        rl.addLayout(colors_grid)

        # Internal per-element style storage (populated by _apply_elem_style)
        self._elem_styles = {"legend": {}, "title": {}, "axes": {}}

        rl.addStretch()
        rscroll.setWidget(ri)
        root.addWidget(rscroll)

        # Default selection
        self._type_btns["bar"].setChecked(True)
        self._on_type("bar")

    def _on_type(self, key):
        self._current_type = key
        ct = CHART_KEY_MAP[key]
        self._title_lbl.setText(f"{ct[2]}  {ct[1]}  —  {ct[3]}")
        px,py,pc,ps = (self._x.current_field(), self._y.current_field(),
                       self._c.current_field(), self._sz.current_field())
        # Default first category field name (may be None if no categories)
        dcat = self._dynamic_fields[0]["key"] if self._dynamic_fields else "obj_name"
        defs = {
            "bar":    ("obj_name","cit_count"),
            "stacked_bar":("art_year","cit_count"), "line":("art_year","cit_count"),
            "area":   ("art_year","cit_count"),  "scatter":("rv_value","cit_count"),
            "bubble": ("rv_value","cit_count"),  "pie":   (dcat,"cit_count"),
            "donut":  (dcat,"cit_count"),        "heatmap":("art_year","obj_name"),
            "histogram":("rv_value",None),       "boxplot":(dcat,"rv_value"),
        }
        dx, dy = defs.get(key, ("obj_name","cit_count"))
        ef = self._dynamic_fields
        self._x.populate(key, "x",     px or dx, extra_fields=ef)
        self._y.populate(key, "y",     py or dy, extra_fields=ef)
        self._c.populate(key, "color", pc,        extra_fields=ef)
        self._sz.populate(key,"size",  ps,         extra_fields=ef)
        self._sz.setEnabled(key=="bubble")
        self._y.setEnabled(key!="histogram")
        idx = self._agg.findData("count" if key in ("pie","donut","histogram","boxplot") else "sum")
        self._agg.setCurrentIndex(max(0,idx))

    def _on_scope_toggle(self, checked):
        if checked:
            self._scope_btn.setText("🔬 Found in articles")
        else:
            self._scope_btn.setText("📋 All objects")

    def _cfg(self):
        es = self._elem_styles if hasattr(self, '_elem_styles') else {}
        # Collect dynamic category filters
        cat_filters = {}
        for i, cw in enumerate(getattr(self, '_cat_filter_combos', [])):
            v = cw.currentData()
            if v: cat_filters[f"obj_cat_{i}"] = v
        return {
            "chart_key":   self._current_type,
            "x_field":     self._x.current_field(),
            "y_field":     self._y.current_field(),
            "color_field": self._c.current_field(),
            "size_field":  self._sz.current_field(),
            "agg_func":    self._agg.currentData(),
            "max_items":   self._max.value(),
            "bins":        self._bins.value(),
            "scope":       "cited" if self._scope_btn.isChecked() else "all",
            "object_filter": self._obj_filter,
            "filters": {
                **cat_filters,
                "rv_parameter": self._f_par.currentData(),
                "art_journal":  self._f_jrn.currentData(),
            },
            "style": {
                "bg_color":      self._fig_bg_btn.color(),
                "show_legend":   self._show_leg.isChecked(),
                "series_colors": [b.color() for b in self._color_btns],
                # Per-element overrides
                "legend_style":  dict(es.get("legend", {})),
                "title_style":   dict(es.get("title",  {})),
                "axes_style":    dict(es.get("axes",   {})),
                # legend_xy injected by ChartElementMover at runtime
            },
        }

    def _apply_elem_style(self):
        """Save current style controls into the per-element style dict for the active target."""
        target = getattr(self._mover, '_target', 'axes') if self._mover else 'axes'
        self._elem_styles[target] = {
            "bg_color":    self._bg_btn.color(),
            "font_color":  self._fc_btn.color(),
            "font_family": self._font_cb.currentData(),
            "font_size":   self._font_sz.value(),
        }
        # Immediately update the style indicator on the mover button
        label_map = {"legend": "📌 Legend", "title": "📝 Title", "axes": "📐 Chart"}
        if target in self._mover_btns:
            styled = f"● {label_map[target].split(' ',1)[1]}"
            # add dot indicator to show it has custom style
            self._mover_btns[target].setToolTip(
                f"Custom style applied — {self._elem_styles[target]}")

    def _set_move_target(self, key: str):
        self._mover.set_target(key)
        # Load that element's current style into the controls
        es = self._elem_styles.get(key, {})
        if es.get("bg_color"):    self._bg_btn.set_color(es["bg_color"])
        if es.get("font_color"):  self._fc_btn.set_color(es["font_color"])
        if es.get("font_family"):
            idx = self._font_cb.findData(es["font_family"])
            if idx >= 0: self._font_cb.setCurrentIndex(idx)
        if es.get("font_size"):   self._font_sz.setValue(es["font_size"])
        self.canvas.setFocus()

    def _nudge(self, dx: float, dy: float):
        self._mover.nudge(dx, dy)

    def _canvas_key_press(self, event):
        from PyQt5.QtCore import Qt as _Qt
        shift = bool(event.modifiers() & _Qt.ShiftModifier)
        step  = MOVE_STEP_FAST if shift else MOVE_STEP
        key   = event.key()
        mapping = {
            _Qt.Key_Left:  (-step,  0),   _Qt.Key_A: (-step,  0),
            _Qt.Key_Right: ( step,  0),   _Qt.Key_D: ( step,  0),
            _Qt.Key_Up:    (  0,  step),  _Qt.Key_W: (  0,  step),
            _Qt.Key_Down:  (  0, -step),  _Qt.Key_S: (  0, -step),
        }
        if key in mapping:
            self._mover.nudge(*mapping[key])
        else:
            type(self.canvas).__bases__[0].keyPressEvent(self.canvas, event)

    def _draw(self):
        cfg = self._cfg()
        if not cfg.get("x_field"):
            Toast.show_toast(self,"Select at least an X axis field","warning"); return
        self._mover.set_config(cfg)
        self.renderer.render(self.canvas, cfg, self.engine)
        self.canvas.setFocus()

    def _pin(self):
        cfg = self._cfg()
        if not cfg.get("x_field"):
            Toast.show_toast(self,"Configure the chart first","warning"); return
        self.chart_saved.emit(cfg)
        Toast.show_toast(self,"Chart pinned to dashboard","success")

    def _save(self):
        path,_ = QFileDialog.getSaveFileName(self,"Save Chart","chart.png",
                                              "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if path:
            self.canvas.fig.savefig(path,dpi=150,bbox_inches='tight',facecolor=COLORS["bg_card"])
            Toast.show_toast(self,"Saved","success")

    def _populate_obj_list(self, names: list):
        """Populate the object list widget. Preserves current selection by name."""
        prev_sel = self._obj_filter or set()
        self._obj_list.blockSignals(True)
        self._obj_list.clear()
        for name in names:
            item = QListWidgetItem(name)
            self._obj_list.addItem(item)
            # Select all by default (no filter active), or restore previous
            if not prev_sel or name in prev_sel:
                item.setSelected(True)
        self._obj_list.blockSignals(False)
        self._sync_obj_filter()

    def _on_obj_search(self, text: str):
        """Filter the visible items in the list as the user types."""
        q = text.strip().lower()
        self._obj_list.blockSignals(True)
        visible = 0
        for i in range(self._obj_list.count()):
            item = self._obj_list.item(i)
            match = (q in item.text().lower()) if q else True
            item.setHidden(not match)
            if match:
                visible += 1
        self._obj_list.blockSignals(False)
        # Show no-match feedback if search is active but nothing visible
        has_filter = bool(q)
        if hasattr(self, "_obj_nomatch_lbl"):
            self._obj_nomatch_lbl.setVisible(has_filter and visible == 0)

    def _on_obj_selection(self):
        self._sync_obj_filter()

    def _sync_obj_filter(self):
        """Update _obj_filter from current list selection."""
        all_names = {self._obj_list.item(i).text()
                     for i in range(self._obj_list.count())}
        sel = {self._obj_list.item(i).text()
               for i in range(self._obj_list.count())
               if self._obj_list.item(i).isSelected()}
        if sel == all_names or not sel:
            self._obj_filter = None
            self._obj_lbl.setText("All objects")
        else:
            self._obj_filter = sel
            n = len(sel)
            self._obj_lbl.setText(f"{n} object{'s' if n != 1 else ''} selected")

    def refresh_filters(self, engine):
        self.engine = engine
        # Update dynamic category fields from engine
        self._dynamic_fields = engine.dynamic_cat_fields()
        cat_names = engine.cat_column_names   # e.g. ["Class", "Subclass", "Trophic Level"]

        def _fill(cb, fk, src):
            prev = cb.currentData()
            cb.blockSignals(True); cb.clear()
            cb.addItem("— All —", userData=None)
            for v in engine.unique_values(fk, src): cb.addItem(v, userData=v)
            if prev:
                idx=cb.findData(prev)
                if idx>=0: cb.setCurrentIndex(idx)
            cb.blockSignals(False)

        # Rebuild dynamic category filter rows in sidebar
        # We keep a list of (label_widget, combo_widget) per cat level
        if not hasattr(self, '_cat_filter_labels'):
            self._cat_filter_labels = []
            self._cat_filter_combos = []

        # Remove old dynamic cat filter widgets
        for lw, cw in zip(self._cat_filter_labels, self._cat_filter_combos):
            lw.setParent(None); lw.deleteLater()
            cw.setParent(None); cw.deleteLater()
        self._cat_filter_labels.clear()
        self._cat_filter_combos.clear()

        # Insert new ones before _f_par in the right sidebar layout
        cb_s = (
            f"QComboBox{{background:{COLORS['bg_tertiary']};"
            f"border:1px solid {COLORS['border']};border-radius:4px;"
            f"color:{COLORS['text_primary']};padding:3px 8px;font-size:9pt;}}"
            f"QComboBox::drop-down{{border:none;padding-right:6px;}}"
            f"QComboBox QAbstractItemView{{background:{COLORS['bg_secondary']};"
            f"border:1px solid {COLORS['border']};"
            f"selection-background-color:{COLORS['bg_hover']};"
            f"color:{COLORS['text_primary']};}}"
        )
        lbl_style = (f"font-size:8pt;color:{COLORS['text_secondary']};"
                     "background:transparent;border:none;")

        rl = self._filter_layout   # reference stored during _build
        par_idx = rl.indexOf(self._f_par_lbl)  # insert before Parameter label

        for i, name in enumerate(cat_names):
            fk = f"obj_cat_{i}"
            lw = QLabel(name); lw.setStyleSheet(lbl_style)
            cw = QComboBox(); cw.setStyleSheet(cb_s)
            cw.addItem("— All —", userData=None)
            for v in engine.unique_values(fk, "objects"):
                cw.addItem(v, userData=v)
            self._cat_filter_labels.append(lw)
            self._cat_filter_combos.append(cw)
            rl.insertWidget(par_idx + i*2,     lw)
            rl.insertWidget(par_idx + i*2 + 1, cw)

        _fill(self._f_par, "rv_parameter", "review")
        _fill(self._f_jrn, "art_journal",  "citations")

        # Populate the inline object list
        all_names = sorted({r.get("obj_name","")
                            for r in engine.get_flat_records("citations")
                            if r.get("obj_name","")})
        if not all_names:
            all_names = sorted(o["name"] for o in engine.objects if o.get("name",""))
        self._obj_search.clear()
        self._populate_obj_list(all_names)

        # Refresh axis field combos with new dynamic fields
        self._on_type(self._current_type)


class DashCard(QWidget):
    """Borderless chart card — just a title strip + canvas."""
    removed = pyqtSignal(object)

    def __init__(self, config, engine, renderer, parent=None):
        super().__init__(parent)
        self.config=config; self.engine=engine; self.renderer=renderer
        self.setMinimumHeight(180)
        self.setStyleSheet(f"background:{COLORS['bg_card']};border:none;")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Minimal title strip — only visible on hover via opacity trick
        hdr = QWidget()
        hdr.setFixedHeight(28)
        hdr.setStyleSheet(
            f"background:{COLORS['bg_secondary']}33;"   # very subtle, almost transparent
            "border:none;"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 0, 4, 0)

        ct  = CHART_KEY_MAP.get(config["chart_key"], ("?","?","?","?"))
        xl  = FIELD_MAP.get(config.get("x_field",""),{}).get("label","?")
        yl  = FIELD_MAP.get(config.get("y_field",""),{}).get("label","")
        title = config.get("title") or (f"{ct[2]} {yl} by {xl}" if yl else f"{ct[2]} {xl}")

        # Scope badge
        scope = config.get("scope","cited")
        scope_lbl = QLabel("🔬" if scope=="cited" else "📋")
        scope_lbl.setToolTip("Found in articles only" if scope=="cited" else "All objects")
        scope_lbl.setStyleSheet("background:transparent;border:none;font-size:9pt;")
        hl.addWidget(scope_lbl)

        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;"
        )
        hl.addWidget(lbl, 1)

        for txt, fn, hover_col in [
            ("↺", self._draw, COLORS['text_secondary']),
            ("✕", lambda: self.removed.emit(self), COLORS['accent_rose']),
        ]:
            b = QPushButton(txt)
            b.setFixedSize(20, 20)
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;"
                f"color:{COLORS['text_muted']};font-size:10pt;}}"
                f"QPushButton:hover{{color:{hover_col};}}"
            )
            b.clicked.connect(fn)
            hl.addWidget(b)

        root.addWidget(hdr)
        self.canvas = MplCanvas(5, 3)
        root.addWidget(self.canvas, 1)
        self._draw()

    def _draw(self):
        self.renderer.render(self.canvas, self.config, self.engine)


class DashboardTab(QWidget):
    def __init__(self, engine, renderer, parent=None):
        super().__init__(parent)
        self.engine=engine; self.renderer=renderer; self._cards=[]
        self.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Info bar
        info = QLabel(
            "📌  Pin charts from the Builder. "
            "Drag the dividers between charts to resize. "
            "Click ✕ to remove."
        )
        info.setStyleSheet(
            f"background:{COLORS['bg_secondary']};color:{COLORS['text_muted']};"
            f"padding:5px 16px;font-size:8pt;"
            f"border-bottom:1px solid {COLORS['border']};border:none;"
        )
        root.addWidget(info)

        # Outer vertical splitter (rows)
        self._vsplit = QSplitter(Qt.Vertical)
        self._vsplit.setHandleWidth(6)
        self._vsplit.setStyleSheet(
            f"QSplitter::handle{{background:{COLORS['bg_primary']};}}"
            "QSplitter::handle:hover{background:#334155;}"
        )
        self._vsplit.setChildrenCollapsible(False)
        root.addWidget(self._vsplit, 1)

        self._empty = EmptyState("📊","No charts yet",
                                 "Build a chart and click 📌 Pin to add it here")
        root.addWidget(self._empty)

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _make_row_splitter(self):
        """Create a horizontal splitter row."""
        hs = QSplitter(Qt.Horizontal)
        hs.setHandleWidth(6)
        hs.setStyleSheet(
            f"QSplitter::handle{{background:{COLORS['bg_primary']};}}"
            "QSplitter::handle:hover{background:#334155;}"
        )
        hs.setChildrenCollapsible(False)
        return hs

    def add_card(self, config):
        card = DashCard(config, self.engine, self.renderer)
        card.removed.connect(self._rm)
        self._cards.append(card)
        self._relayout()
        self._empty.setVisible(False)

    def _rm(self, card):
        self._cards.remove(card)
        card.deleteLater()
        self._relayout()
        self._empty.setVisible(len(self._cards) == 0)

    def _relayout(self):
        # Remove all rows from the vertical splitter
        while self._vsplit.count():
            w = self._vsplit.widget(0)
            w.setParent(None)

        # Re-add cards in pairs into horizontal splitter rows
        for i in range(0, len(self._cards), 2):
            row = self._make_row_splitter()
            row.addWidget(self._cards[i])
            if i + 1 < len(self._cards):
                row.addWidget(self._cards[i + 1])
                row.setSizes([10000, 10000])  # equal width
            self._vsplit.addWidget(row)

        # Equal heights for all rows
        if self._vsplit.count():
            h = 10000
            self._vsplit.setSizes([h] * self._vsplit.count())

    def refresh_all(self, engine):
        self.engine = engine
        for card in self._cards:
            card.engine = engine
            card._draw()


class DataTableTab(QWidget):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine=engine; self._rows=[]
        self.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        root=QVBoxLayout(self); root.setContentsMargins(16,16,16,16); root.setSpacing(10)
        hdr=QHBoxLayout()
        lbl=QLabel("Data Tables")
        lbl.setStyleSheet(f"font-size:11pt;font-weight:700;color:{COLORS['text_primary']};background:transparent;border:none;")
        hdr.addWidget(lbl); hdr.addStretch()
        cb_s=(
            f"QComboBox{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
            f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 8px;}}"
            f"QComboBox::drop-down{{border:none;}}"
            f"QComboBox QAbstractItemView{{background:{COLORS['bg_secondary']};"
            f"border:1px solid {COLORS['border']};"
            f"selection-background-color:{COLORS['bg_hover']};"
            f"color:{COLORS['text_primary']};}}"
        )
        self._cb=QComboBox(); self._cb.setStyleSheet(cb_s)
        self._cb.addItems(["Citation counts","Citations by year","Articles per year",
                           "Citations by journal","Objects per article"])
        hdr.addWidget(self._cb)
        bl=make_btn("▶  Load",primary=True); bl.clicked.connect(self._load); hdr.addWidget(bl)
        be=make_btn("⬇  Export CSV"); be.clicked.connect(self._export); hdr.addWidget(be)
        root.addLayout(hdr)
        self._tbl=QTableWidget()
        self._tbl.setAlternatingRowColors(True)
        self._tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._tbl.setShowGrid(False)
        self._tbl.setStyleSheet(
            f"QTableWidget{{background:{COLORS['bg_primary']};border:none;}}"
            f"QTableWidget::item{{padding:4px 8px;color:{COLORS['text_primary']};}}"
            f"QHeaderView::section{{background:{COLORS['bg_secondary']};"
            f"color:{COLORS['text_secondary']};padding:4px 8px;border:none;"
            f"border-right:1px solid {COLORS['border']};font-size:8pt;font-weight:600;}}"
        )
        root.addWidget(self._tbl)

    def _load(self):
        db=self.engine.db; ch=self._cb.currentText()
        if   "counts"  in ch: data=[{"object":k,"articles_cited":v} for k,v in sorted(db.get_citation_counts().items(),key=lambda x:-x[1])]
        elif "by year" in ch and "Citation" in ch: data=db.get_citations_by_year()
        elif "per year" in ch: data=db.get_articles_per_year()
        elif "journal"  in ch: data=db.get_citations_by_journal()
        else:                  data=db.get_objects_per_article()
        self._rows=data
        if not data: self._tbl.setRowCount(0); self._tbl.setColumnCount(0); return
        cols=list(data[0].keys())
        self._tbl.setColumnCount(len(cols)); self._tbl.setRowCount(len(data))
        self._tbl.setHorizontalHeaderLabels(cols)
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._tbl.horizontalHeader().setStretchLastSection(True)
        for i,row in enumerate(data):
            for j,col in enumerate(cols):
                self._tbl.setItem(i,j,QTableWidgetItem(str(row.get(col,""))))

    def _export(self):
        if not self._rows: return
        path,_=QFileDialog.getSaveFileName(self,"Export","data.csv","CSV (*.csv)")
        if not path: return
        with open(path,"w",newline="",encoding="utf-8") as f:
            w=_csv.DictWriter(f,fieldnames=list(self._rows[0].keys()),extrasaction="ignore")
            w.writeheader(); w.writerows(self._rows)
        Toast.show_toast(self,"Exported","success")


class VizModule(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, db: Database):
        super().__init__()
        self.db       = db
        self.engine   = DataEngine(db)
        self.renderer = ChartRenderer()
        self._build_ui()

    def _build_ui(self):
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        hdr=QWidget(); hdr.setFixedHeight(60)
        hdr.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        hl=QHBoxLayout(hdr); hl.setContentsMargins(20,0,20,0)
        title=QLabel("Visualization")
        title.setStyleSheet(f"font-size:15pt;font-weight:700;color:{COLORS['text_primary']};background:transparent;border:none;")
        sub=QLabel("Interactive chart builder — pick a chart type, assign axes freely, pin to dashboard")
        sub.setStyleSheet(f"font-size:9pt;color:{COLORS['text_secondary']};background:transparent;border:none;")
        ts=QVBoxLayout(); ts.setSpacing(1); ts.addWidget(title); ts.addWidget(sub)
        hl.addLayout(ts); hl.addStretch()
        root.addWidget(hdr)
        self.tabs=QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab{min-width:140px;padding:8px 16px;}")
        root.addWidget(self.tabs)
        self._builder   = ChartBuilderPanel(self.engine)
        self._dashboard = DashboardTab(self.engine, self.renderer)
        self._datatable = DataTableTab(self.engine)
        self.tabs.addTab(self._builder,   "🎛  Chart Builder")
        self.tabs.addTab(self._dashboard, "📊  Dashboard")
        self.tabs.addTab(self._datatable, "🗃  Data Tables")
        self._builder.chart_saved.connect(self._dashboard.add_card)

    def refresh(self):
        self.engine.invalidate()
        self._builder.refresh_filters(self.engine)
        self._dashboard.refresh_all(self.engine)
        # Mark viz tabs as loaded so they won't auto-refresh on tab switch
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if w:
                w._tab_loaded = True
