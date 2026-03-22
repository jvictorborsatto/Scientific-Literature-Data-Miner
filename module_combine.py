"""
SLDM — Combine Module  (v5 — lazy / cached / stale-aware)

Performance rules:
  - Pool (articles + object terms) is built ONCE on Refresh or analysis change.
    It is NEVER rebuilt on tab switch or object selection change.
  - Co-occurrence search runs ONLY when the user clicks "Search".
  - Connection Map draws ONLY when user clicks "Draw Map".
  - Graph (Panel 3) plots ONLY on first data load OR when user clicks "↺ Refresh Graph".
    If the pool changes while on another tab, a ⚠ stale indicator appears.
  - Compare and Summary Table also show a ⚠ stale indicator after pool changes,
    and only rebuild when the user clicks "↺ Refresh".
  - Tab switching passes the cached pool to the panel but does NOT run any computation.
  - Sub-tabs in AnalysisModule are loaded lazily (only on first visit); a data_changed
    signal marks them dirty so they re-load on the next visit.
"""

import re, json, math
from collections import defaultdict

from PyQt5.QtWidgets import QDialog

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QListWidget, QListWidgetItem, QAbstractItemView,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QSplitter, QScrollArea, QCheckBox, QApplication,
    QFileDialog, QSizePolicy, QProgressBar, QMenu, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QPoint
from PyQt5.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QFontMetrics
)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

from core.theme import COLORS
from core.widgets import make_btn, Toast
from modules.module_mining import (
    ObjectSearchPanel,
    _strip_references,
    _strip_sections,
    SectionFilterDialog,
)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _lbl(text, muted=False, bold=False):
    l = QLabel(text)
    color = COLORS["text_muted"] if muted else COLORS["text_secondary"]
    w = "font-weight:700;" if bold else ""
    l.setStyleSheet(f"font-size:9pt;color:{color};{w}background:transparent;border:none;")
    return l

def _sec(text):
    l = QLabel(text)
    l.setStyleSheet(
        f"font-size:7.5pt;font-weight:700;color:{COLORS['text_muted']};"
        "letter-spacing:1px;background:transparent;border:none;margin-top:4px;"
    )
    return l

def _list_style():
    return f"""
QListWidget {{
    background:{COLORS['bg_secondary']};
    border:1px solid {COLORS['border']}; border-radius:4px;
    color:{COLORS['text_primary']}; font-size:9pt; outline:none;
}}
QListWidget::item {{ padding:5px 10px; border-bottom:1px solid {COLORS['border']}; }}
QListWidget::item:selected {{ background:{COLORS['accent_blue']}22; color:{COLORS['accent_blue']}; }}
QListWidget::item:hover:!selected {{ background:{COLORS['bg_hover']}; }}
"""

def _table_style():
    return f"""
QTableWidget {{
    background:{COLORS['bg_secondary']};
    alternate-background-color:{COLORS['bg_tertiary']};
    color:{COLORS['text_primary']}; gridline-color:{COLORS['border']};
    border:none; font-size:9pt;
}}
QHeaderView::section {{
    background:{COLORS['bg_primary']}; color:{COLORS['text_secondary']};
    font-size:8pt; font-weight:700; padding:5px 8px; border:none;
    border-bottom:1px solid {COLORS['border']};
    border-right:1px solid {COLORS['border']};
}}
QTableWidget::item {{ padding:4px 8px; border:none; }}
"""

def _cb_style():
    return (
        f"QComboBox{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
        f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 8px;font-size:9pt;}}"
        f"QComboBox::drop-down{{border:none;}}"
        f"QComboBox QAbstractItemView{{background:{COLORS['bg_secondary']};"
        f"color:{COLORS['text_primary']};border:1px solid {COLORS['border']};}}"
    )



ANALYSIS_COLORS = [
    "#4e9af1", "#2ecc71", "#e67e22", "#9b59b6",
    "#e74c3c", "#1abc9c", "#f39c12", "#3498db",
]


# ---------------------------------------------------------------------------
# MultiFilterWidget — replaces single QComboBox filter with multi-checkbox
# ---------------------------------------------------------------------------
class MultiFilterWidget(QWidget):
    """
    A compact button that shows how many items are selected.
    Clicking it opens a floating popup with checkboxes for each option.
    '— All —' behaves as a toggle-all shortcut.
    """
    selectionChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._options  = []           # list of str
        self._checked  = set()        # set of selected str (empty = All)
        self._popup    = None
        self._btn = QPushButton("— All —")
        self._btn.setStyleSheet(
            f"QPushButton{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
            f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 8px;font-size:9pt;"
            f"text-align:left;min-width:110px;}}"
            f"QPushButton:hover{{border-color:{COLORS['accent_blue']};}}"
        )
        self._btn.clicked.connect(self._open_popup)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._btn)

    # ── Public API ────────────────────────────────────────────────────────
    def set_options(self, options: list):
        """Set the list of available filter values (without '— All —')."""
        self._options = list(options)
        self._checked = set()   # reset to "All"
        self._update_label()

    def selected_values(self) -> set:
        """Returns the set of selected values, or empty set meaning 'All'."""
        return set(self._checked)

    def is_all(self) -> bool:
        return len(self._checked) == 0

    # ── Popup ─────────────────────────────────────────────────────────────
    def _open_popup(self):
        if self._popup and self._popup.isVisible():
            self._popup.close()
            return

        popup = QFrame(None, Qt.Popup | Qt.FramelessWindowHint)
        popup.setStyleSheet(
            f"QFrame{{background:{COLORS['bg_secondary']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;}}"
        )
        outer_vl = QVBoxLayout(popup)
        outer_vl.setContentsMargins(6, 6, 6, 6)
        outer_vl.setSpacing(4)

        # "— All —" row (always visible, outside scroll area)
        all_cb = QCheckBox("— All —")
        all_cb.setChecked(len(self._checked) == 0)
        all_cb.setStyleSheet(
            f"QCheckBox{{color:{COLORS['text_secondary']};font-size:9pt;padding:2px 4px;}}"
            f"QCheckBox:hover{{color:{COLORS['text_primary']};}}"
        )
        outer_vl.addWidget(all_cb)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{COLORS['border']};")
        outer_vl.addWidget(sep)

        # Scrollable area for the options
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:transparent;}}"
            f"QScrollBar:vertical{{background:{COLORS['bg_tertiary']};width:8px;border-radius:4px;}}"
            f"QScrollBar::handle:vertical{{background:{COLORS['border']};border-radius:4px;}}"
        )

        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        vl = QVBoxLayout(inner)
        vl.setContentsMargins(0, 0, 4, 0)
        vl.setSpacing(2)

        # One checkbox per option
        cbs = {}
        for opt in self._options:
            cb = QCheckBox(opt)
            cb.setChecked(opt in self._checked)
            cb.setStyleSheet(
                f"QCheckBox{{color:{COLORS['text_primary']};font-size:9pt;padding:2px 4px;}}"
                f"QCheckBox:hover{{color:{COLORS['accent_blue']};}}"
            )
            vl.addWidget(cb)
            cbs[opt] = cb

        scroll.setWidget(inner)

        # Limit popup height to avoid going off-screen
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        max_scroll_h = min(len(self._options) * 26 + 10, screen_h // 2)
        scroll.setFixedHeight(max_scroll_h)
        outer_vl.addWidget(scroll)

        # Wire "All" toggle
        def _all_toggled(state):
            if state:
                for c in cbs.values(): c.setChecked(False)

        def _item_toggled():
            any_checked = any(c.isChecked() for c in cbs.values())
            all_cb.blockSignals(True)
            all_cb.setChecked(not any_checked)
            all_cb.blockSignals(False)

        all_cb.stateChanged.connect(_all_toggled)
        for c in cbs.values(): c.stateChanged.connect(lambda _: _item_toggled())

        # Apply button
        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent_blue']};color:white;"
            "border:none;border-radius:4px;padding:5px 10px;font-size:9pt;margin-top:4px;}}"
            "QPushButton:hover{opacity:0.9;}"
        )
        def _apply():
            if all_cb.isChecked():
                self._checked = set()
            else:
                self._checked = {opt for opt, c in cbs.items() if c.isChecked()}
            self._update_label()
            popup.close()
            self.selectionChanged.emit()

        apply_btn.clicked.connect(_apply)
        outer_vl.addWidget(apply_btn)

        # Position below button, adjusting if it would go off-screen
        popup.adjustSize()
        global_pos = self._btn.mapToGlobal(QPoint(0, self._btn.height() + 2))
        popup.move(global_pos)
        popup.show()
        self._popup = popup

    def _update_label(self):
        if not self._checked:
            self._btn.setText("— All —")
        elif len(self._checked) == 1:
            self._btn.setText(next(iter(self._checked)))
        else:
            self._btn.setText(f"{len(self._checked)} selected")




# ---------------------------------------------------------------------------
# Term matching
# ---------------------------------------------------------------------------
def _term_matches(term: str, text: str) -> bool:
    if not term or not text:
        return False
    escaped = re.escape(term)
    if len(term) < 4:
        return bool(re.search(r'(?<![A-Za-z0-9])' + escaped + r'(?![A-Za-z0-9])', text))
    return bool(re.search(r'\b' + escaped + r'\b', text, re.IGNORECASE))


def _parse_syns(raw) -> list:
    if isinstance(raw, str):
        try: items = json.loads(raw)
        except Exception: items = [raw]
    else:
        items = raw or []
    result = []
    for item in items:
        for part in str(item).split(';'):
            part = part.strip()
            if part: result.append(part)
    return result


def _obj_terms(obj: dict) -> list:
    terms = [obj["name"].strip()] if obj.get("name") else []
    terms += _parse_syns(obj.get("synonyms", []))
    return [t for t in terms if t]


def _article_text(article: dict) -> str:
    parts = []
    if article.get("abstract"): parts.append(article["abstract"])
    if article.get("raw_text"):  parts.append(article["raw_text"])
    return " ".join(parts)


def _apply_text_filters(text: str, exclude_refs: bool, excluded_sections: set) -> str:
    """Apply reference-strip and section-exclusion filters to article text."""
    if not text:
        return text
    if exclude_refs:
        text = _strip_references(text)
    if excluded_sections:
        text = _strip_sections(text, excluded_sections)
    return text


def _obj_hits_article(obj: dict, art_key: str, art: dict,
                      exclude_refs: bool, excluded_sections: set) -> bool:
    """
    Return True if `obj` is considered found in `art`.

    Priority:
      - If obj["article_keys"] is a set (citations mode): use membership check.
        Text filters are irrelevant here — the citation IS the ground truth.
      - If obj["article_keys"] is None (fallback/no-mining mode): fall back to
        text-match with filters applied.
    """
    ak = obj.get("article_keys")
    if ak is not None:
        return art_key in ak
    # Fallback: text match
    text = _apply_text_filters(art.get("text", "") or art.get("title", ""),
                               exclude_refs, excluded_sections)
    return any(_term_matches(t, text) for t in obj.get("terms", []))


# ---------------------------------------------------------------------------
# Pool builder  (called once per Refresh)
# ---------------------------------------------------------------------------
def build_pool(analyses: list) -> dict:
    """
    Build the cross-analysis pool using citations as the source of truth.

    Source priority:
      1. PRIMARY — citations table: records exactly which objects were found
         in which articles by the Mining/Analysis module. Only objects that
         actually appear in articles are included.
      2. FALLBACK — if an analysis has zero citations (Mining never ran),
         fall back to loading ALL objects and ALL articles for that analysis
         so the Combine module still works (text-match will handle filtering).

    Pool structure:
      pool["articles"][key] = {title, year, journal, text, "article_id": str,
                               "found_objects": {ana_name: set(object_names)}}
      pool["lists"][ana_name] = [{id, name, terms, category, subcategory,
                                   categories, "article_keys": set(keys)}]
      pool["ana_colors"][ana_name] = color_hex
    """
    pool = {"articles": {}, "lists": {}, "ana_colors": {}}

    for i, ana in enumerate(analyses):
        color = ANALYSIS_COLORS[i % len(ANALYSIS_COLORS)]
        pool["ana_colors"][ana.name] = color

        # ── 1. Try citations-based approach ──────────────────────────────
        try:
            citations = ana.db.get_citations()   # [{object_id, object_name, article_id, article_title, year, journal, ...}]
        except Exception:
            citations = []

        if citations:
            # Build a map: object_id → set of article_ids where it was found
            # Normalize all IDs to str — SQLite can return int or str depending on schema
            obj_article_ids: dict = {}
            article_ids_needed: set = set()

            for c in citations:
                oid = str(c["object_id"])
                aid = str(c["article_id"])
                obj_article_ids.setdefault(oid, set()).add(aid)
                article_ids_needed.add(aid)

            # Load full article records — key by str(id) to match citations
            try:
                all_articles = {str(a["id"]): a for a in ana.db.get_articles()}
            except Exception:
                all_articles = {}

            # Register articles in the shared pool
            # key = title_lower|year  (deduplicates cross-analysis)
            art_id_to_key: dict = {}    # article_id → pool key
            for aid in article_ids_needed:
                art = all_articles.get(aid)
                if art is None:
                    continue
                key = f"{art.get('title','').strip().lower()}|{art.get('year','')}"
                art_id_to_key[aid] = key
                if key not in pool["articles"]:
                    pool["articles"][key] = {
                        "title":         art.get("title", ""),
                        "year":          art.get("year", ""),
                        "journal":       art.get("journal", ""),
                        "text":          _article_text(art),
                        "article_id":    aid,
                        "found_objects": {},   # ana_name → set(obj_names) — filled below
                    }
                # Accumulate found_objects per analysis
                fo = pool["articles"][key].setdefault("found_objects", {})
                fo.setdefault(ana.name, set())

            # Load objects that appear in citations
            try:
                all_objs = {str(o["id"]): o for o in ana.db.get_objects()}
            except Exception:
                all_objs = {}

            obj_entries = []
            for oid, art_ids in obj_article_ids.items():
                o = all_objs.get(oid)
                if o is None or not o.get("name", "").strip():
                    continue
                # Map article_ids → pool keys
                art_keys = set()
                for aid in art_ids:
                    k = art_id_to_key.get(aid)
                    if k:
                        art_keys.add(k)
                        # Register object name in article's found_objects
                        fo = pool["articles"][k].setdefault("found_objects", {})
                        fo.setdefault(ana.name, set()).add(o["name"])

                obj_entries.append({
                    "id":          o["id"],
                    "name":        o["name"],
                    "terms":       _obj_terms(o),
                    "category":    o.get("category", "").strip(),
                    "subcategory": o.get("subcategory", "").strip(),
                    "categories":  o.get("categories") or [],
                    "article_keys": art_keys,   # pool keys of articles where found
                })

            pool["lists"][ana.name] = obj_entries

        else:
            # ── 2. Fallback: no citations — load everything, text-match later ─
            try:
                objs = ana.db.get_objects()
            except Exception:
                objs = []
            pool["lists"][ana.name] = [
                {"id": o["id"], "name": o["name"], "terms": _obj_terms(o),
                 "category":    o.get("category", "").strip(),
                 "subcategory": o.get("subcategory", "").strip(),
                 "categories":  o.get("categories") or [],
                 "article_keys": None}   # None = not known, must text-match
                for o in objs if o.get("name", "").strip()
            ]
            try:
                articles = ana.db.get_articles()
            except Exception:
                articles = []
            for art in articles:
                key = f"{art.get('title','').strip().lower()}|{art.get('year','')}"
                if key not in pool["articles"]:
                    pool["articles"][key] = {
                        "title":         art.get("title", ""),
                        "year":          art.get("year", ""),
                        "journal":       art.get("journal", ""),
                        "text":          _article_text(art),
                        "article_id":    art.get("id", ""),
                        "found_objects": {},
                    }

    return pool


# ===========================================================================
# CombineModule
# ===========================================================================
class CombineModule(QWidget):
    data_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._analyses = []
        self._pool = {}
        self._exclude_refs: bool = True
        self._excluded_sections: set = set()
        self._build_ui()

    def set_analyses(self, analyses: list):
        self._analyses = analyses
        self._refresh_all()

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        hdr = QWidget(); hdr.setFixedHeight(56)
        hdr.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 0, 20, 0)
        title = QLabel("Combine")
        title.setStyleSheet(
            f"font-size:15pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;")
        sub = QLabel("Cross-analysis co-occurrence — shared article pool")
        sub.setStyleSheet(
            f"font-size:9pt;color:{COLORS['text_secondary']};background:transparent;border:none;")
        ts = QVBoxLayout(); ts.setSpacing(1); ts.addWidget(title); ts.addWidget(sub)
        hl.addLayout(ts); hl.addStretch()
        self._pool_lbl = QLabel("")
        self._pool_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};background:transparent;border:none;")
        hl.addWidget(self._pool_lbl)

        # ── Skip References toggle ────────────────────────────────────────
        self._btn_excl_refs = QPushButton("📚  Skip References: ON")
        self._btn_excl_refs.setCheckable(True)
        self._btn_excl_refs.setChecked(True)
        self._btn_excl_refs.setFixedHeight(28)
        self._btn_excl_refs.clicked.connect(self._toggle_exclude_refs)
        self._update_refs_btn_style()
        hl.addWidget(self._btn_excl_refs)

        # ── Section Filters button ────────────────────────────────────────
        self._btn_section_filter = QPushButton("🗂  Section Filters")
        self._btn_section_filter.setFixedHeight(28)
        self._btn_section_filter.setToolTip(
            "Choose which article sections (Introduction, Methods, Results, etc.)\n"
            "are included or excluded from the search text."
        )
        self._btn_section_filter.clicked.connect(self._open_section_filter_dialog)
        self._update_section_filter_btn_style()
        hl.addWidget(self._btn_section_filter)

        btn_r = make_btn("↺  Rebuild Pool"); btn_r.clicked.connect(self._refresh_all)
        hl.addWidget(btn_r)
        root.addWidget(hdr)

        body = QSplitter(Qt.Horizontal)
        body.setStyleSheet(f"QSplitter::handle{{background:{COLORS['border']};width:1px;}}")

        sel_pane = QWidget()
        sel_pane.setMinimumWidth(190); sel_pane.setMaximumWidth(240)
        sel_pane.setStyleSheet(
            f"background:{COLORS['bg_secondary']};border-right:1px solid {COLORS['border']};")
        sl = QVBoxLayout(sel_pane); sl.setContentsMargins(12,12,12,12); sl.setSpacing(8)
        sl.addWidget(_sec("SELECT ANALYSES"))
        sl.addWidget(_lbl("Changing selection rebuilds the pool:", muted=True))
        self._ana_checks = []
        self._check_container = QWidget()
        self._check_container.setStyleSheet("background:transparent;border:none;")
        self._check_layout = QVBoxLayout(self._check_container)
        self._check_layout.setContentsMargins(0,4,0,4); self._check_layout.setSpacing(4)
        sl.addWidget(self._check_container); sl.addStretch()
        ba = make_btn("☑  Select all");  ba.clicked.connect(lambda: self._set_all(True))
        bn = make_btn("☐  Deselect all"); bn.clicked.connect(lambda: self._set_all(False))
        sl.addWidget(ba); sl.addWidget(bn)
        body.addWidget(sel_pane)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(self._tab_style())

        self._cooccur_panel = CoOccurrencePanel()
        self._connmap_panel = ConnectionMapPanel()
        self._graph_panel   = GraphPanel()
        self._tree_panel    = TreePanel()

        self._tabs.addTab(self._cooccur_panel, "Co-occurrence")
        self._tabs.addTab(self._connmap_panel, "Connection Map")
        self._tabs.addTab(self._graph_panel,   "Treemap")
        self._tabs.addTab(self._tree_panel,    "Hierarchical Tree")
        # Tab switch only passes pool — does NOT run any search
        self._tabs.currentChanged.connect(self._on_tab)
        body.addWidget(self._tabs)
        body.setSizes([210, 1100])
        root.addWidget(body, 1)

    def _tab_style(self):
        return f"""
        QTabWidget::pane {{ border:none; background:{COLORS['bg_primary']}; }}
        QTabBar::tab {{
            background:{COLORS['bg_tertiary']}; color:{COLORS['text_muted']};
            padding:7px 16px; border:none;
            border-right:1px solid {COLORS['border']}; font-size:9pt;
        }}
        QTabBar::tab:selected {{
            background:{COLORS['bg_primary']}; color:{COLORS['accent_blue']};
            border-bottom:2px solid {COLORS['accent_blue']};
        }}
        QTabBar::tab:hover:!selected {{
            background:{COLORS['bg_hover']}; color:{COLORS['text_primary']};
        }}
        """

    def _rebuild_checks(self):
        for cb in self._ana_checks:
            self._check_layout.removeWidget(cb); cb.deleteLater()
        self._ana_checks = []
        for i, ana in enumerate(self._analyses):
            color = ANALYSIS_COLORS[i % len(ANALYSIS_COLORS)]
            cb = QCheckBox(f"  {ana.name}"); cb.setChecked(True)
            cb.setStyleSheet(
                f"QCheckBox{{color:{color};font-size:9pt;font-weight:700;"
                "background:transparent;border:none;padding:2px;}"
                f"QCheckBox::indicator{{width:14px;height:14px;"
                f"border:2px solid {color};border-radius:3px;}}"
                f"QCheckBox::indicator:checked{{background:{color};}}"
            )
            # Analysis checkbox change → rebuild pool (cheap) but NOT search
            cb.toggled.connect(self._on_ana_changed)
            self._ana_checks.append(cb); self._check_layout.addWidget(cb)

    def _set_all(self, state):
        # Block signals while setting all, then rebuild once
        for cb in self._ana_checks:
            cb.blockSignals(True); cb.setChecked(state); cb.blockSignals(False)
        self._on_ana_changed()

    def _get_selected(self):
        return [ana for cb, ana in zip(self._ana_checks, self._analyses) if cb.isChecked()]

    def _on_ana_changed(self):
        """Analysis selection changed → rebuild pool, update selectors only."""
        self._rebuild_pool()
        self._push_pool_to_current_tab()

    def _on_tab(self, idx):
        """Tab switched → just pass pool to the new panel. No computation."""
        self._push_pool_to_current_tab()

    def _toggle_exclude_refs(self):
        self._exclude_refs = self._btn_excl_refs.isChecked()
        self._update_refs_btn_style()

    def _update_refs_btn_style(self):
        if self._exclude_refs:
            self._btn_excl_refs.setText("📚  Skip References: ON")
            self._btn_excl_refs.setStyleSheet(
                f"QPushButton {{ background: {COLORS['accent_teal']}22; color: {COLORS['accent_teal']}; "
                f"border: 1px solid {COLORS['accent_teal']}66; border-radius: 6px; padding: 4px 10px; font-size: 8pt; font-weight: 600; }}"
                f"QPushButton:hover {{ background: {COLORS['accent_teal']}40; }}"
            )
        else:
            self._btn_excl_refs.setText("📚  Skip References: OFF")
            self._btn_excl_refs.setStyleSheet(
                f"QPushButton {{ background: {COLORS['accent_amber']}22; color: {COLORS['accent_amber']}; "
                f"border: 1px solid {COLORS['accent_amber']}66; border-radius: 6px; padding: 4px 10px; font-size: 8pt; font-weight: 600; }}"
                f"QPushButton:hover {{ background: {COLORS['accent_amber']}40; }}"
            )

    def _update_section_filter_btn_style(self):
        n = len(self._excluded_sections)
        if n:
            self._btn_section_filter.setText(f"🗂  Section Filters ({n} excluded)")
            self._btn_section_filter.setStyleSheet(
                f"QPushButton {{ background: {COLORS['accent_violet']}22; color: {COLORS['accent_violet']}; "
                f"border: 1px solid {COLORS['accent_violet']}66; border-radius: 6px; padding: 4px 10px; font-size: 8pt; font-weight: 600; }}"
                f"QPushButton:hover {{ background: {COLORS['accent_violet']}40; }}"
            )
        else:
            self._btn_section_filter.setText("🗂  Section Filters")
            self._btn_section_filter.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {COLORS['text_secondary']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 6px; padding: 4px 10px; font-size: 8pt; }}"
                f"QPushButton:hover {{ background: {COLORS['bg_hover']}; }}"
            )

    def _open_section_filter_dialog(self):
        dlg = SectionFilterDialog(self, self._excluded_sections)
        if dlg.exec_() == QDialog.Accepted:
            self._excluded_sections = dlg.get_excluded()
            self._update_section_filter_btn_style()

    def _get_text_filters(self) -> tuple:
        """Return (exclude_refs, excluded_sections) for passing to panels."""
        return self._exclude_refs, self._excluded_sections

    def refresh(self):
        self._refresh_all()

    def refresh_theme(self):
        """Re-apply all inline styles after a theme change."""
        self._tabs.setStyleSheet(self._tab_style())
        self._update_refs_btn_style()
        self._update_section_filter_btn_style()
        # Re-apply panels that use inline COLORS
        for panel in [self._cooccur_panel, self._connmap_panel,
                      self._graph_panel, self._tree_panel]:
            if hasattr(panel, 'refresh_theme'):
                panel.refresh_theme()

    def _refresh_all(self):
        self._rebuild_checks()
        self._rebuild_pool()
        self._push_pool_to_current_tab()

    def _rebuild_pool(self):
        selected = self._get_selected()
        self._pool = build_pool(selected)
        n_art = len(self._pool.get("articles", {}))
        n_obj = sum(len(v) for v in self._pool.get("lists", {}).values())
        self._pool_lbl.setText(
            f"Pool: {n_art} art · {n_obj} obj · {len(self._pool.get('lists',{}))} lists"
        )

    def _push_pool_to_current_tab(self):
        """
        Passes the pool to the active panel so it can update its UI widgets
        (object lists, anchor combo, etc.) WITHOUT running any heavy search.
        """
        excl_refs, excl_secs = self._get_text_filters()
        idx = self._tabs.currentIndex()
        if   idx == 0: self._cooccur_panel.set_pool(self._pool, excl_refs, excl_secs)
        elif idx == 1: self._connmap_panel.set_pool(self._pool, excl_refs, excl_secs)
        elif idx == 2: self._graph_panel.set_pool(self._pool, excl_refs, excl_secs)
        elif idx == 3: self._tree_panel.set_pool(self._pool, excl_refs, excl_secs)


# ===========================================================================
# ObjectSelector  (no auto-search wired)
# ===========================================================================
class ObjectSelector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._blocks = []
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{COLORS['bg_secondary']};}}")
        self._container = QWidget()
        self._container.setStyleSheet(f"background:{COLORS['bg_secondary']};")
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8,8,8,8); self._layout.setSpacing(10)
        self._layout.addStretch()
        scroll.setWidget(self._container)
        root.addWidget(scroll)

    def rebuild(self, pool: dict):
        from PyQt5.QtCore import QTimer
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.hide(); w.setParent(None)
                    QTimer.singleShot(0, w.deleteLater)
        self._blocks = []
        lists = pool.get("lists", {}); colors = pool.get("ana_colors", {})
        if not lists:
            self._layout.insertWidget(0, _lbl("No analyses selected.", muted=True)); return
        for ana_name, objs in lists.items():
            color = colors.get(ana_name, "#888")
            grp = QWidget()
            grp.setStyleSheet(
                f"background:{COLORS['bg_primary']};border:1px solid {color}44;border-radius:6px;")
            gl = QVBoxLayout(grp); gl.setContentsMargins(8,8,8,8); gl.setSpacing(4)
            hr_w = QWidget(); hr_w.setStyleSheet("background:transparent;border:none;")
            hr = QHBoxLayout(hr_w); hr.setContentsMargins(0,0,0,0); hr.setSpacing(4)
            lbl = QLabel(f"{ana_name}  ({len(objs)})")
            lbl.setStyleSheet(
                f"font-size:9pt;font-weight:700;color:{color};background:transparent;border:none;")
            hr.addWidget(lbl); hr.addStretch()
            for txt in ["All", "None"]:
                btn = QPushButton(txt); btn.setFixedHeight(20)
                btn.setStyleSheet(
                    f"QPushButton{{font-size:7.5pt;background:{COLORS['bg_tertiary']};"
                    f"color:{COLORS['text_muted']};border:1px solid {COLORS['border']};"
                    f"border-radius:3px;padding:0 5px;}}"
                    f"QPushButton:hover{{color:{COLORS['text_primary']};}}")
                hr.addWidget(btn)
            gl.addWidget(hr_w)
            lw = QListWidget(); lw.setStyleSheet(_list_style())
            lw.setSelectionMode(QAbstractItemView.MultiSelection)
            lw.setMaximumHeight(150)
            for obj in sorted(objs, key=lambda x: x["name"]):
                it = QListWidgetItem(obj["name"]); it.setData(Qt.UserRole, obj); lw.addItem(it)
            lw.selectAll()
            btns = hr_w.findChildren(QPushButton)
            btns[0].clicked.connect(lambda _, w=lw: w.selectAll())
            btns[1].clicked.connect(lambda _, w=lw: w.clearSelection())
            # !! No search/draw connected here — user must press the action button
            gl.addWidget(lw)
            self._layout.insertWidget(self._layout.count()-1, grp)
            self._blocks.append((ana_name, lw, objs))

    def get_selected(self) -> dict:
        result = {}
        for ana_name, lw, all_objs in self._blocks:
            selected = [lw.item(j).data(Qt.UserRole) for j in range(lw.count())
                        if lw.item(j).isSelected()]
            result[ana_name] = selected if selected else list(all_objs)
        return result


# ===========================================================================
# Panel 1 — Co-occurrence
# ===========================================================================
class CoOccurrencePanel(QWidget):
    def __init__(self):
        super().__init__()
        self._pool = {}
        self._exclude_refs: bool = True
        self._excluded_sections: set = set()
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(12,12,12,12); root.setSpacing(8)
        info = _lbl(
            "Pool-based search: reads article text/abstract directly. "
            "Select objects to include, then press Search.",
            muted=True)
        info.setWordWrap(True); root.addWidget(info)

        # ── Object search panel (cross-analysis) ─────────────────────────────
        self._obj_search = ObjectSearchPanel(analyses=[])
        self._obj_search.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;"
        )
        root.addWidget(self._obj_search)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle{{background:{COLORS['border']};width:1px;}}")

        left = QWidget(); ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(4)
        left.setMaximumWidth(320)
        self._obj_sel = ObjectSelector(); ll.addWidget(self._obj_sel, 1)
        splitter.addWidget(left)

        right = QWidget(); rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)
        self._stats_lbl = QLabel("Press Search to find co-occurrences.")
        self._stats_lbl.setWordWrap(True)
        self._stats_lbl.setStyleSheet(
            f"font-size:9pt;color:{COLORS['accent_blue']};padding:6px 10px;"
            f"background:{COLORS['bg_secondary']};border-radius:4px;border:none;")
        rl.addWidget(self._stats_lbl)

        ctrl = QWidget(); ctrl.setStyleSheet("background:transparent;border:none;")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(0,0,0,0); cl.setSpacing(8)
        self._btn_run = make_btn("🔍  Search Co-occurrences")
        self._btn_run.clicked.connect(self._run)
        cl.addWidget(self._btn_run)
        self._progress = QProgressBar(); self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{COLORS['bg_tertiary']};border:none;border-radius:3px;}}"
            f"QProgressBar::chunk{{background:{COLORS['accent_blue']};border-radius:3px;}}")
        self._progress.hide(); cl.addWidget(self._progress, 1)
        btn_csv = make_btn("⬇  Export CSV"); btn_csv.clicked.connect(self._export)
        cl.addWidget(btn_csv)
        rl.addWidget(ctrl)

        self._table = QTableWidget(); self._table.setStyleSheet(_table_style())
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        rl.addWidget(self._table, 1)
        splitter.addWidget(right); splitter.setSizes([300, 900])
        root.addWidget(splitter, 1)

    def set_pool(self, pool: dict, exclude_refs: bool = True, excluded_sections: set = None):
        """Called when pool changes. Only rebuilds the object selector UI — no search."""
        self._pool = pool
        self._exclude_refs = exclude_refs
        self._excluded_sections = excluded_sections or set()
        self._obj_sel.rebuild(pool)
        # Update search panel with current analyses
        anas = [type('_A', (), {'name': n, 'db': None})() for n in pool.get("lists", {})]
        # We need real analysis objects with db — store pool reference instead
        self._obj_search._pool_ref = pool
        self._obj_search.update_analyses_from_pool(pool)
        self._stats_lbl.setText(
            f"Pool ready: {len(pool.get('articles', {}))} articles — press Search.")

    def refresh_theme(self):
        """Re-apply inline styles after theme change."""
        self._obj_search.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;"
        )
        self._stats_lbl.setStyleSheet(
            f"font-size:9pt;color:{COLORS['accent_blue']};padding:6px 10px;"
            f"background:{COLORS['bg_secondary']};border-radius:4px;border:none;"
        )
        self._table.setStyleSheet(_table_style())
        self._obj_sel.setStyleSheet(_list_style())

    def _run(self):
        self._table.clear()
        arts = dict(self._pool.get("articles", {}))
        lists = self._pool.get("lists", {})
        if not arts:
            self._stats_lbl.setText("No articles in pool."); return
        if len(lists) < 2:
            self._stats_lbl.setText("Need at least 2 analyses."); return

        # Apply object search filter if active
        if self._obj_search.is_active():
            allowed_keys = self._obj_search.matching_pool_keys(self._pool)
            arts = {k: v for k, v in arts.items() if k in allowed_keys}
            if not arts:
                self._stats_lbl.setText("Object search found no matching articles.")
                return

        sel = self._obj_sel.get_selected()

        self._btn_run.setEnabled(False)
        self._progress.setRange(0, len(arts)); self._progress.setValue(0); self._progress.show()

        results = []
        for i, (art_key, art) in enumerate(arts.items()):
            self._progress.setValue(i + 1)
            if i % 20 == 0: QApplication.processEvents()

            hits = {}
            for ana_name, objs in sel.items():
                matched = [o["name"] for o in objs
                           if _obj_hits_article(o, art_key, art,
                                                self._exclude_refs, self._excluded_sections)]
                if matched:
                    hits[ana_name] = matched

            if len(hits) >= 2:
                results.append({"title": art["title"], "year": art["year"],
                                "journal": art["journal"], "hits": hits,
                                "n_lists": len(hits)})

        self._progress.hide(); self._btn_run.setEnabled(True)
        results.sort(key=lambda x: -x["n_lists"])

        self._stats_lbl.setText(
            f"  {len(results)} article(s) with objects from 2+ lists  "
            f"(searched {len(arts)} articles)")

        if not results:
            self._table.setRowCount(1); self._table.setColumnCount(1)
            self._table.setHorizontalHeaderLabels(["Result"])
            self._table.setItem(0, 0, QTableWidgetItem(
                "No co-occurrences found. Verify that Mining has been run on both analyses.")); return

        list_names = list(sel.keys()); colors = self._pool.get("ana_colors", {})
        headers = ["Article", "Year", "Journal"] + list_names + ["# Lists"]
        self._table.setRowCount(len(results)); self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        for ri, r in enumerate(results):
            self._table.setItem(ri, 0, QTableWidgetItem(r["title"]))
            yr = QTableWidgetItem(str(r["year"] or ""))
            yr.setTextAlignment(Qt.AlignCenter); self._table.setItem(ri, 1, yr)
            self._table.setItem(ri, 2, QTableWidgetItem(r["journal"] or ""))
            for ci, lname in enumerate(list_names):
                objs = r["hits"].get(lname, [])
                cell = QTableWidgetItem(", ".join(objs) if objs else "—")
                cell.setForeground(QColor(colors.get(lname,"#888") if objs else COLORS["text_muted"]))
                self._table.setItem(ri, 3+ci, cell)
            cnt = QTableWidgetItem(str(r["n_lists"]))
            cnt.setTextAlignment(Qt.AlignCenter)
            cnt.setForeground(QColor("#2ecc71" if r["n_lists"] >= 3 else "#4e9af1"))
            self._table.setItem(ri, len(headers)-1, cnt)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)

    def _export(self):
        import csv
        path, _ = QFileDialog.getSaveFileName(self, "Export", "cooccurrences.csv", "CSV (*.csv)")
        if not path: return
        headers = [self._table.horizontalHeaderItem(c).text() for c in range(self._table.columnCount())]
        rows = [[self._table.item(r,c).text() if self._table.item(r,c) else ""
                 for c in range(self._table.columnCount())] for r in range(self._table.rowCount())]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(headers); w.writerows(rows)
        Toast.show_toast(self, f"Exported: {path}", "success")


# ===========================================================================
# Panel 2 — Connection Map  (co-occurrence matrix — Solvent Miscibility style)
# ===========================================================================
class ConnectionMapPanel(QWidget):
    """
    Displays a symmetric co-occurrence matrix between objects/categories
    from two analyses (X axis vs Y axis).  Each cell shows how many articles
    contain both the row-item and the column-item simultaneously.
    Filled square = co-occurrence > 0  (colour = number of articles).
    Empty square  = no co-occurrence.
    The count is printed inside each filled cell.
    """

    def __init__(self):
        super().__init__()
        self._pool = {}
        self._exclude_refs: bool = True
        self._excluded_sections: set = set()
        self._matrix = None   # 2-D list of counts
        self._row_labels = []
        self._col_labels = []
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Controls ──────────────────────────────────────────────────────
        ctrl = QWidget(); ctrl.setStyleSheet("background:transparent;border:none;")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(10)

        # Row axis (Y)
        cl.addWidget(_sec("ROW AXIS (Y):"))
        cl.addWidget(_lbl("Analysis:", muted=True))
        self._row_ana_cb = QComboBox(); self._row_ana_cb.setStyleSheet(_cb_style())
        self._row_ana_cb.setMinimumWidth(120)
        self._row_ana_cb.currentTextChanged.connect(self._on_row_ana_changed)
        cl.addWidget(self._row_ana_cb)

        cl.addWidget(_lbl("Group by:", muted=True))
        self._row_grp_cb = QComboBox(); self._row_grp_cb.setStyleSheet(_cb_style())
        self._row_grp_cb.addItems(["Objects", "Category 1"])
        self._row_grp_cb.currentTextChanged.connect(self._on_row_grp_changed)
        cl.addWidget(self._row_grp_cb)

        cl.addWidget(_lbl("Filter:", muted=True))
        self._row_filt_cb = QComboBox(); self._row_filt_cb.setStyleSheet(_cb_style())
        self._row_filt_cb.setMinimumWidth(110); self._row_filt_cb.addItem("— All —")
        cl.addWidget(self._row_filt_cb)

        cl.addWidget(QLabel("   "))  # visual gap

        # Col axis (X)
        cl.addWidget(_sec("COL AXIS (X):"))
        cl.addWidget(_lbl("Analysis:", muted=True))
        self._col_ana_cb = QComboBox(); self._col_ana_cb.setStyleSheet(_cb_style())
        self._col_ana_cb.setMinimumWidth(120)
        self._col_ana_cb.currentTextChanged.connect(self._on_col_ana_changed)
        cl.addWidget(self._col_ana_cb)

        cl.addWidget(_lbl("Group by:", muted=True))
        self._col_grp_cb = QComboBox(); self._col_grp_cb.setStyleSheet(_cb_style())
        self._col_grp_cb.addItems(["Objects", "Category 1"])
        self._col_grp_cb.currentTextChanged.connect(self._on_col_grp_changed)
        cl.addWidget(self._col_grp_cb)

        cl.addWidget(_lbl("Filter:", muted=True))
        self._col_filt_cb = QComboBox(); self._col_filt_cb.setStyleSheet(_cb_style())
        self._col_filt_cb.setMinimumWidth(110); self._col_filt_cb.addItem("— All —")
        cl.addWidget(self._col_filt_cb)

        cl.addWidget(QLabel("   "))

        # Top-N per axis
        cl.addWidget(_sec("TOP N:"))
        self._topn_cb = QComboBox(); self._topn_cb.setStyleSheet(_cb_style())
        self._topn_cb.addItems(["10", "15", "20", "30", "All"])
        self._topn_cb.setCurrentText("20")
        cl.addWidget(self._topn_cb)

        cl.addStretch()
        btn_draw = make_btn("▶  Draw Matrix"); btn_draw.clicked.connect(self._draw)
        cl.addWidget(btn_draw)
        btn_exp = make_btn("Export"); btn_exp.clicked.connect(self._export)
        cl.addWidget(btn_exp)
        root.addWidget(ctrl)

        # ── Legend row ────────────────────────────────────────────────────
        leg = QWidget(); leg.setStyleSheet("background:transparent;border:none;")
        ll = QHBoxLayout(leg); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(18)
        for color, label in [("#4e9af1", "Co-occurrence (low)"),
                             ("#f39c12", "Co-occurrence (med)"),
                             ("#e74c3c", "Co-occurrence (high)"),
                             (COLORS["bg_secondary"], "No co-occurrence")]:
            dot = QLabel("■")
            dot.setStyleSheet(f"font-size:14pt;color:{color};background:transparent;border:none;")
            txt = _lbl(label, muted=True)
            ll.addWidget(dot); ll.addWidget(txt)
        ll.addStretch()
        root.addWidget(leg)

        # ── Matrix canvas ─────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{COLORS['bg_primary']};}}")
        self._matrix_canvas = CoOccurrenceMatrixCanvas()
        self._scroll.setWidget(self._matrix_canvas)
        root.addWidget(self._scroll, 1)

    # ── Pool ──────────────────────────────────────────────────────────────
    def set_pool(self, pool: dict, exclude_refs: bool = True, excluded_sections: set = None):
        self._pool = pool
        self._exclude_refs = exclude_refs
        self._excluded_sections = excluded_sections or set()
        anas = list(pool.get("lists", {}).keys())

        for cb in (self._row_ana_cb, self._col_ana_cb):
            prev = cb.currentText()
            cb.blockSignals(True); cb.clear(); cb.addItems(anas)
            if prev in anas: cb.setCurrentText(prev)
            cb.blockSignals(False)

        # Default: row = first analysis, col = second (if exists)
        if len(anas) >= 2 and not self._row_ana_cb.currentText():
            self._row_ana_cb.setCurrentText(anas[0])
            self._col_ana_cb.setCurrentText(anas[1])

        # Populate Group-by combos with actual category levels found in pool
        self._refresh_grp_combos()
        self._refresh_row_filter()
        self._refresh_col_filter()

    def _max_cat_levels(self) -> int:
        """Return the maximum number of category levels across all pool objects."""
        mx = 0
        for objs in self._pool.get("lists", {}).values():
            for o in objs:
                mx = max(mx, len(o.get("categories") or []))
        return max(mx, 1)

    def _refresh_grp_combos(self):
        n = self._max_cat_levels()
        items = ["Objects"] + [f"Category {i+1}" for i in range(n)]
        for cb in (self._row_grp_cb, self._col_grp_cb):
            prev = cb.currentText()
            cb.blockSignals(True); cb.clear(); cb.addItems(items)
            if prev in items: cb.setCurrentText(prev)
            cb.blockSignals(False)

    def _on_row_ana_changed(self):  self._refresh_row_filter()
    def _on_row_grp_changed(self):  self._refresh_row_filter()
    def _on_col_ana_changed(self):  self._refresh_col_filter()
    def _on_col_grp_changed(self):  self._refresh_col_filter()

    @staticmethod
    def _cat_val(obj: dict, group: str) -> str:
        """Extract grouping value from obj dict based on 'Objects'/'Category N' string."""
        if group == "Objects":
            return obj["name"]
        if group.startswith("Category "):
            try:
                idx = int(group.split()[-1]) - 1
                cats = obj.get("categories") or []
                return cats[idx].strip() if idx < len(cats) else ""
            except (ValueError, IndexError):
                return ""
        return obj["name"]

    def _get_label_values(self, ana: str, group: str) -> set:
        objs = self._pool.get("lists", {}).get(ana, [])
        if group == "Objects":
            return set()   # no meaningful filter for individual objects
        return {self._cat_val(o, group) for o in objs if self._cat_val(o, group)}

    def _refresh_row_filter(self):
        values = self._get_label_values(
            self._row_ana_cb.currentText(), self._row_grp_cb.currentText())
        self._row_filt_cb.blockSignals(True)
        self._row_filt_cb.clear(); self._row_filt_cb.addItem("— All —")
        for v in sorted(values): self._row_filt_cb.addItem(v)
        self._row_filt_cb.blockSignals(False)

    def _refresh_col_filter(self):
        values = self._get_label_values(
            self._col_ana_cb.currentText(), self._col_grp_cb.currentText())
        self._col_filt_cb.blockSignals(True)
        self._col_filt_cb.clear(); self._col_filt_cb.addItem("— All —")
        for v in sorted(values): self._col_filt_cb.addItem(v)
        self._col_filt_cb.blockSignals(False)

    # ── Build axis labels ─────────────────────────────────────────────────
    def _build_labels(self, ana: str, group: str, filt: str) -> list:
        """Return list of (label, terms, article_keys_or_None).

        article_keys is the union of article_keys across all objects in the label
        group, or None if any object has article_keys=None (fallback text-match mode).
        """
        objs = self._pool.get("lists", {}).get(ana, [])
        label_terms    = defaultdict(list)
        label_art_keys = defaultdict(set)
        label_has_none = set()

        for o in objs:
            lbl = self._cat_val(o, group) or o["name"]
            if filt != "— All —":
                if self._cat_val(o, group) != filt:
                    continue
            label_terms[lbl].extend(o.get("terms", []))
            ak = o.get("article_keys")
            if ak is None:
                label_has_none.add(lbl)
            else:
                label_art_keys[lbl].update(ak)

        result = []
        for lbl in sorted(label_terms):
            terms    = label_terms[lbl]
            art_keys = None if lbl in label_has_none else label_art_keys[lbl]
            result.append((lbl, terms, art_keys))
        return result

    # ── Draw ──────────────────────────────────────────────────────────────
    def _draw(self):
        pool = self._pool
        if not pool.get("articles") or not pool.get("lists"):
            self._matrix_canvas.set_matrix([], [], []); return

        row_ana   = self._row_ana_cb.currentText()
        row_grp   = self._row_grp_cb.currentText()
        row_filt  = self._row_filt_cb.currentText()
        col_ana   = self._col_ana_cb.currentText()
        col_grp   = self._col_grp_cb.currentText()
        col_filt  = self._col_filt_cb.currentText()
        topn_txt  = self._topn_cb.currentText()
        topn      = None if topn_txt == "All" else int(topn_txt)

        row_items = self._build_labels(row_ana, row_grp, row_filt)  # [(lbl, terms)]
        col_items = self._build_labels(col_ana, col_grp, col_filt)

        if not row_items or not col_items:
            self._matrix_canvas.set_matrix([], [], []); return

        # Count co-occurrences: matrix[r][c] = # articles where row_lbl AND col_lbl both appear
        n_r, n_c = len(row_items), len(col_items)
        matrix = [[0]*n_c for _ in range(n_r)]

        for art_key, art in pool["articles"].items():
            # Which row labels hit this article?
            row_hits = set()
            for ri, (lbl, terms, art_keys) in enumerate(row_items):
                if art_keys is not None:
                    if art_key in art_keys:
                        row_hits.add(ri)
                else:
                    text = _apply_text_filters(
                        art.get("text", "") or art.get("title", ""),
                        self._exclude_refs, self._excluded_sections)
                    if any(_term_matches(t, text) for t in terms):
                        row_hits.add(ri)
            if not row_hits:
                continue

            # Which col labels hit this article?
            col_hits = set()
            for ci, (lbl, terms, art_keys) in enumerate(col_items):
                if art_keys is not None:
                    if art_key in art_keys:
                        col_hits.add(ci)
                else:
                    text = _apply_text_filters(
                        art.get("text", "") or art.get("title", ""),
                        self._exclude_refs, self._excluded_sections)
                    if any(_term_matches(t, text) for t in terms):
                        col_hits.add(ci)
            if not col_hits:
                continue

            for ri in row_hits:
                for ci in col_hits:
                    matrix[ri][ci] += 1

        # Apply Top-N: keep rows/cols with most total hits
        if topn:
            row_totals = [sum(matrix[r]) for r in range(n_r)]
            top_rows = sorted(range(n_r), key=lambda i: -row_totals[i])[:topn]
            top_rows = sorted(top_rows)
            col_totals = [sum(matrix[r][c] for r in range(n_r)) for c in range(n_c)]
            top_cols = sorted(range(n_c), key=lambda i: -col_totals[i])[:topn]
            top_cols = sorted(top_cols)
            row_items  = [row_items[i] for i in top_rows]
            col_items  = [col_items[i] for i in top_cols]
            matrix = [[matrix[r][c] for c in top_cols] for r in top_rows]

        row_labels = [lbl for lbl, _, _ in row_items]
        col_labels = [lbl for lbl, _, _ in col_items]

        # Axis colors
        row_color = ANALYSIS_COLORS[
            list(pool["lists"].keys()).index(row_ana) % len(ANALYSIS_COLORS)
            if row_ana in pool["lists"] else 0]
        col_color = ANALYSIS_COLORS[
            list(pool["lists"].keys()).index(col_ana) % len(ANALYSIS_COLORS)
            if col_ana in pool["lists"] else 1]

        self._matrix_canvas.set_matrix(
            row_labels, col_labels, matrix,
            row_ana=row_ana, col_ana=col_ana,
            row_color=row_color, col_color=col_color)
        # Cache for CSV export
        self._last_row_labels = row_labels
        self._last_col_labels = col_labels
        self._last_matrix     = matrix

    def _export(self):
        path, filt = QFileDialog.getSaveFileName(
            self, "Export", "matrix",
            "PNG (*.png);;CSV (*.csv);;PDF (*.pdf);;SVG (*.svg)")
        if not path: return
        if filt.startswith("CSV") or path.endswith(".csv"):
            self._export_csv(path)
        else:
            self._matrix_canvas.export(path)

    def _export_csv(self, path=None):
        import csv as _csv
        row_labels = getattr(self, '_last_row_labels', [])
        col_labels = getattr(self, '_last_col_labels', [])
        matrix     = getattr(self, '_last_matrix', [])
        if not row_labels:
            Toast.show_toast(self, "Draw the matrix first", "warning"); return
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "matrix.csv", "CSV (*.csv)")
            if not path: return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow([""] + col_labels)
            for ri, rl in enumerate(row_labels):
                w.writerow([rl] + list(matrix[ri]))
        Toast.show_toast(self, f"Exported: {path}", "success")


# ---------------------------------------------------------------------------
# CoOccurrenceMatrixCanvas — Qt-native painter (no matplotlib needed)
# ---------------------------------------------------------------------------
class CoOccurrenceMatrixCanvas(QWidget):
    """
    Draws a grid where:
      - rows = Y-axis labels (painted rotated on the left)
      - cols = X-axis labels (painted rotated on top, ending at matrix edge)
      - filled cell = co-occurrence count > 0  (colour intensity ∝ count)
      - number printed inside each filled cell
      - empty cell = dark square, no number
    Hovering a cell highlights row + column header and shows a tooltip.
    """
    CELL = 34          # base cell size px
    HEADER_W = 160     # left header width px
    FONT_SIZE = 8
    _MARGIN_TOP = 24   # extra space above the rotated labels for axis name

    def __init__(self):
        super().__init__()
        self._row_labels = []
        self._col_labels = []
        self._matrix = []
        self._row_ana = ""; self._col_ana = ""
        self._row_color = "#4e9af1"; self._col_color = "#2ecc71"
        self._hovered = (-1, -1)
        self._max_val = 1
        self._header_h = 160   # computed dynamically in set_matrix
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ── helpers ───────────────────────────────────────────────────────────
    @property
    def HEADER_H(self):
        return self._header_h

    def _compute_header_h(self, col_labels, font_size):
        """Compute the minimum top-header height so rotated labels don't overlap the grid."""
        if not col_labels:
            return 120
        from PyQt5.QtGui import QFontMetrics, QFont
        f = QFont(); f.setPointSize(font_size - 1)
        fm = QFontMetrics(f)
        max_len = max(fm.horizontalAdvance(lbl[:22]) for lbl in col_labels)
        # Text rotated -45°: vertical extent ≈ len * sin(45°) + cell/2 * cos(45°)
        import math
        h = int(max_len * math.sin(math.radians(45))) + self.CELL + self._MARGIN_TOP
        return max(h, 80)

    def set_matrix(self, row_labels, col_labels, matrix,
                   row_ana="", col_ana="", row_color="#4e9af1", col_color="#2ecc71"):
        self._row_labels = row_labels
        self._col_labels = col_labels
        self._matrix = matrix
        self._row_ana = row_ana
        self._col_ana = col_ana
        self._row_color = row_color
        self._col_color = col_color
        self._hovered = (-1, -1)
        flat = [v for row in matrix for v in row if v > 0]
        self._max_val = max(flat) if flat else 1
        # Compute dynamic header height from label lengths
        self._header_h = self._compute_header_h(col_labels, self.FONT_SIZE)
        # Resize widget to fit content
        n_r = len(row_labels); n_c = len(col_labels)
        W = self.HEADER_W + n_c * self.CELL + 80   # extra for legend bar
        H = self._header_h + n_r * self.CELL + 10
        self.setMinimumSize(max(W, 300), max(H, 300))
        self.update()

    def _cell_rect(self, r, c):
        x = self.HEADER_W + c * self.CELL
        y = self.HEADER_H + r * self.CELL
        return x, y

    def _cell_at(self, px, py):
        if px < self.HEADER_W or py < self.HEADER_H:
            return -1, -1
        c = (px - self.HEADER_W) // self.CELL
        r = (py - self.HEADER_H) // self.CELL
        if 0 <= r < len(self._row_labels) and 0 <= c < len(self._col_labels):
            return r, c
        return -1, -1

    def _cell_color(self, val):
        """Interpolate colour: dark bg → accent_blue → amber → red."""
        if val == 0:
            return QColor(COLORS["bg_secondary"])
        t = min(val / self._max_val, 1.0)
        # Three-stop gradient: blue (t=0) → amber (t=0.5) → red (t=1)
        if t < 0.5:
            s = t * 2
            r = int(78  + s * (243 - 78))
            g = int(154 + s * (156 - 154))
            b = int(241 + s * (18  - 241))
        else:
            s = (t - 0.5) * 2
            r = int(243 + s * (231 - 243))
            g = int(156 + s * (76  - 156))
            b = int(18  + s * (60  - 18))
        return QColor(r, g, b)

    def mouseMoveEvent(self, event):
        r, c = self._cell_at(event.x(), event.y())
        if (r, c) != self._hovered:
            self._hovered = (r, c)
            self.update()
            if r >= 0:
                val = self._matrix[r][c]
                tip = (f"<b>{self._row_labels[r]}</b> × <b>{self._col_labels[c]}</b>"
                       f"<br>Co-occurrences: <b>{val}</b> article(s)")
                from PyQt5.QtWidgets import QToolTip
                QToolTip.showText(event.globalPos(), tip, self)
            else:
                from PyQt5.QtWidgets import QToolTip
                QToolTip.hideText()

    def leaveEvent(self, event):
        self._hovered = (-1, -1); self.update()

    def paintEvent(self, event):
        if not self._row_labels or not self._col_labels:
            p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(self.rect(), QColor(COLORS["bg_primary"]))
            p.setPen(QColor(COLORS["text_muted"]))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Configure axes and press  ▶ Draw Matrix")
            p.end(); return

        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(COLORS["bg_primary"]))

        n_r = len(self._row_labels)
        n_c = len(self._col_labels)
        C   = self.CELL
        HW  = self.HEADER_W
        HH  = self.HEADER_H
        hr, hc = self._hovered

        font_sm = QFont(); font_sm.setPointSize(self.FONT_SIZE)
        font_bold = QFont(); font_bold.setPointSize(self.FONT_SIZE); font_bold.setBold(True)
        font_lbl  = QFont(); font_lbl.setPointSize(self.FONT_SIZE - 1)
        fm = QFontMetrics(font_sm)

        # ── Draw cells ────────────────────────────────────────────────────
        for r in range(n_r):
            for c in range(n_c):
                val = self._matrix[r][c]
                x, y = self._cell_rect(r, c)
                is_hov = (r == hr or c == hc)
                cell_c = self._cell_color(val)

                # Hover highlight
                if is_hov and val == 0:
                    bg = QColor(COLORS["bg_tertiary"])
                elif is_hov:
                    bg = cell_c.lighter(130)
                else:
                    bg = cell_c

                p.fillRect(x, y, C - 1, C - 1, bg)

                # Border
                pen_col = QColor("#ffffff44") if (r == hr and c == hc) else QColor(COLORS["border"])
                p.setPen(QPen(pen_col, 0.5))
                p.drawRect(x, y, C - 1, C - 1)

                # Count label
                if val > 0:
                    p.setFont(font_bold if (r == hr and c == hc) else font_sm)
                    lum = 0.299*bg.red() + 0.587*bg.green() + 0.114*bg.blue()
                    p.setPen(QColor("white") if lum < 160 else QColor("#111"))
                    p.drawText(x, y, C - 1, C - 1, Qt.AlignCenter, str(val))

        # ── Row headers (left, horizontal text) ───────────────────────────
        for r in range(n_r):
            x, y = self._cell_rect(r, 0)
            is_hov = (r == hr)
            bg = QColor(self._row_color + "33") if is_hov else QColor(COLORS["bg_secondary"])
            p.fillRect(0, y, HW - 4, C - 1, bg)
            p.setFont(font_bold if is_hov else font_lbl)
            col = QColor(self._row_color) if is_hov else QColor(COLORS["text_secondary"])
            p.setPen(col)
            lbl = self._row_labels[r]
            # Truncate to fit
            max_w = HW - 12
            while fm.horizontalAdvance(lbl) > max_w and len(lbl) > 4:
                lbl = lbl[:-2] + "…"
            p.drawText(4, y, HW - 8, C - 1, Qt.AlignVCenter | Qt.AlignRight, lbl)

        # ── Col headers (top, rotated -45°) ──────────────────────────────
        # Strategy: pivot at the LEFT edge of each column's cell, at matrix top.
        # With rotate(-45°) the local X axis points upper-right, so drawText(0,0,lbl)
        # sends the text up-right into the header area — entirely above the matrix.
        p.save()
        for c in range(n_c):
            x, _ = self._cell_rect(0, c)
            is_hov = (c == hc)
            p.setFont(font_bold if is_hov else font_lbl)
            p.setPen(QColor(self._col_color) if is_hov else QColor(COLORS["text_secondary"]))
            lbl = self._col_labels[c][:24]
            cx = x          # left edge of the cell column
            cy = HH - 2     # just above the matrix top edge
            p.translate(cx, cy)
            p.rotate(-45)
            p.drawText(3, 0, lbl)   # small gap then text goes upper-right
            p.resetTransform()
        p.restore()

        # ── Axis name labels ──────────────────────────────────────────────
        font_axis = QFont(); font_axis.setPointSize(self.FONT_SIZE); font_axis.setBold(True)
        p.setFont(font_axis)

        # Row axis name (vertical, left side)
        if self._row_ana:
            p.save()
            p.setPen(QColor(self._row_color))
            total_h = n_r * C
            p.translate(12, HH + total_h // 2)
            p.rotate(-90)
            p.drawText(-60, 0, self._row_ana[:20])
            p.restore()

        # Col axis name (horizontal, very top — above the rotated labels)
        if self._col_ana:
            p.setPen(QColor(self._col_color))
            total_w = n_c * C
            p.drawText(HW, 2, total_w, self._MARGIN_TOP - 2,
                       Qt.AlignCenter, self._col_ana[:30])

        # ── Legend colour bar (bottom-right) ──────────────────────────────
        bar_x = HW + n_c * C + 12
        bar_y = HH
        bar_h = min(n_r * C, 180)
        bar_w = 14
        if bar_x + bar_w + 40 < self.width():
            for i in range(bar_h):
                t = 1.0 - i / bar_h
                p.setPen(self._cell_color(t * self._max_val))
                p.drawLine(bar_x, bar_y + i, bar_x + bar_w, bar_y + i)
            p.setPen(QColor(COLORS["text_muted"]))
            p.setFont(font_lbl)
            p.drawText(bar_x + bar_w + 2, bar_y + 8,       str(self._max_val))
            p.drawText(bar_x + bar_w + 2, bar_y + bar_h,   "0")

        p.end()

    def export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Matrix", "cooccurrence_matrix.png",
            "PNG (*.png);;PDF (*.pdf);;SVG (*.svg)")
        if not path:
            return
        if path.lower().endswith(".png"):
            pixmap = self.grab()
            pixmap.save(path, "PNG")
            Toast.show_toast(self, f"Exported: {path}", "success")
        elif HAS_MPL:
            # Render via matplotlib for PDF/SVG
            import numpy as np
            n_r, n_c = len(self._row_labels), len(self._col_labels)
            data = np.array(self._matrix, dtype=float)
            fig, ax = plt.subplots(figsize=(max(6, n_c*0.55), max(5, n_r*0.45)))
            fig.patch.set_facecolor(COLORS["bg_primary"])
            ax.set_facecolor(COLORS["bg_secondary"])
            masked = np.where(data == 0, np.nan, data)
            im = ax.imshow(masked, aspect="auto", cmap="YlOrRd",
                           interpolation="nearest", vmin=0)
            fig.colorbar(im, ax=ax, label="Co-occurrences", shrink=0.8)
            ax.set_xticks(range(n_c))
            ax.set_xticklabels(self._col_labels, rotation=45, ha="right",
                               color="white", fontsize=7)
            ax.set_yticks(range(n_r))
            ax.set_yticklabels(self._row_labels, color="white", fontsize=8)
            for r in range(n_r):
                for c in range(n_c):
                    v = data[r, c]
                    if v > 0:
                        ax.text(c, r, int(v), ha="center", va="center",
                                fontsize=7,
                                color="black" if v > self._max_val * 0.5 else "white")
            ax.set_xlabel(self._col_ana, color="white")
            ax.set_ylabel(self._row_ana, color="white")
            ax.tick_params(colors="white")
            for sp in ax.spines.values(): sp.set_edgecolor(COLORS["border"])
            fig.tight_layout()
            fig.savefig(path, dpi=150, bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            plt.close(fig)
            Toast.show_toast(self, f"Exported: {path}", "success")
        else:
            Toast.show_toast(self, "Install matplotlib for PDF/SVG export", "warning")




# ===========================================================================
# Treemap layout engine  (squarify algorithm — no external deps)
# ===========================================================================
def _treemap_layout(items: list, x: float, y: float, w: float, h: float) -> list:
    """
    items : [(label, value, color), ...]
    Returns [(label, value, color, rx, ry, rw, rh), ...] in pixels.
    Uses the squarify worst-aspect-ratio algorithm.
    """
    if not items or w <= 0 or h <= 0:
        return []
    total = sum(v for _, v, _ in items)
    if total <= 0:
        return []

    def _worst(row, length):
        if not row or length == 0:
            return float("inf")
        s = sum(v for _, v, _, _ in row)
        mx = max(v for _, v, _, _ in row)
        mn = min(v for _, v, _, _ in row)
        if s == 0 or mn == 0:
            return float("inf")
        return max(length**2 * mx / s**2, s**2 / (length**2 * mn))

    def _lay_row(row, rx, ry, rw, rh, horiz):
        s = sum(v for _, v, _, _ in row)
        rects, off = [], 0.0
        for lbl, v, col, orig_v in row:
            frac = (v / s) if s > 0 else 0
            if horiz:
                rects.append((lbl, orig_v, col, rx + off, ry, rw * frac, rh))
                off += rw * frac
            else:
                rects.append((lbl, orig_v, col, rx, ry + off, rw, rh * frac))
                off += rh * frac
        return rects

    def _sq(items, rx, ry, rw, rh):
        if not items:
            return []
        area = rw * rh
        total_v = sum(v for _, v, _ in items)
        normed = [(lbl, v * area / total_v, col, v) for lbl, v, col in items]

        results, row = [], []
        cx, cy, cw, ch = rx, ry, rw, rh

        for item in normed:
            horiz = cw >= ch
            length = cw if horiz else ch
            test = row + [item]
            if not row or _worst(test, length) <= _worst(row, length):
                row = test
            else:
                s = sum(v for _, v, _, _ in row)
                frac = s / (cw * ch) if (cw * ch) > 0 else 0
                if horiz:
                    results += _lay_row(row, cx, cy, cw, ch, False)
                    # Recompute actual width from original (not normed) values
                    # The row fills a vertical strip of width = frac*cw
                    actual_w = cw * frac
                    cx += actual_w; cw -= actual_w
                else:
                    results += _lay_row(row, cx, cy, cw, ch, True)
                    actual_h = ch * frac
                    cy += actual_h; ch -= actual_h
                row = [item]

        if row:
            horiz = cw >= ch
            results += _lay_row(row, cx, cy, cw, ch, not horiz)
        return results

    return _sq(items, x, y, w, h)


# ===========================================================================
# TreemapCanvas — Qt-native painter
# ===========================================================================
class TreemapCanvas(QWidget):
    PAD  = 2    # gap between tiles px
    FONT = 8    # base font size

    def __init__(self):
        super().__init__()
        self._rects = []          # list of (lbl, val, color, x, y, w, h)
        self._ana_legend = []     # [(ana_name, color)]
        self._title = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(300, 200)

    def set_data(self, rects, ana_legend, title=""):
        self._rects = rects
        self._ana_legend = ana_legend
        self._title = title
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(COLORS["bg_primary"]))

        if not self._rects:
            p.setPen(QColor(COLORS["text_muted"]))
            f = QFont(); f.setPointSize(11)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Configure grouping and press  ↺ Refresh")
            p.end(); return

        PAD = self.PAD
        for lbl, val, color, rx, ry, rw, rh in self._rects:
            rx, ry, rw, rh = int(rx)+PAD, int(ry)+PAD, int(rw)-PAD*2, int(rh)-PAD*2
            if rw < 6 or rh < 6:
                continue

            # ── Tile background ──────────────────────────────────────────
            tile_color = QColor(color)
            p.fillRect(rx, ry, rw, rh, tile_color)
            p.setPen(QColor(0, 0, 0, 55))
            p.drawRect(rx, ry, rw, rh)

            # ── Text colour from luminance ───────────────────────────────
            r2, g2, b2 = tile_color.red(), tile_color.green(), tile_color.blue()
            lum = 0.299*r2 + 0.587*g2 + 0.114*b2
            txt_col  = QColor("#111111") if lum > 140 else QColor("#ffffff")
            # Count label slightly more transparent
            cnt_col  = QColor(0, 0, 0, 160) if lum > 140 else QColor(255, 255, 255, 180)

            count_str = str(int(val))

            # ── Font sizes: scale to tile, name bigger than count ────────
            fs_name = max(7, min(self.FONT + 3, int(rh / 3.8), int(rw / 4)))
            fs_cnt  = max(6, min(fs_name - 1,  int(rh / 5.5), int(rw / 5)))

            font_name = QFont(); font_name.setPointSize(fs_name); font_name.setBold(True)
            font_cnt  = QFont(); font_cnt.setPointSize(fs_cnt);   font_cnt.setBold(False)
            fm_name   = QFontMetrics(font_name)
            fm_cnt    = QFontMetrics(font_cnt)

            # Truncate name to fit tile width
            short_lbl = lbl
            if fm_name.horizontalAdvance(lbl) > rw - 8:
                # Try character-by-character truncation
                for cut in range(len(lbl), 0, -1):
                    candidate = lbl[:cut] + "…"
                    if fm_name.horizontalAdvance(candidate) <= rw - 8:
                        short_lbl = candidate
                        break

            name_h = fm_name.height()
            cnt_h  = fm_cnt.height()
            needed = name_h + cnt_h + 6   # 6px gap between lines

            if rh >= needed:
                # ── Two lines: NAME (top) + count (bottom) ───────────────
                # Name — bold, top-left
                p.setFont(font_name)
                p.setPen(txt_col)
                p.drawText(rx + 5, ry + 5, rw - 10, name_h + 2,
                           Qt.AlignLeft | Qt.AlignTop, short_lbl)

                # Count — smaller, bottom-left, semi-transparent
                p.setFont(font_cnt)
                p.setPen(cnt_col)
                p.drawText(rx + 5, ry + rh - cnt_h - 5, rw - 10, cnt_h + 2,
                           Qt.AlignLeft | Qt.AlignBottom, count_str)

            elif rh >= name_h + 4:
                # ── One line: name only (tile too short for count) ───────
                p.setFont(font_name)
                p.setPen(txt_col)
                p.drawText(rx + 5, ry, rw - 10, rh,
                           Qt.AlignLeft | Qt.AlignVCenter, short_lbl)

        # ── Legend ────────────────────────────────────────────────────────
        if self._ana_legend:
            lx = PAD + 4
            ly = H - 22
            f_leg = QFont(); f_leg.setPointSize(7)
            p.setFont(f_leg)
            for ana, col in self._ana_legend:
                p.fillRect(lx, ly + 4, 12, 12, QColor(col))
                p.setPen(QColor(COLORS["text_secondary"]))
                p.drawText(lx + 15, ly, 200, 20, Qt.AlignVCenter, ana)
                lx += 15 + QFontMetrics(f_leg).horizontalAdvance(ana) + 16

        p.end()


# ===========================================================================
# Panel 3 — Graph  (Treemap — Qt-native, no matplotlib needed)
# ===========================================================================
class GraphPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._pool = {}
        self._exclude_refs: bool = True
        self._excluded_sections: set = set()
        self._pool_hash = None
        self._stale = False
        self._last_counts = None
        self._last_top    = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(12,12,12,12); root.setSpacing(8)

        # ── Controls ──────────────────────────────────────────────────────
        ctrl = QWidget(); ctrl.setStyleSheet("background:transparent;border:none;")
        cl = QHBoxLayout(ctrl); cl.setContentsMargins(0,0,0,0); cl.setSpacing(10)

        cl.addWidget(_sec("GROUP BY:"))
        self._xaxis_cb = QComboBox(); self._xaxis_cb.setStyleSheet(_cb_style())
        self._xaxis_cb.setMinimumWidth(130)
        self._xaxis_cb.addItems(["Objects"])
        self._xaxis_cb.currentTextChanged.connect(self._on_changed)
        cl.addWidget(self._xaxis_cb)

        cl.addStretch()
        self._stale_lbl = QLabel("⚠  Pool changed — press Refresh")
        self._stale_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['accent_amber']};background:transparent;border:none;")
        self._stale_lbl.hide()
        cl.addWidget(self._stale_lbl)

        self._btn_refresh = make_btn("↺  Refresh")
        self._btn_refresh.clicked.connect(self._force_plot)
        cl.addWidget(self._btn_refresh)
        btn_png = make_btn("Export PNG"); btn_png.clicked.connect(self._export_png)
        cl.addWidget(btn_png)
        btn_csv = make_btn("Export CSV"); btn_csv.clicked.connect(self._export_csv)
        cl.addWidget(btn_csv)

        root.addWidget(ctrl)

        # ── Treemap canvas ────────────────────────────────────────────────
        self._canvas = TreemapCanvas()
        root.addWidget(self._canvas, 1)

    # ── Pool interface ─────────────────────────────────────────────────────
    def set_pool(self, pool, exclude_refs=True, excluded_sections=None):
        self._pool = pool
        self._exclude_refs = exclude_refs
        self._excluded_sections = excluded_sections or set()
        # Repopulate group-by combo
        cats = set()
        for objs in pool.get("lists", {}).values():
            for o in objs:
                for c in (o.get("categories") or []):
                    if isinstance(c, dict):
                        cats.update(c.keys())
        self._xaxis_cb.blockSignals(True)
        prev = self._xaxis_cb.currentText()
        self._xaxis_cb.clear()
        self._xaxis_cb.addItem("Objects")
        for c in sorted(cats):
            self._xaxis_cb.addItem(c)
        idx = self._xaxis_cb.findText(prev)
        self._xaxis_cb.setCurrentIndex(max(idx, 0))
        self._xaxis_cb.blockSignals(False)

        new_hash = self._pool_fingerprint()
        if self._pool_hash is None:
            self._force_plot()
        else:
            self._stale = True
            self._stale_lbl.show()
        self._pool_hash = new_hash

    def _pool_fingerprint(self):
        arts  = len(self._pool.get("articles", {}))
        lists = sum(len(v) for v in self._pool.get("lists", {}).values())
        return (arts, lists, self._xaxis_cb.currentText())

    def refresh_theme(self): pass

    def _on_changed(self):
        self._stale = True
        self._stale_lbl.show()

    def _force_plot(self):
        self._stale_lbl.hide()
        self._btn_refresh.setEnabled(False)
        QApplication.processEvents()
        self._plot()
        self._pool_hash = self._pool_fingerprint()
        self._stale = False
        self._btn_refresh.setEnabled(True)

    # ── Counting ───────────────────────────────────────────────────────────
    def _count(self):
        """
        Count distinct articles per label per analysis.

        Uses pool["articles"][key]["found_objects"][ana] = set(obj_names)
        which is populated directly from citations during build_pool.
        This avoids any dependency on article_keys or text-match.

        Fallback: if found_objects is empty for an ana (old-style pool),
        use text-match against article text.
        """
        xaxis    = self._xaxis_cb.currentText()
        result   = defaultdict(lambda: defaultdict(int))
        articles = self._pool.get("articles", {})
        lists    = self._pool.get("lists", {})

        # Check if any object has found_objects populated (citations mode)
        has_found_objects = any(
            art.get("found_objects")
            for art in articles.values()
        )

        if has_found_objects and xaxis == "Objects":
            # Fast path: iterate articles and read found_objects directly
            for art_key, art in articles.items():
                fo = art.get("found_objects", {})
                for ana, obj_names in fo.items():
                    for obj_name in obj_names:
                        result[ana][obj_name] += 1

        else:
            # Category grouping or no found_objects: fall back to obj-level iteration
            for ana, objs in lists.items():
                for obj in objs:
                    if xaxis == "Objects":
                        label = obj["name"]
                    else:
                        label = ConnectionMapPanel._cat_val(obj, xaxis)
                        if not label:
                            continue

                    ak = obj.get("article_keys")
                    if ak is not None:
                        result[ana][label] += len(ak)
                    else:
                        for art_key, art in articles.items():
                            if _obj_hits_article(obj, art_key, art,
                                                 self._exclude_refs,
                                                 self._excluded_sections):
                                result[ana][label] += 1

        return result

    # ── Plot ───────────────────────────────────────────────────────────────
    def _plot(self):
        if not self._pool.get("articles"):
            self._canvas.set_data([], [])
            return

        counts    = self._count()
        colors    = self._pool.get("ana_colors", {})
        ana_names = list(counts.keys())

        if not ana_names:
            self._canvas.set_data([], [])
            return

        # Aggregate totals per label
        label_total: dict = defaultdict(int)
        label_ana:   dict = {}   # label → ana_name (dominant)
        for ana, c in counts.items():
            for lbl, n in c.items():
                label_total[lbl] += n
                if lbl not in label_ana or n > counts[label_ana[lbl]].get(lbl, 0):
                    label_ana[lbl] = ana

        # Sort descending by count — exclude objects with only 1 citation
        top = sorted(
            (lbl for lbl in label_total if label_total[lbl] > 1),
            key=lambda lx: -label_total[lx]
        )
        if not top:
            self._canvas.set_data([], [])
            return

        # Assign color: each label gets its dominant analysis color,
        # with slight lightness variation for multi-analysis labels
        def _tile_color(lbl):
            ana  = label_ana.get(lbl, ana_names[0])
            base = QColor(colors.get(ana, ANALYSIS_COLORS[0]))
            contributors = sum(1 for a in ana_names if counts[a].get(lbl, 0) > 0)
            if contributors > 1:
                base = base.lighter(115)
            return base.name()

        items = [(lbl, float(label_total[lbl]), _tile_color(lbl)) for lbl in top]

        # Layout into the canvas rect (leave 28px at bottom for legend)
        W = max(self._canvas.width(),  400)
        H = max(self._canvas.height(), 200)
        legend_h = 26 if len(ana_names) > 0 else 0
        rects = _treemap_layout(items, 0, 0, W, H - legend_h)

        # Filter out tiles whose area is < 20% of the largest tile's area
        if rects:
            max_area = max(rw * rh for _, _, _, _, _, rw, rh in rects)
            min_area = max_area * 0.20
            rects = [r for r in rects if r[5] * r[6] >= min_area]

        ana_legend = [(ana, colors.get(ana, ANALYSIS_COLORS[i % len(ANALYSIS_COLORS)]))
                      for i, ana in enumerate(ana_names)]

        xaxis = self._xaxis_cb.currentText()
        title = f"Citations per {xaxis if xaxis != 'Objects' else 'Object'}"
        self._canvas.set_data(rects, ana_legend, title)

        self._last_counts = counts
        self._last_top    = top

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._stale and self._pool_hash is not None:
            self._plot()   # re-layout on resize

    # ── Export ─────────────────────────────────────────────────────────────
    def _export_png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export PNG", "treemap.png", "PNG (*.png)")
        if not path:
            return
        pix = self._canvas.grab()
        pix.save(path, "PNG")
        Toast.show_toast(self, f"Exported: {path}", "success")

    def _export_csv(self):
        import csv as _csv
        counts = self._last_counts
        top    = self._last_top
        if not counts or not top:
            Toast.show_toast(self, "Refresh first", "warning"); return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "treemap.csv", "CSV (*.csv)")
        if not path: return
        ana_names = list(counts.keys())
        xaxis = self._xaxis_cb.currentText()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow([xaxis] + ana_names + ["total"])
            for lbl in top:
                row = [lbl] + [counts[ana].get(lbl, 0) for ana in ana_names]
                row.append(sum(counts[ana].get(lbl, 0) for ana in ana_names))
                w.writerow(row)
        Toast.show_toast(self, f"Exported: {path}", "success")




# ===========================================================================
# Panel — Tree  (hierarchical co-occurrence tree, horizontal layout)
# ===========================================================================
class TreePanel(QWidget):
    """
    Builds a hierarchical tree where:
      - Each LEVEL corresponds to one Analysis (user-ordered)
      - Node content = Objects | Category | Subcategory  (per-level choice)
      - Edges connect nodes across adjacent levels when they co-occur
        in at least one article in the pool
      - Layout: horizontal, root on the left (cladogram / decision-tree style)
      - Each node shows: label + article count
    """

    def __init__(self):
        super().__init__()
        self._pool = {}
        self._exclude_refs: bool = True
        self._excluded_sections: set = set()
        self._level_widgets = []   # list of (ana_combo, group_combo, filter_combo)
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Top controls ──────────────────────────────────────────────────
        top = QWidget(); top.setStyleSheet("background:transparent;border:none;")
        tl = QHBoxLayout(top); tl.setContentsMargins(0, 0, 0, 0); tl.setSpacing(10)

        tl.addWidget(_sec("MIN CO-OCC:"))
        self._min_cooc_cb = QComboBox(); self._min_cooc_cb.setStyleSheet(_cb_style())
        self._min_cooc_cb.addItems(["1", "2", "3", "5", "10"])
        self._min_cooc_cb.setToolTip("Minimum number of shared articles to draw an edge")
        tl.addWidget(self._min_cooc_cb)

        tl.addWidget(_sec("TOP N / LEVEL:"))
        self._topn_cb = QComboBox(); self._topn_cb.setStyleSheet(_cb_style())
        self._topn_cb.addItems(["5", "10", "15", "20", "All"])
        self._topn_cb.setCurrentText("10")
        tl.addWidget(self._topn_cb)

        tl.addWidget(_sec("CELL SIZE:"))
        self._cell_cb = QComboBox(); self._cell_cb.setStyleSheet(_cb_style())
        self._cell_cb.addItems(["Small", "Medium", "Large"])
        self._cell_cb.setCurrentText("Medium")
        tl.addWidget(self._cell_cb)

        tl.addStretch()
        btn_draw = make_btn("🌿  Draw Tree"); btn_draw.clicked.connect(self._draw)
        tl.addWidget(btn_draw)
        btn_exp = make_btn("Export PNG"); btn_exp.clicked.connect(self._export)
        tl.addWidget(btn_exp)
        root.addWidget(top)

        # ── Level configurator ────────────────────────────────────────────
        self._level_area = QWidget()
        self._level_area.setStyleSheet(
            f"background:{COLORS['bg_secondary']};border:1px solid {COLORS['border']};"
            "border-radius:4px;")
        self._level_layout = QHBoxLayout(self._level_area)
        self._level_layout.setContentsMargins(8, 6, 8, 6)
        self._level_layout.setSpacing(4)
        self._level_layout.addStretch()
        root.addWidget(self._level_area)

        # ── Canvas in scroll area ─────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea{{border:none;background:{COLORS['bg_primary']};}}")
        self._canvas = TreeCanvas()
        self._canvas.node_delete_requested.connect(self._delete_node)
        self._scroll.setWidget(self._canvas)
        root.addWidget(self._scroll, 1)

    # ── Pool ──────────────────────────────────────────────────────────────
    def set_pool(self, pool: dict, exclude_refs: bool = True, excluded_sections: set = None):
        self._pool = pool
        self._exclude_refs = exclude_refs
        self._excluded_sections = excluded_sections or set()
        self._rebuild_level_ui()

    def _rebuild_level_ui(self):
        """Rebuild level row from pool analyses (one level per analysis by default)."""
        from PyQt5.QtCore import QTimer
        # Safely remove all widgets from layout
        while self._level_layout.count():
            item = self._level_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.hide()
                    w.setParent(None)
                    QTimer.singleShot(0, w.deleteLater)
        self._level_widgets = []

        anas = list(self._pool.get("lists", {}).keys())
        if not anas:
            self._level_layout.addWidget(_lbl("No analyses in pool", muted=True))
            self._level_layout.addStretch()
            return

        self._level_layout.addWidget(_lbl("ROOT →", bold=True))

        # ── "+ Add Level" button and stretch must exist BEFORE _add_level_card
        # because _add_level_card uses count()-2 to insert before them
        add_btn = QPushButton("+ Level")
        add_btn.setToolTip("Add another level to the tree")
        add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['accent_teal']};"
            f"border:1px dashed {COLORS['border']};border-radius:4px;"
            f"padding:4px 8px;font-size:8pt;}}"
            f"QPushButton:hover{{background:{COLORS['bg_hover']};}}"
        )
        add_btn.clicked.connect(lambda: self._add_level_card(anas[0]))
        self._level_layout.addWidget(add_btn)
        self._level_layout.addStretch()

        for ana in anas:
            self._add_level_card(ana)

    def _add_level_card(self, default_ana: str):
        """Insert one level card before the '+ Level' button and stretch."""
        anas = list(self._pool.get("lists", {}).keys())
        idx = len(self._level_widgets)
        color = ANALYSIS_COLORS[idx % len(ANALYSIS_COLORS)]

        card = QWidget()
        card.setStyleSheet(
            f"background:{COLORS['bg_primary']};border:1px solid {color}55;"
            "border-radius:4px;")
        cl = QVBoxLayout(card); cl.setContentsMargins(6, 4, 6, 4); cl.setSpacing(3)

        # Header row: "Level N" + × remove button
        hdr_row = QWidget(); hdr_row.setStyleSheet("background:transparent;border:none;")
        hrl = QHBoxLayout(hdr_row); hrl.setContentsMargins(0,0,0,0); hrl.setSpacing(2)
        hdr = QLabel(f"Level {idx+1}")
        hdr.setStyleSheet(
            f"font-size:7.5pt;font-weight:700;color:{color};"
            "background:transparent;border:none;")
        hrl.addWidget(hdr, 1)
        rem_btn = QPushButton("×")
        rem_btn.setFixedSize(16, 16)
        rem_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_muted']};"
            "border:none;font-size:10pt;padding:0;}}"
            f"QPushButton:hover{{color:#f43f5e;}}"
        )
        rem_btn.clicked.connect(lambda checked=False, c=card: self._remove_level_card(c))
        hrl.addWidget(rem_btn)
        cl.addWidget(hdr_row)

        # Analysis selector
        ana_cb = QComboBox(); ana_cb.setStyleSheet(_cb_style()); ana_cb.setMinimumWidth(110)
        ana_cb.addItems(anas)
        if default_ana in anas: ana_cb.setCurrentText(default_ana)
        cl.addWidget(ana_cb)

        # Group-by selector — populated with actual N category levels
        grp_cb = QComboBox(); grp_cb.setStyleSheet(_cb_style())
        n_cats = max(
            (len(o.get("categories") or [])
             for o in self._pool.get("lists", {}).get(default_ana, [])),
            default=1
        )
        grp_items = ["Objects"] + [f"Category {i+1}" for i in range(n_cats)]
        grp_cb.addItems(grp_items)
        cl.addWidget(grp_cb)

        # Filter selector — multi-checkbox
        filt_w = MultiFilterWidget(); filt_w.setMinimumWidth(110)
        cl.addWidget(filt_w)

        # Wire up signals
        ana_cb.currentTextChanged.connect(
            lambda _, a=ana_cb, g=grp_cb, f=filt_w: self._refresh_level_filter(a, g, f))
        grp_cb.currentTextChanged.connect(
            lambda _, a=ana_cb, g=grp_cb, f=filt_w: self._refresh_level_filter(a, g, f))
        self._refresh_level_filter(ana_cb, grp_cb, filt_w)

        # Insert before the "+" button — which is at count()-2 (before stretch)
        # structure: ROOT → [cards...] [+btn] [stretch]
        # insert at position: count() - 2 means before +btn
        insert_pos = self._level_layout.count() - 2
        # Add arrow before this card (except for the very first card)
        if self._level_widgets:
            arr = QLabel("→")
            arr.setStyleSheet(
                f"font-size:14pt;color:{COLORS['text_muted']};"
                "background:transparent;border:none;padding:0 2px;")
            arr.setObjectName("tree_arrow")
            self._level_layout.insertWidget(insert_pos, arr)
            insert_pos += 1

        self._level_layout.insertWidget(insert_pos, card)
        self._level_widgets.append((ana_cb, grp_cb, filt_w, card))

    def _remove_level_card(self, card):
        """Safely remove a level card and its preceding arrow from the layout."""
        from PyQt5.QtCore import QTimer

        if len(self._level_widgets) <= 1:
            return  # always keep at least one level

        # Remove from our tracking list first
        self._level_widgets = [t for t in self._level_widgets if t[3] is not card]

        # Find and remove the preceding arrow (if any) from the layout
        idx = self._level_layout.indexOf(card)
        if idx > 0:
            prev_item = self._level_layout.itemAt(idx - 1)
            if prev_item is not None:
                prev_w = prev_item.widget()
                if prev_w is not None and prev_w.objectName() == "tree_arrow":
                    self._level_layout.removeWidget(prev_w)
                    prev_w.hide()
                    prev_w.setParent(None)
                    QTimer.singleShot(0, prev_w.deleteLater)

        # Remove card from layout, then schedule deletion after event loop tick
        # (so the click event that triggered this has fully returned first)
        self._level_layout.removeWidget(card)
        card.hide()
        card.setParent(None)
        QTimer.singleShot(0, card.deleteLater)

        # Renumber remaining level headers safely
        for i, (a, g, f, c) in enumerate(self._level_widgets):
            try:
                lay = c.layout()
                if lay is None: continue
                hdr_item = lay.itemAt(0)
                if hdr_item is None: continue
                hdr_row = hdr_item.widget()
                if hdr_row is None: continue
                hrl = hdr_row.layout()
                if hrl is None: continue
                lbl_item = hrl.itemAt(0)
                if lbl_item is None: continue
                lbl_w = lbl_item.widget()
                if lbl_w is None: continue
                color = ANALYSIS_COLORS[i % len(ANALYSIS_COLORS)]
                lbl_w.setText(f"Level {i+1}")
                lbl_w.setStyleSheet(
                    f"font-size:7.5pt;font-weight:700;color:{color};"
                    "background:transparent;border:none;")
            except RuntimeError:
                pass  # widget already deleted — skip

    def _refresh_level_filter(self, ana_cb, grp_cb, filt_w):
        try:
            ana   = ana_cb.currentText()
            group = grp_cb.currentText()
        except RuntimeError:
            return  # widget already deleted
        objs  = self._pool.get("lists", {}).get(ana, [])
        values = set()
        for o in objs:
            v = ConnectionMapPanel._cat_val(o, group)
            if v: values.add(v)
        try:
            filt_w.set_options(sorted(values))
        except RuntimeError:
            pass  # widget already deleted

    # ── Build labels for one level ────────────────────────────────────────
    def _level_labels(self, ana: str, group: str, filt_w):
        """Returns {label: {"terms": [...], "art_keys": set_or_None}} for a level."""
        objs = self._pool.get("lists", {}).get(ana, [])
        selected = filt_w.selected_values()   # empty set = All
        label_terms    = defaultdict(list)
        label_art_keys = defaultdict(set)
        label_has_none = set()

        for o in objs:
            lbl = ConnectionMapPanel._cat_val(o, group) or o["name"]
            if selected:
                check = ConnectionMapPanel._cat_val(o, group)
                if check not in selected:
                    continue
            label_terms[lbl].extend(o.get("terms", []))
            ak = o.get("article_keys")
            if ak is None:
                label_has_none.add(lbl)
            else:
                label_art_keys[lbl].update(ak)

        result = {}
        for lbl in label_terms:
            result[lbl] = {
                "terms":    label_terms[lbl],
                "art_keys": None if lbl in label_has_none else label_art_keys[lbl],
            }
        return result

    # ── Draw ──────────────────────────────────────────────────────────────
    def _draw(self):
        try:
            self._draw_internal()
        except Exception as exc:
            from PyQt5.QtWidgets import QMessageBox
            self._canvas.set_tree([], [])
            QMessageBox.warning(self, "Draw Tree", f"Could not draw tree:\n{exc}")

    def _draw_internal(self):
        if not self._level_widgets:
            self._canvas.set_tree([], []); return

        pool = self._pool
        articles = pool.get("articles", {})
        if not articles:
            self._canvas.set_tree([], []); return
        min_cooc = int(self._min_cooc_cb.currentText())
        topn_txt = self._topn_cb.currentText()
        topn = None if topn_txt == "All" else int(topn_txt)
        cell_size = {"Small": 22, "Medium": 30, "Large": 40}[self._cell_cb.currentText()]

        # Build levels: [{label: terms_list}]
        levels = []
        level_colors = []
        for idx, level_tup in enumerate(self._level_widgets):
            ana_cb, grp_cb, filt_w = level_tup[0], level_tup[1], level_tup[2]
            ana   = ana_cb.currentText()
            group = grp_cb.currentText()
            lbl_map = self._level_labels(ana, group, filt_w)
            levels.append(lbl_map)
            color = ANALYSIS_COLORS[idx % len(ANALYSIS_COLORS)]
            level_colors.append((color, ana))

        if not levels:
            self._canvas.set_tree([], []); return

        # ── Pre-scan: for each article, which labels from each level does it hit?
        # art_hits[article_idx] = [frozenset_lv0, frozenset_lv1, ...]
        art_hits = []
        art_keys_list = list(articles.keys())
        for art_key in art_keys_list:
            art = articles[art_key]
            row = []
            for lv in levels:
                hit_lbls = set()
                for lbl, lv_info in lv.items():
                    ak = lv_info["art_keys"]
                    if ak is not None:
                        if art_key in ak:
                            hit_lbls.add(lbl)
                    else:
                        text = _apply_text_filters(
                            art.get("text", "") or art.get("title", ""),
                            self._exclude_refs, self._excluded_sections)
                        if any(_term_matches(t, text) for t in lv_info["terms"]):
                            hit_lbls.add(lbl)
                row.append(frozenset(hit_lbls))
            # Only include articles that hit at least one label in the first level
            if row[0]:
                art_hits.append(row)

        # ── Chain-aware article sets ──────────────────────────────────────────
        # art_ids_for_path[path_tuple] = set of article indices matching that full path
        # A path is a tuple of labels (one per level), e.g. ("Organic", "Drug", "Analgesic")
        # We build this incrementally level by level.
        #
        # For each node at each level we track:
        #   node_art_sets[(level_idx, label, parent_path)] = set of article indices
        # where parent_path is a tuple of ancestor labels (empty for root).
        #
        # An article qualifies for a path if it matches ALL labels in that path.

        # Build tree nodes and edges via DFS, tracking article sets at each path
        nodes = []
        edges = []
        nid = 0

        def build_subtree(parent_id, level_idx, label, ancestor_path, ancestor_art_set):
            """
            ancestor_path  : tuple of labels at levels 0..level_idx-1
            ancestor_art_set : set of article indices that matched the full ancestor path
            """
            nonlocal nid

            # Articles matching this node = ancestor_art_set ∩ articles_hitting_this_label
            my_art_set = frozenset(
                i for i in ancestor_art_set
                if label in art_hits[i][level_idx]
            ) if level_idx > 0 else frozenset(
                i for i, row in enumerate(art_hits)
                if label in row[level_idx]
            )

            if len(my_art_set) < min_cooc:
                return None

            color, ana_name = level_colors[level_idx]
            node = {
                "id": nid, "label": label, "level": level_idx,
                "color": color, "ana": ana_name, "parent_id": parent_id,
                "count": len(my_art_set),
            }
            nodes.append(node)
            my_id = nid; nid += 1

            if parent_id is not None:
                edges.append({"src": parent_id, "dst": my_id, "weight": len(my_art_set)})

            # Recurse into next level
            if level_idx < len(levels) - 1:
                # Candidate children = all labels in next level that appear
                # in at least one article already in my_art_set
                candidate_children = {}
                for i in my_art_set:
                    for child_lbl in art_hits[i][level_idx + 1]:
                        candidate_children[child_lbl] = candidate_children.get(child_lbl, 0) + 1

                # Sort by count descending, apply topn
                children_sorted = sorted(candidate_children.items(), key=lambda x: -x[1])
                if topn:
                    children_sorted = children_sorted[:topn]

                my_path = ancestor_path + (label,)
                for child_lbl, _ in children_sorted:
                    build_subtree(my_id, level_idx + 1, child_lbl, my_path, my_art_set)

            return my_id

        # ── Root nodes (level 0) ─────────────────────────────────────────────
        all_art_indices = set(range(len(art_hits)))

        # Count article hits per root label
        root_totals = defaultdict(int)
        for row in art_hits:
            for lbl in row[0]:
                root_totals[lbl] += 1

        if topn:
            root_labels = sorted(root_totals, key=lambda l: -root_totals[l])[:topn]
        else:
            root_labels = sorted(root_totals)

        for lbl in root_labels:
            build_subtree(None, 0, lbl, (), all_art_indices)

        self._last_nodes = nodes
        self._last_edges = edges
        self._canvas.set_tree(nodes, edges,
                               level_colors=level_colors,
                               cell_size=cell_size)

    def _delete_node(self, nid: int):
        """Remove node nid and all its descendants from the live tree, then redraw."""
        nodes = getattr(self, '_last_nodes', [])
        edges = getattr(self, '_last_edges', [])
        if not nodes:
            return

        # Collect all descendant ids (BFS)
        to_remove = set()
        queue = [nid]
        while queue:
            cur = queue.pop()
            to_remove.add(cur)
            for e in edges:
                if e["src"] == cur and e["dst"] not in to_remove:
                    queue.append(e["dst"])

        # Filter nodes and edges
        new_nodes = [n for n in nodes if n["id"] not in to_remove]
        new_edges = [e for e in edges
                     if e["src"] not in to_remove and e["dst"] not in to_remove]

        self._last_nodes = new_nodes
        self._last_edges = new_edges

        # Recover level_colors from current level widgets
        level_colors = []
        for idx, level_tup in enumerate(self._level_widgets):
            ana = level_tup[0].currentText()
            color = ANALYSIS_COLORS[idx % len(ANALYSIS_COLORS)]
            level_colors.append((color, ana))

        cell_size = {"Small": 22, "Medium": 30, "Large": 40}[self._cell_cb.currentText()]
        self._canvas.set_tree(new_nodes, new_edges,
                              level_colors=level_colors, cell_size=cell_size)

    def _export(self):
        path, filt = QFileDialog.getSaveFileName(
            self, "Export Tree", "tree",
            "PNG (*.png);;CSV (*.csv)")
        if not path: return
        if filt.startswith("CSV") or path.endswith(".csv"):
            self._export_csv(path)
        else:
            pixmap = self._canvas.grab()
            pixmap.save(path, "PNG")
            Toast.show_toast(self, f"Exported: {path}", "success")

    def _export_csv(self, path=None):
        import csv as _csv
        nodes = getattr(self, '_last_nodes', [])
        edges = getattr(self, '_last_edges', [])
        if not nodes:
            Toast.show_toast(self, "Draw the tree first", "warning"); return
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "tree.csv", "CSV (*.csv)")
            if not path: return
        node_map = {n["id"]: n for n in nodes}
        edge_map = {e["dst"]: e for e in edges}
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(["level", "analysis", "label", "parent_label", "co_occurrence"])
            for n in nodes:
                e    = edge_map.get(n["id"])
                par  = node_map[e["src"]]["label"] if e else ""
                cooc = e["weight"] if e else ""
                w.writerow([n["level"] + 1, n.get("ana",""), n["label"], par, cooc])
        Toast.show_toast(self, f"Exported: {path}", "success")


# ---------------------------------------------------------------------------
# TreeCanvas — Qt native painter  (true tree, no crossing edges)
# ---------------------------------------------------------------------------
class TreeCanvas(QWidget):
    """
    Horizontal cladogram-style tree.

    Layout rules (no crossing edges):
      - Leaf nodes are stacked top-to-bottom with uniform spacing.
      - Each internal node is vertically centred over its subtree span.
      - Edges drawn as right-angle connectors:
          parent-right → vertical bar at mid-X → child-left
        (like figure A/C in the reference image).
      - Nodes with the same label can appear multiple times (one per parent).
    """

    node_delete_requested = pyqtSignal(int)   # emits node id to delete

    NODE_W   = 150   # fixed node box width
    NODE_H   = 28    # fixed node box height
    PAD_Y    = 6     # vertical gap between sibling boxes
    COL_GAP  = 70    # horizontal gap between levels (connector space)
    MARGIN_X = 20
    MARGIN_Y = 40    # top margin (space for column headers)

    def __init__(self):
        super().__init__()
        self._nodes      = []
        self._edges      = []
        self._level_colors = []
        self._positions  = {}   # node_id → QRectF(x, y, w, h)
        self._hovered_id = -1
        self._selected_id = -1
        self._cell_size  = 30
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ── Public API ────────────────────────────────────────────────────────
    def set_tree(self, nodes, edges, level_colors=None, cell_size=30, **_):
        self._nodes        = nodes
        self._edges        = edges
        self._level_colors = level_colors or []
        self._cell_size    = cell_size
        self._hovered_id   = -1
        self._selected_id  = -1
        # Scale node size with cell_size
        self.NODE_H = max(24, cell_size)
        self.NODE_W = max(120, cell_size * 5)
        self._compute_layout()
        self.update()

    # ── Layout ────────────────────────────────────────────────────────────
    def _compute_layout(self):
        from PyQt5.QtCore import QRectF
        self._positions = {}
        if not self._nodes:
            return

        # Build children map
        children = defaultdict(list)   # parent_id → [child_id, ...]
        roots = []
        node_map = {n["id"]: n for n in self._nodes}
        for n in self._nodes:
            pid = n.get("parent_id")
            if pid is None:
                roots.append(n["id"])
            else:
                children[pid].append(n["id"])

        # Assign Y positions bottom-up:
        # 1. Assign sequential Y slots to leaves
        # 2. Each internal node = midpoint of first and last child Y

        slot = [0]   # mutable counter

        def assign_y(nid):
            kids = children[nid]
            if not kids:
                # Leaf: assign next slot
                y = slot[0]
                slot[0] += 1
                return y, y          # (first_leaf, last_leaf)
            else:
                first = None
                last  = None
                for kid in kids:
                    f, l = assign_y(kid)
                    if first is None: first = f
                    last = l
                return first, last

        node_y_slots = {}   # nid → float y-slot centre

        def collect_y(nid):
            kids = children[nid]
            if not kids:
                # already assigned by assign_y pass
                pass
            f, l = assign_y_result[nid]
            node_y_slots[nid] = (f + l) / 2.0
            for kid in kids:
                collect_y(kid)

        # Two-pass: first compute spans, then centre
        assign_y_result = {}

        def compute_spans(nid):
            kids = children[nid]
            if not kids:
                y = slot[0]; slot[0] += 1
                assign_y_result[nid] = (y, y)
            else:
                for kid in kids:
                    compute_spans(kid)
                first = assign_y_result[children[nid][0]][0]
                last  = assign_y_result[children[nid][-1]][1]
                assign_y_result[nid] = (first, last)

        slot[0] = 0
        for r in roots:
            compute_spans(r)

        # Centre each node
        for nid in assign_y_result:
            f, l = assign_y_result[nid]
            node_y_slots[nid] = (f + l) / 2.0

        # Convert slots → pixel Y
        row_h   = self.NODE_H + self.PAD_Y
        col_w   = self.NODE_W + self.COL_GAP

        # X position from level index
        n_levels = max(n["level"] for n in self._nodes) + 1 if self._nodes else 1

        total_slots = slot[0]
        total_h = self.MARGIN_Y + total_slots * row_h + self.PAD_Y
        total_w = self.MARGIN_X + n_levels * col_w + 20
        self.setMinimumSize(max(total_w, 400), max(total_h, 300))

        from PyQt5.QtCore import QRectF
        for n in self._nodes:
            nid = n["id"]
            li  = n["level"]
            x   = self.MARGIN_X + li * col_w
            y_slot = node_y_slots.get(nid, 0)
            y   = self.MARGIN_Y + y_slot * row_h
            self._positions[nid] = QRectF(x, y, self.NODE_W, self.NODE_H)

    # ── Interaction ───────────────────────────────────────────────────────
    def _node_at(self, x, y):
        for nid, r in self._positions.items():
            if r.contains(x, y):
                return nid
        return -1

    def _connected_ids(self, nid):
        s = set()
        for e in self._edges:
            if e["src"] == nid: s.add(e["dst"])
            if e["dst"] == nid: s.add(e["src"])
        return s

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            nid = self._node_at(event.x(), event.y())
            self._selected_id = nid
            self.setFocus()
            self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self._selected_id >= 0:
                self.node_delete_requested.emit(self._selected_id)
        else:
            super().keyPressEvent(event)

    def _show_context_menu(self, pos):
        nid = self._node_at(pos.x(), pos.y())
        if nid < 0:
            return
        self._selected_id = nid
        self.update()
        node = next((n for n in self._nodes if n["id"] == nid), None)
        if not node:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{COLORS['bg_secondary']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:4px 0;}}"
            f"QMenu::item{{padding:6px 20px 6px 12px;color:{COLORS['text_primary']};font-size:9pt;}}"
            f"QMenu::item:selected{{background:{COLORS['bg_hover']};color:#cf222e;}}"
        )
        lbl = node['label']
        title = menu.addAction(f"🔵  {lbl}")
        title.setEnabled(False)
        menu.addSeparator()
        del_action = menu.addAction("🗑  Delete node and its branches")
        action = menu.exec_(self.mapToGlobal(pos))
        if action == del_action:
            self.node_delete_requested.emit(nid)

    def mouseMoveEvent(self, event):
        px, py = event.x(), event.y()
        found = -1
        for nid, r in self._positions.items():
            if r.contains(px, py):
                found = nid; break
        if found != self._hovered_id:
            self._hovered_id = found
            self.update()
            if found >= 0:
                node = next(n for n in self._nodes if n["id"] == found)
                from PyQt5.QtWidgets import QToolTip
                # Count children
                n_ch = sum(1 for e in self._edges if e["src"] == found)
                tip = f"<b>{node['label']}</b><br>Analysis: {node.get('ana','')}"
                if n_ch: tip += f"<br>Children: {n_ch}"
                QToolTip.showText(event.globalPos(), tip, self)

    def leaveEvent(self, event):
        self._hovered_id = -1; self.update()

    # ── Paint ─────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        from PyQt5.QtGui import QPainterPath
        from PyQt5.QtCore import QRectF, QPointF

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#f8f9fb"))   # off-white canvas

        if not self._nodes or not self._positions:
            p.setPen(QColor("#555e6b"))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Configure levels and press  Draw Tree")
            p.end(); return

        connected = self._connected_ids(self._hovered_id) if self._hovered_id >= 0 else set()
        node_map  = {n["id"]: n for n in self._nodes}        # ── Column headers ────────────────────────────────────────────────
        font_hdr = QFont(); font_hdr.setPointSize(8); font_hdr.setBold(True)
        p.setFont(font_hdr)
        col_w = self.NODE_W + self.COL_GAP
        for li, (color, ana_name) in enumerate(self._level_colors):
            x = self.MARGIN_X + li * col_w
            # Darken the level colour for the header text
            hdr_color = QColor(color).darker(140)
            p.setPen(hdr_color)
            p.drawText(int(x), 4, self.NODE_W, 22, Qt.AlignCenter,
                       f"L{li+1}  ·  {ana_name[:20]}")
            if li > 0:
                # Soft vertical separator
                p.setPen(QPen(QColor("#c0c8d4"), 1, Qt.DashLine))
                p.drawLine(int(x) - self.COL_GAP // 2, 0,
                           int(x) - self.COL_GAP // 2, self.height())

        # ── Edges: right-angle connectors (cladogram style) ───────────────
        for e in self._edges:
            sr = self._positions.get(e["src"])
            dr = self._positions.get(e["dst"])
            if sr is None or dr is None: continue

            is_hov = (self._hovered_id in (e["src"], e["dst"]))
            is_dim = (self._hovered_id >= 0 and not is_hov)

            # Use a darkened version of the source node colour for edges
            base = QColor(node_map[e["src"]]["color"]).darker(130)
            edge_color = QColor(base)
            if is_dim:
                edge_color.setAlpha(30)
            elif is_hov:
                edge_color.setAlpha(255)
            else:
                edge_color.setAlpha(160)

            p.setPen(QPen(edge_color, 2.0 if is_hov else 1.4))
            p.setBrush(Qt.NoBrush)

            x1 = sr.right()
            y1 = sr.center().y()
            x2 = dr.left()
            y2 = dr.center().y()
            mid_x = (x1 + x2) / 2.0

            path = QPainterPath()
            path.moveTo(x1, y1)
            path.lineTo(mid_x, y1)
            path.lineTo(mid_x, y2)
            path.lineTo(x2, y2)
            p.drawPath(path)

        # ── Nodes ─────────────────────────────────────────────────────────
        font_lbl  = QFont(); font_lbl.setPointSize(8)
        font_bold = QFont(); font_bold.setPointSize(8); font_bold.setBold(True)

        for node in self._nodes:
            nid = node["id"]
            r   = self._positions.get(nid)
            if r is None: continue

            base_color = QColor(node["color"])
            # Derive a darker border from the accent colour
            border_dark = base_color.darker(170)
            is_hov  = (nid == self._hovered_id)
            is_conn = (nid in connected)
            is_dim  = (self._hovered_id >= 0 and not is_hov and not is_conn)

            # ── Background fill ───────────────────────────────────────────
            is_sel  = (nid == self._selected_id)
            if is_sel:
                # Selected: red-tinted border to signal "ready to delete"
                bg = QColor(base_color.red(), base_color.green(),
                            base_color.blue(), 45)
                border_color = QColor("#cf222e")
                border_width = 2.2
            elif is_hov:
                # Solid accent fill on hover
                bg = base_color.lighter(130)
                border_color = border_dark
                border_width = 2.0
            elif is_conn:
                # Light tint for connected nodes
                bg = QColor(base_color.red(), base_color.green(),
                            base_color.blue(), 55)
                border_color = base_color.darker(150)
                border_width = 1.8
            elif is_dim:
                bg = QColor("#eaecf0")
                border_color = QColor("#b0b8c4")
                border_width = 0.8
            else:
                # Normal: very light tint + dark border
                bg = QColor(base_color.red(), base_color.green(),
                            base_color.blue(), 28)
                border_color = border_dark
                border_width = 1.4

            p.setBrush(QBrush(bg))
            p.setPen(QPen(border_color, border_width))
            p.drawRoundedRect(r, 5, 5)

            # ── Label text (always dark / readable) ───────────────────────
            font = font_bold if is_hov else font_lbl
            p.setFont(font)

            if is_hov:
                text_c = QColor("#1a1f27")        # near-black on hover
            elif is_dim:
                text_c = QColor("#9aa3ae")        # muted grey when dimmed
            else:
                text_c = QColor("#23282f")        # dark charcoal by default

            p.setPen(text_c)

            lbl = node["label"]
            fm  = QFontMetrics(font)
            avail = int(r.width()) - 12
            while fm.horizontalAdvance(lbl) > avail and len(lbl) > 4:
                lbl = lbl[:-2] + "…"
            p.drawText(r.adjusted(6, 0, -6, 0).toRect(),
                       Qt.AlignVCenter | Qt.AlignLeft, lbl)

        p.end()