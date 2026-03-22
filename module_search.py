"""
SLDM — Reference Search Module

Simple cross-analysis article search:
  - Type any word/phrase (or object name/synonym).  AND/OR between rows.
  - Optional: case-sensitive toggle (exact capitalisation required).
  - Results: list of matching articles across ALL analyses.
  - Click an article → PDF viewer with every matched term highlighted,
    each in its own colour.  No PDF?  Shows highlighted abstract/text.
"""

import re, json, os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QScrollArea, QFrame, QDialog,
    QApplication, QMessageBox, QTextEdit, QCheckBox, QSizePolicy,
    QProgressBar,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap, QImage

from core.theme import COLORS
from core.widgets import make_btn, Toast
from modules.module_mining import (
    _strip_references, _strip_sections, SectionFilterDialog,
)

# ── Highlight colour palette (hex + fitz RGB tuple 0-1) ───────────────────────
_PAL_HEX = [
    "#f0d000", "#3db271", "#3d8bfa", "#f2661f",
    "#bf59f2", "#f2374d", "#20d1be", "#fab302",
    "#66cc40", "#8c40cc",
]
_PAL_RGB = [
    (0.94, 0.82, 0.00), (0.24, 0.70, 0.44), (0.24, 0.55, 0.98), (0.95, 0.40, 0.13),
    (0.75, 0.35, 0.95), (0.95, 0.22, 0.37), (0.13, 0.82, 0.75), (0.98, 0.72, 0.01),
    (0.40, 0.80, 0.25), (0.55, 0.25, 0.80),
]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse_syns(raw) -> list:
    if isinstance(raw, str):
        try:    items = json.loads(raw)
        except: items = [raw]
    else:
        items = list(raw or [])
    out = []
    for item in items:
        for part in str(item).split(';'):
            p = part.strip()
            if p:
                out.append(p)
    return out


def _article_text(art: dict) -> str:
    parts = []
    if art.get("abstract"): parts.append(art["abstract"])
    if art.get("raw_text"):  parts.append(art["raw_text"])
    return " ".join(parts) or art.get("title", "")


def _term_in_text(term: str, text: str, case_sensitive: bool) -> bool:
    """Plain substring search. case_sensitive flag respected."""
    if not term or not text:
        return False
    if case_sensitive:
        return term in text
    return term.lower() in text.lower()


# ── Styles (functions → always read current COLORS) ───────────────────────────
def _cb_s():
    return (
        f"QComboBox{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
        f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 7px;font-size:9pt;}}"
        "QComboBox::drop-down{border:none;}"
        f"QComboBox QAbstractItemView{{background:{COLORS['bg_secondary']};"
        f"color:{COLORS['text_primary']};border:1px solid {COLORS['border']};}}"
    )

def _le_s():
    return (
        f"QLineEdit{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
        f"border-radius:4px;color:{COLORS['text_primary']};padding:4px 9px;font-size:9pt;}}"
        f"QLineEdit:focus{{border-color:{COLORS['accent_blue']};}}"
    )


# ===========================================================================
# Multi-colour PDF viewer  (rewrite of PdfViewerWindow for N terms/colours)
# ===========================================================================
class MultiColorPdfViewer(QDialog):
    """
    pdf_path     : str
    term_colors  : list of (display_label, [search_terms], hex_color)
    """
    def __init__(self, parent, pdf_path: str,
                 term_colors: list, title: str = "",
                 case_sensitive: bool = False):
        super().__init__(parent)
        self.pdf_path       = pdf_path
        self.term_colors    = term_colors
        self.article_title  = title
        self.case_sensitive = case_sensitive
        self._zoom = 1.5
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(f"PDF — {title[:70]}")
        self.setMinimumSize(920, 760)
        self.resize(1060, 840)
        self._build_ui()
        self._render()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # toolbar
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 0, 12, 0)
        bl.setSpacing(6)

        self._hits_lbl = QLabel("")
        self._hits_lbl.setStyleSheet(
            f"color:{COLORS['accent_amber']};font-size:9pt;"
            "font-weight:600;background:transparent;border:none;"
        )
        bl.addWidget(self._hits_lbl)
        bl.addStretch()

        # colour legend
        for label, _terms, hex_c in self.term_colors:
            b = QLabel(f"  {label}  ")
            b.setStyleSheet(
                f"background:{hex_c}44;color:{hex_c};"
                f"border:1px solid {hex_c}88;border-radius:8px;"
                "padding:2px 8px;font-size:8pt;font-weight:600;"
            )
            bl.addWidget(b)

        bl.addSpacing(12)
        btn_out = make_btn("－"); btn_in = make_btn("＋")
        btn_out.setFixedWidth(34); btn_in.setFixedWidth(34)
        btn_out.clicked.connect(lambda: self._set_zoom(max(0.5, self._zoom - 0.25)))
        btn_in.clicked.connect(lambda: self._set_zoom(self._zoom + 0.25))
        bl.addWidget(btn_out); bl.addWidget(btn_in)
        lay.addWidget(bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea{{background:{COLORS['bg_primary']};border:none;}}"
        )
        self._container = QWidget()
        self._container.setStyleSheet(f"background:{COLORS['bg_primary']};")
        self._pages_lay = QVBoxLayout(self._container)
        self._pages_lay.setContentsMargins(24, 16, 24, 16)
        self._pages_lay.setSpacing(12)
        self._pages_lay.setAlignment(Qt.AlignHCenter)
        self._scroll.setWidget(self._container)
        lay.addWidget(self._scroll, 1)

    def _render(self):
        try:
            import fitz
        except ImportError:
            QMessageBox.warning(self, "PyMuPDF missing",
                "Install with:  pip install pymupdf")
            self.close(); return
        try:
            doc = fitz.open(self.pdf_path)
        except Exception as e:
            QMessageBox.critical(self, "Cannot open PDF", str(e))
            self.close(); return

        total = 0
        mat = fitz.Matrix(self._zoom, self._zoom)
        flags = 0 if self.case_sensitive else fitz.TEXT_DEHYPHENATE

        for page in doc:
            for _label, terms, hex_c in self.term_colors:
                h = hex_c.lstrip('#')
                r, g, b = (int(h[i:i+2], 16) / 255 for i in (0, 2, 4))
                for term in terms:
                    if not term.strip():
                        continue
                    try:
                        rects = page.search_for(
                            term,
                            quads=False,
                            flags=0 if self.case_sensitive else fitz.TEXT_DEHYPHENATE
                        )
                    except Exception:
                        rects = []
                    for rect in rects:
                        total += 1
                        try:
                            hl = page.add_highlight_annot(rect)
                            hl.set_colors(stroke=(r, g, b))
                            hl.update()
                        except Exception:
                            pass

            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format_RGB888)
            lbl = QLabel()
            lbl.setPixmap(QPixmap.fromImage(img))
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("background:transparent;border:none;")
            self._pages_lay.addWidget(lbl)

        doc.close()
        self._hits_lbl.setText(f"{total} highlight(s) found")

    def _set_zoom(self, z):
        self._zoom = z
        while self._pages_lay.count():
            item = self._pages_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._render()


# ===========================================================================
# Article result row
# ===========================================================================
class ArticleRow(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, article: dict, term_colors: list, parent=None):
        super().__init__(parent)
        self._article    = article
        self._term_colors = term_colors   # [(label, [terms], hex)]
        self.setFrameShape(QFrame.NoFrame)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame{{background:{COLORS['bg_card']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;}}"
            f"QFrame:hover{{background:{COLORS['bg_hover']};"
            f"border-color:{COLORS['accent_blue']}55;}}"
        )
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        info = QVBoxLayout(); info.setSpacing(2)
        title_lbl = QLabel(self._article.get("title", "Untitled"))
        title_lbl.setStyleSheet(
            f"font-weight:600;font-size:9pt;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        title_lbl.setWordWrap(True)
        info.addWidget(title_lbl)

        year    = str(self._article.get("year") or "")
        journal = self._article.get("journal") or ""
        meta    = " · ".join(p for p in [year, journal] if p)
        if meta:
            m = QLabel(meta)
            m.setStyleSheet(
                f"font-size:8pt;color:{COLORS['text_secondary']};"
                "background:transparent;border:none;"
            )
            info.addWidget(m)
        lay.addLayout(info, 1)

        right = QHBoxLayout()
        right.setSpacing(4)
        right.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for label, _terms, hex_c in self._term_colors[:6]:
            b = QLabel(f" {label} ")
            b.setStyleSheet(
                f"background:{hex_c}33;color:{hex_c};"
                f"border:1px solid {hex_c}66;border-radius:8px;"
                "padding:1px 6px;font-size:7.5pt;font-weight:600;"
            )
            right.addWidget(b)
        if len(self._term_colors) > 6:
            more = QLabel(f"+{len(self._term_colors)-6}")
            more.setStyleSheet(
                f"color:{COLORS['text_muted']};font-size:8pt;"
                "background:transparent;border:none;"
            )
            right.addWidget(more)

        has_pdf = bool(self._article.get("file_path"))
        icon = QLabel("📄" if has_pdf else "📝")
        icon.setStyleSheet("font-size:15px;background:transparent;border:none;")
        icon.setToolTip("PDF available — click to open" if has_pdf
                        else "No PDF — will show abstract/text")
        right.addWidget(icon)
        lay.addLayout(right)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self._article)
        super().mousePressEvent(e)


# ===========================================================================
# Search row (one term + AND/OR operator)
# ===========================================================================
class SearchRow(QWidget):
    removed  = pyqtSignal(object)
    search   = pyqtSignal()   # Enter pressed

    def __init__(self, is_first=False, parent=None):
        super().__init__(parent)
        self._is_first = is_first
        self.setStyleSheet("background:transparent;border:none;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._op = QComboBox()
        self._op.addItems(["AND", "OR"])
        self._op.setFixedWidth(62)
        self._op.setStyleSheet(_cb_s())
        self._op.setVisible(not is_first)
        lay.addWidget(self._op)

        self._le = QLineEdit()
        self._le.setPlaceholderText("Type any word, phrase, or object name…")
        self._le.setStyleSheet(_le_s())
        self._le.returnPressed.connect(self.search)
        lay.addWidget(self._le, 1)

        rem = QPushButton("×")
        rem.setFixedSize(22, 22)
        rem.setVisible(not is_first)
        rem.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_muted']};"
            "border:none;font-size:13pt;padding:0;line-height:1;}}"
            f"QPushButton:hover{{color:{COLORS['accent_rose']};}}"
        )
        rem.clicked.connect(lambda: self.removed.emit(self))
        lay.addWidget(rem)

    def value(self):
        """Returns (op_or_None, text) or None if text is blank."""
        t = self._le.text().strip()
        if not t:
            return None
        return (None if self._is_first else self._op.currentText(), t)


# ===========================================================================
# SearchModule — main widget
# ===========================================================================
class SearchModule(QWidget):
    def __init__(self):
        super().__init__()
        self._analyses = []
        self._pool     = {}   # key → {title,year,journal,text,file_path}
        self._rows: list[SearchRow] = []
        self._exclude_refs: bool = True        # skip reference sections
        self._excluded_sections: set = set()  # section keys to exclude
        self._build_ui()

    # ── public API ────────────────────────────────────────────────────────────
    def set_analyses(self, analyses: list):
        self._analyses = analyses
        self._rebuild_pool()

    def refresh(self):
        self._rebuild_pool()

    # ── pool ──────────────────────────────────────────────────────────────────
    def _rebuild_pool(self):
        self._pool = {}
        for ana in self._analyses:
            try:    articles = ana.db.get_articles()
            except: articles = []
            for art in articles:
                key = f"{art.get('title','').strip().lower()}|{art.get('year','')}"
                if key not in self._pool:
                    self._pool[key] = {
                        "title":     art.get("title", ""),
                        "year":      art.get("year", ""),
                        "journal":   art.get("journal", ""),
                        "file_path": art.get("file_path", ""),
                        "text":      _article_text(art),
                    }
        n = len(self._pool)
        self._pool_lbl.setText(
            f"Pool: {n} article{'s' if n!=1 else ''} · "
            f"{len(self._analyses)} analys{'es' if len(self._analyses)!=1 else 'is'}"
        )

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        hdr = QWidget(); hdr.setFixedHeight(54)
        hdr.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20, 0, 20, 0)
        t1 = QLabel("Reference Search")
        t1.setStyleSheet(
            f"font-size:15pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        t2 = QLabel("Search any word or object across all analyses · AND / OR between rows · click to open PDF")
        t2.setStyleSheet(
            f"font-size:9pt;color:{COLORS['text_secondary']};"
            "background:transparent;border:none;"
        )
        ts = QVBoxLayout(); ts.setSpacing(1); ts.addWidget(t1); ts.addWidget(t2)
        hl.addLayout(ts); hl.addStretch()
        self._pool_lbl = QLabel("")
        self._pool_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;"
        )
        hl.addWidget(self._pool_lbl)

        # Skip References toggle
        self._btn_excl_refs = make_btn("📚  Skip References: ON", primary=False)
        self._btn_excl_refs.setToolTip(
            "When ON, text after the References / Bibliography heading is ignored.\n"
            "Turn OFF if your articles use non-standard headings."
        )
        self._btn_excl_refs.setCheckable(True)
        self._btn_excl_refs.setChecked(True)
        self._btn_excl_refs.clicked.connect(self._toggle_exclude_refs)
        self._update_refs_btn_style()
        hl.addWidget(self._btn_excl_refs)

        # Section Filters button
        self._btn_section_filter = make_btn("🗂  Section Filters")
        self._btn_section_filter.setToolTip(
            "Choose which article sections (Introduction, Methods, Results, etc.)\n"
            "to EXCLUDE from the search text."
        )
        self._btn_section_filter.clicked.connect(self._open_section_filter_dialog)
        self._update_section_filter_btn_style()
        hl.addWidget(self._btn_section_filter)

        root.addWidget(hdr)

        # main splitter
        from PyQt5.QtWidgets import QSplitter
        body = QSplitter(Qt.Horizontal)
        body.setStyleSheet(
            f"QSplitter::handle{{background:{COLORS['border']};width:1px;}}"
        )

        # ── LEFT: query panel ──────────────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(270); left.setMaximumWidth(340)
        left.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-right:1px solid {COLORS['border']};"
        )
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 14, 14, 14)
        ll.setSpacing(8)

        sec = QLabel("SEARCH TERMS")
        sec.setStyleSheet(
            f"font-size:7.5pt;font-weight:700;color:{COLORS['text_muted']};"
            "letter-spacing:1px;background:transparent;border:none;"
        )
        ll.addWidget(sec)

        # rows container
        self._rows_w = QWidget()
        self._rows_w.setStyleSheet("background:transparent;border:none;")
        self._rows_lay = QVBoxLayout(self._rows_w)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(5)
        ll.addWidget(self._rows_w)

        # + Add / Clear
        add_clr = QHBoxLayout()
        btn_add = QPushButton("＋ Add row")
        btn_add.setFixedHeight(26)
        btn_add.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['accent_teal']};"
            f"border:1px dashed {COLORS['border']};border-radius:4px;"
            "padding:0 10px;font-size:8pt;}}"
            f"QPushButton:hover{{background:{COLORS['bg_hover']};}}"
        )
        btn_add.clicked.connect(self._add_row)
        btn_clr = QPushButton("✕ Clear")
        btn_clr.setFixedHeight(26)
        btn_clr.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_muted']};"
            f"border:1px solid {COLORS['border']};border-radius:4px;"
            "padding:0 8px;font-size:8pt;}}"
            f"QPushButton:hover{{color:{COLORS['accent_rose']};}}"
        )
        btn_clr.clicked.connect(self._clear)
        add_clr.addWidget(btn_add); add_clr.addWidget(btn_clr); add_clr.addStretch()
        ll.addLayout(add_clr)

        # case-sensitive toggle
        self._case_cb = QCheckBox("Case-sensitive search")
        self._case_cb.setStyleSheet(
            f"QCheckBox{{color:{COLORS['text_secondary']};font-size:9pt;"
            "background:transparent;border:none;spacing:6px;}"
            f"QCheckBox::indicator{{width:14px;height:14px;"
            f"background:{COLORS['input_bg']};border:1px solid {COLORS['border']};"
            "border-radius:3px;}"
            f"QCheckBox::indicator:checked{{background:{COLORS['accent_blue']};"
            f"border-color:{COLORS['accent_blue']};}}"
        )
        self._case_cb.setToolTip(
            "When checked, 'Water' will not match 'water'.\n"
            "Useful for chemical symbols (e.g. 'Pb', 'Hg')."
        )
        ll.addWidget(self._case_cb)

        # divider
        div = QFrame(); div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(
            f"color:{COLORS['border']};background:{COLORS['border']};"
            "border:none;max-height:1px;"
        )
        ll.addWidget(div)

        # Search button
        self._btn_s = QPushButton("🔍  Search")
        self._btn_s.setFixedHeight(34)
        self._btn_s.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent_blue']};color:white;"
            "border:none;border-radius:6px;font-size:10pt;font-weight:600;}}"
            f"QPushButton:hover{{background:{COLORS['accent_blue']}cc;}}"
            "QPushButton:disabled{opacity:0.5;}"
        )
        self._btn_s.clicked.connect(self._run)
        ll.addWidget(self._btn_s)

        self._prog = QProgressBar()
        self._prog.setFixedHeight(4); self._prog.setTextVisible(False)
        self._prog.setStyleSheet(
            f"QProgressBar{{background:{COLORS['bg_tertiary']};border:none;border-radius:2px;}}"
            f"QProgressBar::chunk{{background:{COLORS['accent_blue']};border-radius:2px;}}"
        )
        self._prog.hide()
        ll.addWidget(self._prog)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"font-size:8.5pt;color:{COLORS['accent_blue']};"
            "background:transparent;border:none;"
        )
        ll.addWidget(self._status)
        ll.addStretch()
        body.addWidget(left)

        # ── RIGHT: results ─────────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        # results header
        rh = QWidget(); rh.setFixedHeight(36)
        rh.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        rhl = QHBoxLayout(rh); rhl.setContentsMargins(14,0,14,0)
        self._count_lbl = QLabel("Results will appear here after a search.")
        self._count_lbl.setStyleSheet(
            f"font-size:9pt;font-weight:600;color:{COLORS['text_secondary']};"
            "background:transparent;border:none;"
        )
        rhl.addWidget(self._count_lbl); rhl.addStretch()
        hint = QLabel("Click a row to open")
        hint.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;font-style:italic;"
        )
        rhl.addWidget(hint)
        rl.addWidget(rh)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea{{background:{COLORS['bg_primary']};border:none;}}"
        )
        self._res_w = QWidget()
        self._res_w.setStyleSheet(f"background:{COLORS['bg_primary']};")
        self._res_lay = QVBoxLayout(self._res_w)
        self._res_lay.setContentsMargins(12, 10, 12, 10)
        self._res_lay.setSpacing(6)
        self._res_lay.setAlignment(Qt.AlignTop)

        self._placeholder = QLabel("🔍  Enter search terms and press Search")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(
            f"font-size:11pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;"
        )
        self._res_lay.addWidget(self._placeholder)

        self._scroll.setWidget(self._res_w)
        rl.addWidget(self._scroll, 1)
        body.addWidget(right)
        body.setSizes([295, 900])
        root.addWidget(body, 1)

        # seed first row
        self._add_row()

    # ── filter helpers ───────────────────────────────────────────────────────
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

    def _get_search_text(self, raw: str) -> str:
        """Apply active exclusion filters to article text before searching."""
        if self._exclude_refs:
            raw = _strip_references(raw)
        if self._excluded_sections:
            raw = _strip_sections(raw, self._excluded_sections)
        return raw

    # ── rows ──────────────────────────────────────────────────────────────────
    def _add_row(self):
        row = SearchRow(is_first=(len(self._rows) == 0))
        row.removed.connect(self._remove_row)
        row.search.connect(self._run)
        self._rows_lay.addWidget(row)
        self._rows.append(row)

    def _remove_row(self, row):
        if len(self._rows) <= 1:
            return
        self._rows.remove(row)
        row.setParent(None); row.deleteLater()

    def _clear(self):
        for row in self._rows[1:]:
            row.setParent(None); row.deleteLater()
        self._rows = self._rows[:1]
        if self._rows:
            self._rows[0]._le.clear()
        self._status.setText("")

    # ── search ────────────────────────────────────────────────────────────────
    def _run(self):
        parts = [r.value() for r in self._rows]
        parts = [p for p in parts if p]

        if not parts:
            self._status.setStyleSheet(
                f"font-size:8.5pt;color:{COLORS['accent_rose']};"
                "background:transparent;border:none;"
            )
            self._status.setText("Enter at least one search term.")
            return

        if not self._pool:
            self._rebuild_pool()

        case = self._case_cb.isChecked()

        # Build term-colour list: one entry per search row
        term_colors = []
        for i, (op, text) in enumerate(parts):
            hex_c = _PAL_HEX[i % len(_PAL_HEX)]
            # Split comma-separated terms within one row
            terms = [t.strip() for t in text.split(',') if t.strip()]
            term_colors.append((text, terms, hex_c, op))

        self._btn_s.setEnabled(False)
        self._prog.setRange(0, len(self._pool))
        self._prog.setValue(0)
        self._prog.show()
        self._clear_results()
        QApplication.processEvents()

        # ── Build independent OR-groups ─────────────────────────────────────
        # Rows joined by AND belong to the same group (all must match).
        # A new OR operator starts a fresh independent group.
        # An article passes if ANY group is fully satisfied.
        #
        # Example:
        #   Row1: "cancer"          (first row, starts group 0)
        #   Row2: AND  "mouse"      (same group 0 → both required)
        #   Row3: OR   "diabetes"   (new group 1 → independent)
        #   Row4: AND  "insulin"    (same group 1 → both required)
        #
        #  Article passes if:
        #    ("cancer" AND "mouse")  OR  ("diabetes" AND "insulin")

        groups = []        # list of lists of (label, terms, hex_c)
        current_group = []
        for label, terms, hex_c, op in term_colors:
            if op == "OR" and current_group:
                groups.append(current_group)
                current_group = []
            current_group.append((label, terms, hex_c))
        if current_group:
            groups.append(current_group)

        results = []
        for i, (key, art) in enumerate(self._pool.items()):
            self._prog.setValue(i + 1)
            if i % 40 == 0:
                QApplication.processEvents()

            body_text = self._get_search_text(art.get("text", "") or art.get("title", ""))

            matched_tc = []   # rows that actually hit (for badges)
            match = False

            for group in groups:
                # Every row in this group must hit
                group_hits = []
                all_hit = True
                for label, terms, hex_c in group:
                    hit = any(_term_in_text(t, body_text, case) for t in terms)
                    if hit:
                        group_hits.append((label, terms, hex_c))
                    else:
                        all_hit = False
                if all_hit:
                    match = True
                    matched_tc.extend(group_hits)

            if match:
                results.append((art, matched_tc))

        self._prog.hide()
        self._btn_s.setEnabled(True)

        n = len(results)
        color = COLORS['accent_blue'] if n > 0 else COLORS['accent_rose']
        self._status.setStyleSheet(
            f"font-size:8.5pt;color:{color};"
            "background:transparent;border:none;"
        )

        if n == 0:
            self._status.setText("No articles found.")
            self._count_lbl.setText("No results")
            self._show_empty()
            return

        self._status.setText(f"{n} article(s) found.")
        self._count_lbl.setText(
            f"{n} article{'s' if n != 1 else ''} found"
        )

        # Sort: most matched rows first, then year desc
        results.sort(key=lambda x: (-len(x[1]), -(x[0].get("year") or 0)))
        for art, matched_tc in results:
            row_w = ArticleRow(art, matched_tc)
            row_w.clicked.connect(self._open_article)
            self._res_lay.addWidget(row_w)

    # ── results helpers ───────────────────────────────────────────────────────
    def _clear_results(self):
        while self._res_lay.count():
            item = self._res_lay.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def _show_empty(self):
        lbl = QLabel("No articles matched your search.\nTry different terms or check the case-sensitive option.")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"font-size:10pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;padding:40px;"
        )
        self._res_lay.addWidget(lbl)

    # ── open article ──────────────────────────────────────────────────────────
    def _open_article(self, article: dict):
        # Collect all term_colors for this specific article
        case = self._case_cb.isChecked()
        parts = [r.value() for r in self._rows if r.value()]
        body_text = article.get("text", "") or article.get("title", "")

        term_colors_for_viewer = []
        for i, (op, text) in enumerate(parts):
            terms = [t.strip() for t in text.split(',') if t.strip()]
            if any(_term_in_text(t, body_text, case) for t in terms):
                hex_c = _PAL_HEX[i % len(_PAL_HEX)]
                term_colors_for_viewer.append((text, terms, hex_c))

        pdf = article.get("file_path", "")
        if pdf:
            if not os.path.isfile(pdf):
                QMessageBox.warning(
                    self, "PDF not found",
                    f"File not found:\n{pdf}\n\nRe-attach in the Mining module."
                )
                return
            dlg = MultiColorPdfViewer(
                self, pdf, term_colors_for_viewer,
                title=article.get("title", ""),
                case_sensitive=case
            )
            dlg.show()
        else:
            self._text_viewer(article, term_colors_for_viewer, case)

    def _text_viewer(self, article: dict, term_colors: list, case: bool):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Abstract — {article.get('title','')[:60]}")
        dlg.resize(720, 480)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(dlg); lay.setContentsMargins(0,0,0,0)

        # small header with badges
        hdr = QWidget(); hdr.setFixedHeight(40)
        hdr.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        hl = QHBoxLayout(hdr); hl.setContentsMargins(12,0,12,0)
        ttl = QLabel(article.get("title",""))
        ttl.setStyleSheet(
            f"font-weight:600;font-size:9pt;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        ttl.setMaximumWidth(500)
        hl.addWidget(ttl); hl.addStretch()
        for label, _t, hex_c in term_colors[:5]:
            b = QLabel(f" {label} ")
            b.setStyleSheet(
                f"background:{hex_c}33;color:{hex_c};"
                f"border:1px solid {hex_c}66;border-radius:8px;"
                "padding:1px 6px;font-size:8pt;"
            )
            hl.addWidget(b)
        lay.addWidget(hdr)

        te = QTextEdit(); te.setReadOnly(True)
        te.setStyleSheet(
            f"QTextEdit{{background:{COLORS['bg_primary']};"
            f"color:{COLORS['text_primary']};border:none;"
            "font-size:9pt;padding:12px;line-height:1.5;}}"
        )
        raw = article.get("text","") or "No abstract / text available."
        te.setHtml(_make_html(raw, term_colors, case))
        lay.addWidget(te, 1)

        btn = make_btn("Close"); btn.clicked.connect(dlg.close)
        bot = QHBoxLayout(); bot.setContentsMargins(12,8,12,8)
        bot.addStretch(); bot.addWidget(btn)
        lay.addLayout(bot)
        dlg.show()


def _make_html(text: str, term_colors: list, case: bool) -> str:
    """Wrap matched terms in coloured <mark> spans."""
    import html as _h
    safe = _h.escape(text)

    # Sort longest-first to avoid partial replacements
    pairs = []
    for label, terms, hex_c in term_colors:
        for t in terms:
            if t.strip():
                pairs.append((_h.escape(t), hex_c))
    pairs.sort(key=lambda x: -len(x[0]))

    placeholder_map = {}
    for esc_t, hex_c in pairs:
        ph = f"\x00P{len(placeholder_map)}\x00"
        mark = (
            f'<mark style="background:{hex_c}55;color:inherit;'
            f'border-radius:3px;padding:0 2px;">{esc_t}</mark>'
        )
        flags = 0 if case else re.IGNORECASE
        new_safe, n = re.subn(re.escape(esc_t), ph, safe, flags=flags)
        if n:
            safe = new_safe
            placeholder_map[ph] = mark

    for ph, mark in placeholder_map.items():
        safe = safe.replace(ph, mark)

    fg = COLORS["text_primary"]
    return (
        "<html><body style='font-family:Segoe UI,Arial;font-size:9pt;"
        f"line-height:1.6;color:{fg};'>{safe}</body></html>"
    )
