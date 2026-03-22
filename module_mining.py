"""
SLDM — Module 2: Article Mining
Mendeley-style article library + object citation detection.
"""

import os
import json
import re
import urllib.request
import urllib.error
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QFileDialog, QMessageBox, QSplitter,
    QFrame, QScrollArea, QSpinBox, QAbstractItemView, QProgressBar,
    QGroupBox, QCheckBox, QGridLayout, QApplication, QScrollBar,
    QSizePolicy, QStackedWidget, QComboBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QObject, pyqtSlot, QSize, QRectF
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap, QPainter, QPen, QBrush, QImage

from core.database import Database
from core.widgets import StatCard, Panel, SearchBar, make_btn, EmptyState, Toast
from core.theme import COLORS
from modules.module_objects import ObjectDialog




# ── SEARCH HELPER ─────────────────────────────────────────────────────────────
# Characters that are valid immediately before or after a short term.
# A short term must be surrounded by these on both sides.
# This is stricter than \b: it requires an actual space, punctuation or
# start/end-of-string — so "B" never matches inside "BPA", "Ba" or "by".
_SHORT_BOUNDARY = r'(?:(?<=[^A-Za-z0-9])|(?<=\A)|^)'   # left side
_SHORT_BOUNDARY_R = r'(?=[^A-Za-z0-9]|$)'               # right side

def _term_matches(term: str, text: str) -> bool:
    """
    Robust term matching.

    Terms < 4 characters (e.g. "B", "As", "Al", "Hg"):
      - Case-SENSITIVE (exact case required, "B" ≠ "b")
      - Must be surrounded by non-alphanumeric characters or string edges.
        "B" matches " B " or "(B)" or "B," but NOT "BPA", "Ba", "by",
        "absorbed", etc.

    Terms ≥ 4 characters (e.g. "paraben", "atrazine"):
      - Case-INSENSITIVE
      - Standard word-boundary (\b) — "paraben" does NOT match "parabens".
    """
    if not term or not text:
        return False
    escaped = re.escape(term)
    if len(term) < 4:
        # Strict boundaries: no adjacent letter or digit on either side,
        # and case-sensitive (no re.IGNORECASE).
        pattern = r'(?<![A-Za-z0-9])' + escaped + r'(?![A-Za-z0-9])'
        return bool(re.search(pattern, text))
    else:
        pattern = r'\b' + escaped + r'\b'
        return bool(re.search(pattern, text, re.IGNORECASE))


def _any_term_matches(terms: list, text: str) -> bool:
    """Returns True if any term in the list matches the text."""
    return any(_term_matches(t, text) for t in terms)


def _parse_syns(raw) -> list:
    """
    Parse synonyms from the DB value (JSON string or list).
    Splits by semicolon only — commas are valid inside compound names
    (e.g. "1,4-dichlorobenzene") and must not be treated as separators.
    Handles objects imported with the old comma-split format gracefully
    by only splitting on semicolons.
    """
    if isinstance(raw, str):
        try:
            items = json.loads(raw)
        except Exception:
            items = [raw]
    else:
        items = raw or []
    result = []
    for item in items:
        for part in str(item).split(';'):
            part = part.strip()
            if part:
                result.append(part)
    return result


# ── REFERENCE SECTION STRIPPER ────────────────────────────────────────────────
# All heading variants that signal the start of a reference/bibliography section.
# The list covers English, Portuguese, Spanish, French, German and common
# abbreviations found in scientific articles.
_REF_HEADINGS = [
    # English
    "references", "bibliography", "works cited", "literature cited",
    "citations", "reference list", "cited literature", "cited references",
    "literature", "sources", "further reading",
    # Portuguese
    "referências", "referencias", "referências bibliográficas",
    "referencias bibliograficas", "referências citadas", "bibliografia",
    "fontes", "literatura citada",
    # Spanish
    "bibliografía", "bibliografia", "referencias bibliográficas",
    "fuentes", "literatura citada",
    # French
    "références", "references bibliographiques", "bibliographie",
    # German
    "literatur", "quellenverzeichnis", "literaturverzeichnis",
    "literaturnachweis",
    # Common abbreviations / numbered
    "refs.", "ref.",
]

# Pre-compiled pattern: matches a heading line that IS the references section.
# Accepts optional numbering (e.g. "5. References"), optional trailing colon,
# optional surrounding whitespace / line-start.
_REF_PATTERN = re.compile(
    r'(?:^|\n)'                          # start of line
    r'\s*(?:\d+[\.\)]?\s*)?'            # optional "5." or "5)"
    r'(?:' + '|'.join(re.escape(h) for h in _REF_HEADINGS) + r')'
    r'\s*:?\s*(?:\n|$)',                 # optional colon, end of line
    re.IGNORECASE
)


def _strip_references(text: str) -> str:
    """
    Return the text up to (but not including) the first reference-section
    heading.  If no heading is found the full text is returned unchanged.
    """
    m = _REF_PATTERN.search(text)
    if m:
        return text[:m.start()]
    return text


# ── SECTION EXCLUSION ENGINE ──────────────────────────────────────────────────
# Each entry: (section_key, display_label, [heading variants])
# Heading variants cover English, Portuguese, Spanish, French, German and
# common abbreviations found in scientific articles.
SECTION_DEFS = {
    "introduction": {
        "label": "Introduction",
        "icon": "📖",
        "headings": [
            # English
            "introduction", "background", "overview", "preamble",
            # Portuguese
            "introdução", "introducao", "contextualização", "contextualizacao",
            "antecedentes",
            # Spanish
            "introducción", "introduccion", "antecedentes", "generalidades",
            # French
            "introduction", "contexte", "généralités",
            # German
            "einleitung", "hintergrund", "einführung",
        ],
    },
    "methods": {
        "label": "Methods / Experimental",
        "icon": "⚗️",
        "headings": [
            # English
            "methods", "methodology", "materials and methods",
            "materials & methods", "experimental", "experimental section",
            "experimental methods", "experimental procedure",
            "experimental procedures", "experimental design",
            "study design", "patients and methods", "subjects and methods",
            "participants and methods", "procedures",
            # Portuguese
            "métodos", "metodos", "metodologia", "materiais e métodos",
            "materiais e metodos", "material e métodos", "material e metodos",
            "procedimentos", "parte experimental", "seção experimental",
            "secao experimental", "procedimentos experimentais",
            # Spanish
            "métodos", "metodología", "metodologia",
            "materiales y métodos", "materiales y metodos",
            "parte experimental", "procedimientos",
            # French
            "méthodes", "methodologie", "matériel et méthodes",
            "matériels et méthodes", "partie expérimentale",
            # German
            "methoden", "methodik", "material und methoden",
            "experimenteller teil", "versuchsdurchführung",
        ],
    },
    "results": {
        "label": "Results",
        "icon": "📊",
        "headings": [
            # English
            "results", "findings", "observations",
            "results and discussion", "results & discussion",
            # Portuguese
            "resultados", "resultados e discussão", "resultados e discussao",
            "resultados e análise", "achados",
            # Spanish
            "resultados", "resultados y discusión", "resultados y discusion",
            "hallazgos",
            # French
            "résultats", "resultats", "résultats et discussion",
            # German
            "ergebnisse", "resultate", "ergebnisse und diskussion",
        ],
    },
    "discussion": {
        "label": "Discussion",
        "icon": "💬",
        "headings": [
            # English
            "discussion", "general discussion", "interpretation",
            # Portuguese
            "discussão", "discussao", "discussão geral",
            # Spanish
            "discusión", "discusion",
            # French
            "discussion", "interprétation",
            # German
            "diskussion", "auswertung",
        ],
    },
    "conclusion": {
        "label": "Conclusion",
        "icon": "🏁",
        "headings": [
            # English
            "conclusion", "conclusions", "concluding remarks",
            "summary", "final remarks", "closing remarks",
            "summary and conclusions", "conclusions and future work",
            "outlook",
            # Portuguese
            "conclusão", "conclusao", "conclusões", "conclusoes",
            "considerações finais", "consideracoes finais",
            "resumo", "perspectivas",
            # Spanish
            "conclusión", "conclusion", "conclusiones",
            "consideraciones finales", "perspectivas",
            # French
            "conclusion", "conclusions", "remarques finales",
            "perspectives",
            # German
            "schlussfolgerung", "schlussfolgerungen", "zusammenfassung",
            "ausblick", "fazit",
        ],
    },
}

# Pre-compile one regex per section key for fast matching.
_SECTION_PATTERNS: dict = {}
for _key, _sdef in SECTION_DEFS.items():
    _alts = '|'.join(re.escape(h) for h in _sdef["headings"])
    _SECTION_PATTERNS[_key] = re.compile(
        r'(?:^|\n)'
        r'\s*(?:\d+[\.\)]?\s*)?'
        r'(?:' + _alts + r')'
        r'\s*:?\s*(?:\n|$)',
        re.IGNORECASE
    )


def _find_section_boundaries(text: str) -> list:
    """
    Scan the text and return a sorted list of (start, end) tuples for every
    detected section heading — where 'start' is the character offset of the
    heading line and 'end' is the start of the *next* detected heading (or
    end-of-text).  Each tuple also carries the section key.

    Returns: [(key, heading_start, body_start, next_heading_start), ...]
    """
    hits = []
    for key, pat in _SECTION_PATTERNS.items():
        for m in pat.finditer(text):
            hits.append((m.start(), m.end(), key))
    # Sort by position; tie-break by end (longer match wins)
    hits.sort(key=lambda x: (x[0], -x[1]))

    # Deduplicate overlapping matches (keep the first per position)
    deduped = []
    last_end = -1
    for (s, e, k) in hits:
        if s >= last_end:
            deduped.append((s, e, k))
            last_end = e

    # Compute body spans: from heading_end to next heading_start (or EOF)
    boundaries = []
    for i, (s, e, k) in enumerate(deduped):
        next_start = deduped[i + 1][0] if i + 1 < len(deduped) else len(text)
        boundaries.append((k, s, e, next_start))
    return boundaries


def _strip_sections(text: str, excluded_keys: set) -> str:
    """
    Remove all body text belonging to sections whose key is in *excluded_keys*.
    Headings themselves are also removed.  Gaps left by removed sections are
    collapsed to a single blank line so paragraph flow is maintained.
    """
    if not excluded_keys:
        return text

    boundaries = _find_section_boundaries(text)
    if not boundaries:
        return text

    # Build a mask of characters to keep (True = keep)
    keep = bytearray(b'\x01' * len(text))   # all kept by default

    for (key, h_start, body_start, next_h_start) in boundaries:
        if key in excluded_keys:
            # Blank out heading + body
            for i in range(h_start, next_h_start):
                keep[i] = 0

    # Reconstruct text, collapsing removed blocks to '\n\n'
    parts = []
    in_removed = False
    buf = []
    for i, ch in enumerate(text):
        if keep[i]:
            if in_removed:
                parts.append('\n\n')
                in_removed = False
            buf.append(ch)
        else:
            if buf:
                parts.append(''.join(buf))
                buf = []
            in_removed = True
    if buf:
        parts.append(''.join(buf))

    return ''.join(parts).strip()



class ExtractWorker(QObject):
    finished = pyqtSignal(str, str)  # file_path, text
    error    = pyqtSignal(str, str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(self.path)
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            self.finished.emit(self.path, text)
        except ImportError:
            # Fall back to reading as text
            try:
                with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
                    self.finished.emit(self.path, f.read())
            except Exception as e:
                self.error.emit(self.path, str(e))
        except Exception as e:
            self.error.emit(self.path, str(e))


# ── PDF VIEWER WITH HIGHLIGHTS ───────────────────────────────────────────────
class PdfViewerWindow(QDialog):
    """
    Opens a PDF in a separate window and highlights all occurrences
    of the given terms (object name + synonyms) across every page.
    Requires PyMuPDF (fitz).
    """
    HIGHLIGHT_COLOR = (1.0, 0.85, 0.0)   # yellow RGB 0-1

    def __init__(self, parent, pdf_path: str, terms: list, object_name: str):
        super().__init__(parent)
        self.pdf_path   = pdf_path
        self.terms      = [t for t in terms if t.strip()]
        self.object_name = object_name
        self._pages     = []   # list of QPixmap
        self._zoom      = 1.5
        self.setWindowTitle(f"PDF Viewer — {object_name}")
        self.setMinimumSize(860, 740)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._build_ui()
        self._render_pdf()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Toolbar
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(f"background:{COLORS['bg_secondary']}; border-bottom:1px solid {COLORS['border']};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 0, 12, 0)
        bl.setSpacing(8)

        lbl = QLabel(f"🔬  Highlighting: <b>{self.object_name}</b>")
        lbl.setStyleSheet(f"color:{COLORS['text_primary']}; font-size:9pt; background:transparent; border:none;")
        bl.addWidget(lbl)
        bl.addStretch()

        self._lbl_hits = QLabel("")
        self._lbl_hits.setStyleSheet(f"color:{COLORS['accent_amber']}; font-size:9pt; font-weight:600; background:transparent; border:none;")
        bl.addWidget(self._lbl_hits)

        btn_zoom_in  = make_btn("＋ Zoom")
        btn_zoom_out = make_btn("－ Zoom")
        btn_zoom_in.clicked.connect(lambda: self._set_zoom(self._zoom + 0.25))
        btn_zoom_out.clicked.connect(lambda: self._set_zoom(max(0.5, self._zoom - 0.25)))
        bl.addWidget(btn_zoom_out)
        bl.addWidget(btn_zoom_in)
        lay.addWidget(bar)

        # Scroll area with pages
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"QScrollArea{{background:{COLORS['bg_primary']};border:none;}}")

        self.pages_container = QWidget()
        self.pages_container.setStyleSheet(f"background:{COLORS['bg_primary']};")
        self.pages_layout = QVBoxLayout(self.pages_container)
        self.pages_layout.setContentsMargins(24, 16, 24, 16)
        self.pages_layout.setSpacing(12)
        self.pages_layout.setAlignment(Qt.AlignHCenter)

        self.scroll.setWidget(self.pages_container)
        lay.addWidget(self.scroll)

    def _render_pdf(self):
        try:
            import fitz
        except ImportError:
            QMessageBox.warning(self, "PyMuPDF missing",
                "PyMuPDF (fitz) is required for the PDF viewer.\nInstall with: pip install pymupdf")
            self.close(); return

        try:
            doc = fitz.open(self.pdf_path)
        except Exception as e:
            QMessageBox.critical(self, "Cannot open PDF", str(e))
            self.close(); return

        total_hits = 0
        mat = fitz.Matrix(self._zoom, self._zoom)

        for page in doc:
            # Find and highlight all terms
            page_hits = 0
            for term in self.terms:
                hits = page.search_for(term)
                page_hits += len(hits)
                total_hits += len(hits)
                for rect in hits:
                    highlight = page.add_highlight_annot(rect)
                    highlight.set_colors(stroke=self.HIGHLIGHT_COLOR)
                    highlight.update()

            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = QImage(pix.samples, pix.width, pix.height,
                         pix.stride, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(img)
            self._pages.append(pixmap)

            lbl = QLabel()
            lbl.setPixmap(pixmap)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("background:transparent; border:none;")
            self.pages_layout.addWidget(lbl)

        doc.close()
        self._lbl_hits.setText(f"{total_hits} occurrence(s) found")

    def _set_zoom(self, zoom):
        self._zoom = zoom
        # Clear pages and re-render
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._pages.clear()
        self._render_pdf()


# ── DOI METADATA FETCHER ──────────────────────────────────────────────────────
def fetch_doi_metadata(doi: str) -> dict:
    """
    Fetches bibliographic metadata from Crossref public API.
    Returns a dict with keys: title, authors, year, journal,
    volume, issue, pages, doi, abstract, keywords.
    Raises ValueError on bad DOI / not found.
    """
    doi = doi.strip().lstrip("https://doi.org/").lstrip("http://dx.doi.org/")
    url = f"https://api.crossref.org/works/{urllib.request.quote(doi, safe='/')}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "SLDM/3.0 (scientific literature miner; mailto:user@example.com)"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise ValueError(f"DOI not found (HTTP {e.code})")
    except Exception as e:
        raise ValueError(f"Network error: {e}")

    w = data.get("message", {})

    # Title
    title_list = w.get("title", [])
    title = title_list[0] if title_list else ""

    # Authors
    authors_raw = w.get("author", [])
    authors = ", ".join(
        f"{a.get('family','')}, {a.get('given','')}".strip(", ")
        for a in authors_raw
    )

    # Year
    year = None
    for date_field in ("published-print", "published-online", "issued"):
        dp = w.get(date_field, {}).get("date-parts", [[]])
        if dp and dp[0]:
            year = dp[0][0]; break

    # Journal
    container = w.get("container-title", [])
    journal = container[0] if container else ""

    # Volume / Issue / Pages
    volume = w.get("volume", "")
    issue  = w.get("issue", "")
    pages  = w.get("page", "")

    # Abstract (Crossref sometimes provides it)
    abstract = w.get("abstract", "")
    # Strip JATS XML tags if present
    abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    # Keywords
    subjects = w.get("subject", [])
    keywords = ", ".join(subjects)

    return {
        "title":    title,
        "authors":  authors,
        "year":     year,
        "journal":  journal,
        "volume":   volume,
        "issue":    issue,
        "pages":    pages,
        "doi":      doi,
        "abstract": abstract,
        "keywords": keywords,
    }


class _DoiFetchWorker(QObject):
    """Fetches DOI metadata in background thread."""
    finished = pyqtSignal(dict)
    error    = pyqtSignal(str)

    def __init__(self, doi: str):
        super().__init__()
        self.doi = doi

    @pyqtSlot()
    def run(self):
        try:
            meta = fetch_doi_metadata(self.doi)
            self.finished.emit(meta)
        except Exception as e:
            self.error.emit(str(e))



# ── OBJECT SEARCH PANEL ──────────────────────────────────────────────────────
# Shared between MiningModule (single-analysis) and CoOccurrencePanel (multi).
#
# Single-analysis mode:   ObjectSearchPanel(db=db)
# Multi-analysis mode:    ObjectSearchPanel(analyses=[ana1, ana2, ...])
#
# Call .get_matching_article_ids(all_articles) → set of article IDs
# or   .get_matching_article_keys(pool)        → set of pool keys  (combine mode)
# Signal: search_changed — emitted whenever the user edits any row.

_INPUT_STYLE = (
    "QLineEdit{{"
    f"background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
    "border-radius:4px;"
    f"color:{COLORS['text_primary']};padding:3px 7px;font-size:9pt;}}"
    f"QLineEdit:focus{{border:1px solid {COLORS['accent_blue']};}}"
)
def _cb_style_mining():
    return (
        f"QComboBox{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
        "border-radius:4px;"
        f"color:{COLORS['text_primary']};padding:2px 6px;font-size:8pt;}}"
        "QComboBox::drop-down{border:none;}"
        f"QComboBox QAbstractItemView{{background:{COLORS['bg_secondary']};"
        f"color:{COLORS['text_primary']};border:1px solid {COLORS['border']};}}"
    )

def _sec_style_mining():
    return (
        f"font-size:7.5pt;font-weight:700;color:{COLORS['text_muted']};"
        "letter-spacing:1px;background:transparent;border:none;"
    )

# backward compat aliases (evaluated at call sites, fine since str is immutable)
_CB_STYLE  = property(lambda _: _cb_style_mining())
_SEC_STYLE = property(lambda _: _sec_style_mining())


def _obj_all_terms(obj: dict) -> list:
    """Return all searchable terms for an object: name + synonyms + all categories."""
    terms = [obj["name"].strip()] if obj.get("name") else []
    # synonyms
    raw = obj.get("synonyms", [])
    if isinstance(raw, str):
        try:    raw = json.loads(raw)
        except: raw = [raw]
    for item in (raw or []):
        for part in str(item).split(";"):
            part = part.strip()
            if part:
                terms.append(part)
    # categories
    cats = obj.get("categories") or []
    for c in cats:
        c = str(c).strip()
        if c:
            terms.append(c)
    return [t for t in terms if t]


class ObjectSearchPanel(QWidget):
    """
    Stacked query builder:
        [  text field  ] [analysis ▾]   (first row — no operator prefix)
        [AND/OR ▾] [ text field ] [analysis ▾]   (subsequent rows)
        [+ Add]  [✕ Clear]  [🔍 Search]   [N articles found]

    'analysis' combo only shown in multi-analysis mode.
    Matches object names, synonyms, and category values.
    """
    search_changed = pyqtSignal()

    def __init__(self, db=None, analyses=None, parent=None):
        super().__init__(parent)
        self._db       = db          # single-analysis
        self._analyses = analyses or []   # multi-analysis
        self._multi    = bool(analyses)
        self._rows: list = []        # list of (op_cb | None, text_le, ana_cb | None)
        self._build_ui()
        self._add_row()              # start with one empty row

    # ── helpers ───────────────────────────────────────────────────────────────
    def _ana_names(self):
        return [a.name for a in self._analyses]

    def _objects_for(self, ana_name: str) -> list:
        """Return object dicts for the given analysis (or db in single mode)."""
        if self._multi:
            for a in self._analyses:
                if a.name == ana_name:
                    try:    return a.db.get_objects()
                    except: return []
            return []
        try:    return self._db.get_objects()
        except: return []

    def update_analyses(self, analyses: list):
        """Refresh the available analysis list (called by Combine on pool rebuild)."""
        self._analyses = analyses
        self._multi    = bool(analyses)
        # Repopulate all analysis combos
        for _, _, ana_cb in self._rows:
            if ana_cb is not None:
                prev = ana_cb.currentText()
                ana_cb.blockSignals(True); ana_cb.clear()
                ana_cb.addItems(self._ana_names())
                idx = ana_cb.findText(prev)
                if idx >= 0: ana_cb.setCurrentIndex(idx)
                ana_cb.blockSignals(False)

    def update_analyses_from_pool(self, pool: dict):
        """
        Called by CoOccurrencePanel — updates analysis names and stores pool
        so object lookup works without real analysis objects.
        """
        self._pool_ref = pool
        names = list(pool.get("lists", {}).keys())
        # Build lightweight proxy objects so _objects_for works
        class _PoolProxy:
            def __init__(self, name, objs):
                self.name = name
                self._objs = objs
            class _DB:
                def __init__(self, objs): self._objs = objs
                def get_objects(self): return self._objs
            @property
            def db(self): return self._DB(self._objs)

        self._analyses = [_PoolProxy(n, pool["lists"][n]) for n in names]
        self._multi    = bool(self._analyses)
        # Repopulate all analysis combos
        for _, _, ana_cb in self._rows:
            if ana_cb is not None:
                prev = ana_cb.currentText()
                ana_cb.blockSignals(True); ana_cb.clear()
                ana_cb.addItems(names)
                idx = ana_cb.findText(prev)
                if idx >= 0: ana_cb.setCurrentIndex(idx)
                ana_cb.blockSignals(False)

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 6)
        outer.setSpacing(4)

        # Header
        hdr = QHBoxLayout()
        lbl = QLabel("OBJECT SEARCH")
        lbl.setStyleSheet(_sec_style_mining())
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._result_lbl = QLabel("")
        self._result_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['accent_teal']};"
            "background:transparent;border:none;"
        )
        hdr.addWidget(self._result_lbl)
        outer.addLayout(hdr)

        # Rows container
        self._rows_widget = QWidget()
        self._rows_widget.setStyleSheet("background:transparent;border:none;")
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(3)
        outer.addWidget(self._rows_widget)

        # Bottom toolbar
        bot = QHBoxLayout()
        btn_add = QPushButton("＋ Add")
        btn_add.setFixedHeight(24)
        btn_add.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['accent_teal']};"
            f"border:1px dashed {COLORS['border']};border-radius:4px;"
            f"padding:0 8px;font-size:8pt;}}"
            f"QPushButton:hover{{background:{COLORS['bg_hover']};}}"
        )
        btn_add.clicked.connect(self._add_row)
        btn_clr = QPushButton("✕ Clear")
        btn_clr.setFixedHeight(24)
        btn_clr.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_muted']};"
            f"border:1px solid {COLORS['border']};border-radius:4px;"
            f"padding:0 8px;font-size:8pt;}}"
            f"QPushButton:hover{{color:{COLORS['accent_rose']};}}"
        )
        btn_clr.clicked.connect(self._clear_all)
        self._btn_search = QPushButton("🔍  Search")
        self._btn_search.setFixedHeight(26)
        self._btn_search.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent_blue']}22;"
            f"color:{COLORS['accent_blue']};border:1px solid {COLORS['accent_blue']}55;"
            f"border-radius:4px;padding:0 10px;font-size:8.5pt;font-weight:600;}}"
            f"QPushButton:hover{{background:{COLORS['accent_blue']}44;}}"
        )
        self._btn_search.clicked.connect(self.search_changed)
        bot.addWidget(btn_add); bot.addWidget(btn_clr); bot.addStretch()
        bot.addWidget(self._btn_search)
        outer.addLayout(bot)

    def _add_row(self):
        row_w = QWidget()
        row_w.setStyleSheet("background:transparent;border:none;")
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)

        is_first = (len(self._rows) == 0)

        # Operator combo (AND/OR) — hidden for the first row
        op_cb = None
        if not is_first:
            op_cb = QComboBox()
            op_cb.addItems(["AND", "OR"])
            op_cb.setFixedWidth(58)
            op_cb.setStyleSheet(_cb_style_mining())
            rl.addWidget(op_cb)

        # Text input
        le = QLineEdit()
        le.setPlaceholderText("Object name, synonym or category…")
        le.setStyleSheet(
            f"QLineEdit{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
            f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 7px;font-size:9pt;}}"
            f"QLineEdit:focus{{border:1px solid {COLORS['accent_blue']};}}"
        )
        le.returnPressed.connect(self.search_changed)
        rl.addWidget(le, 1)

        # Analysis combo — only in multi mode
        ana_cb = None
        if self._multi:
            ana_cb = QComboBox()
            ana_cb.addItems(self._ana_names())
            ana_cb.setMinimumWidth(100)
            ana_cb.setStyleSheet(_cb_style_mining())
            rl.addWidget(ana_cb)

        # Remove button (hidden for row 0)
        rem_btn = QPushButton("×")
        rem_btn.setFixedSize(22, 22)
        rem_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_muted']};"
            "border:none;font-size:12pt;padding:0;}}"
            f"QPushButton:hover{{color:{COLORS['accent_rose']};}}"
        )
        rem_btn.setVisible(not is_first)
        rem_btn.clicked.connect(lambda _, rw=row_w, t=(op_cb, le, ana_cb): self._remove_row(rw, t))
        rl.addWidget(rem_btn)

        self._rows_layout.addWidget(row_w)
        self._rows.append((op_cb, le, ana_cb))

    def _remove_row(self, row_w, tup):
        if len(self._rows) <= 1:
            return
        if tup in self._rows:
            self._rows.remove(tup)
        row_w.setParent(None)
        row_w.deleteLater()

    def _clear_all(self):
        # Clear text in all rows, remove extra rows, reset result label
        for op_cb, le, ana_cb in self._rows:
            le.clear()
        # Remove all but first row
        while len(self._rows) > 1:
            op_cb, le, ana_cb = self._rows.pop()
            # find and destroy its parent widget
            le.parent().setParent(None)
            le.parent() and le.parent().deleteLater()
        self._result_lbl.setText("")
        self.search_changed.emit()

    # ── Query building ────────────────────────────────────────────────────────
    def _build_query(self) -> list:
        """
        Returns list of (operator, terms_set, ana_name|None).
        operator is 'AND'|'OR'|None (for first row).
        terms_set is a set of search strings (lowered) entered by the user.
        """
        parts = []
        for op_cb, le, ana_cb in self._rows:
            text = le.text().strip()
            if not text:
                continue
            op = op_cb.currentText() if op_cb else None
            ana = ana_cb.currentText() if ana_cb else None
            # Support comma-separated terms within one row → treated as OR within that cell
            cell_terms = [t.strip() for t in text.split(",") if t.strip()]
            parts.append((op, cell_terms, ana))
        return parts

    def _obj_matches_terms(self, obj: dict, cell_terms: list) -> bool:
        """True if any term in cell_terms matches any searchable term of obj."""
        obj_terms = _obj_all_terms(obj)
        for q in cell_terms:
            q_low = q.lower()
            for ot in obj_terms:
                if q_low in ot.lower():
                    return True
        return False

    def _article_text(self, art: dict) -> str:
        parts = []
        if art.get("abstract"):  parts.append(art["abstract"])
        if art.get("raw_text"):  parts.append(art["raw_text"])
        return " ".join(parts) or art.get("title", "")

    def _matching_objs_for_part(self, cell_terms: list, ana_name) -> list:
        """Return list of object dicts that match the cell_terms."""
        objs = self._objects_for(ana_name)
        return [o for o in objs if self._obj_matches_terms(o, cell_terms)]

    # ── Public API ────────────────────────────────────────────────────────────
    def is_active(self) -> bool:
        """True if at least one row has text."""
        return any(le.text().strip() for _, le, _ in self._rows)

    def matching_article_ids(self, articles: list) -> set:
        """
        Single-analysis mode.
        Returns the set of article IDs from `articles` that match the query.
        """
        parts = self._build_query()
        if not parts:
            return {a["id"] for a in articles}   # no filter → all

        # For each part, find matching objects → their terms → articles that contain them
        part_art_sets = []
        for (op, cell_terms, _) in parts:
            matched_objs = self._matching_objs_for_part(cell_terms, None)
            if not matched_objs:
                # Also try direct text match against title/abstract
                matched_ids = {
                    a["id"] for a in articles
                    if any(
                        q.lower() in (a.get("title","") + " " + (a.get("abstract","") or "")).lower()
                        for q in cell_terms
                    )
                }
            else:
                all_obj_terms = []
                for o in matched_objs:
                    all_obj_terms.extend(_obj_all_terms(o))
                matched_ids = {
                    a["id"] for a in articles
                    if any(_term_matches(t, self._article_text(a)) for t in all_obj_terms)
                }
            part_art_sets.append((op, matched_ids))

        # Combine with AND/OR
        result = part_art_sets[0][1]
        for op, ids in part_art_sets[1:]:
            if op == "AND":
                result = result & ids
            else:
                result = result | ids

        n = len(result)
        total = len(articles)
        if n == 0:
            self._result_lbl.setStyleSheet(
                f"font-size:8pt;color:{COLORS['accent_rose']};"
                "background:transparent;border:none;"
            )
            self._result_lbl.setText("No results found")
        else:
            self._result_lbl.setStyleSheet(
                f"font-size:8pt;color:{COLORS['accent_teal']};"
                "background:transparent;border:none;"
            )
            self._result_lbl.setText(f"{n} / {total} articles")
        return result

    def matching_pool_keys(self, pool: dict) -> set:
        """
        Multi-analysis mode (Combine).
        Returns the set of pool article keys that match the query.
        pool["articles"] = {key: {title, year, journal, text}}
        """
        parts = self._build_query()
        if not parts:
            return set(pool.get("articles", {}).keys())

        articles_pool = pool.get("articles", {})

        part_key_sets = []
        for (op, cell_terms, ana_name) in parts:
            matched_objs = self._matching_objs_for_part(cell_terms, ana_name)
            if not matched_objs:
                matched_keys = {
                    k for k, art in articles_pool.items()
                    if any(
                        q.lower() in (art.get("text","") + art.get("title","")).lower()
                        for q in cell_terms
                    )
                }
            else:
                all_obj_terms = []
                for o in matched_objs:
                    all_obj_terms.extend(_obj_all_terms(o))
                matched_keys = {
                    k for k, art in articles_pool.items()
                    if any(_term_matches(t, art.get("text","") or art.get("title",""))
                           for t in all_obj_terms)
                }
            part_key_sets.append((op, matched_keys))

        result = part_key_sets[0][1]
        for op, keys in part_key_sets[1:]:
            if op == "AND":
                result = result & keys
            else:
                result = result | keys

        n = len(result)
        total = len(articles_pool)
        if n == 0:
            self._result_lbl.setStyleSheet(
                f"font-size:8pt;color:{COLORS['accent_rose']};"
                "background:transparent;border:none;"
            )
            self._result_lbl.setText("No results found")
        else:
            self._result_lbl.setStyleSheet(
                f"font-size:8pt;color:{COLORS['accent_teal']};"
                "background:transparent;border:none;"
            )
            self._result_lbl.setText(f"{n} / {total} articles")
        return result



# ── ARTICLE CARD (list item widget) ──────────────────────────────────────────
class ArticleCard(QWidget):
    def __init__(self, article: dict, citation_count: int = 0):
        super().__init__()
        self.article_id = article["id"]
        self._build(article, citation_count)

    def _build(self, a: dict, cit_count: int):
        self.setStyleSheet("background: transparent; border: none;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(4)

        # Title row
        top = QHBoxLayout()
        title = QLabel(a.get("title","Untitled"))
        title.setStyleSheet(f"font-weight: 600; font-size: 9pt; color: {COLORS['text_primary']}; background: transparent; border: none;")
        title.setWordWrap(True)
        top.addWidget(title, 1)

        if cit_count > 0:
            badge = QLabel(f"  {cit_count} objects  ")
            badge.setStyleSheet(f"""
                background: {COLORS['accent_blue']}18;
                color: {COLORS['accent_blue']};
                border: 1px solid {COLORS['accent_blue']}44;
                border-radius: 8px;
                padding: 1px 6px;
                font-size: 8pt;
                font-weight: 600;
            """)
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedHeight(20)
            top.addWidget(badge)
        outer.addLayout(top)

        # Authors + Year + Journal
        authors = a.get("authors","")
        year    = a.get("year","")
        journal = a.get("journal","")
        parts = []
        if authors: parts.append(authors[:60] + ("…" if len(authors)>60 else ""))
        if year:    parts.append(str(year))
        if journal: parts.append(journal)
        meta_line = " · ".join(parts)
        if meta_line:
            meta = QLabel(meta_line)
            meta.setStyleSheet(f"font-size: 8pt; color: {COLORS['text_secondary']}; background: transparent; border: none;")
            outer.addWidget(meta)

        # DOI
        doi = a.get("doi","")
        if doi:
            doi_lbl = QLabel(f"DOI: {doi}")
            doi_lbl.setStyleSheet(f"font-size: 7pt; color: {COLORS['text_muted']}; background: transparent; border: none;")
            outer.addWidget(doi_lbl)

    def update_badge(self, cit_count: int):
        pass  # full refresh handled by module


# ── MAIN MODULE ───────────────────────────────────────────────────────────────
class MiningModule(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self._selected_article_id = None
        self._exclude_refs = True           # default: ignore reference sections
        self._excluded_sections: set = set()  # section keys to exclude
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Page header
        hdr_bar = QWidget()
        hdr_bar.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        hdr_bar.setFixedHeight(60)
        hdr_lay = QHBoxLayout(hdr_bar)
        hdr_lay.setContentsMargins(20, 0, 20, 0)

        title = QLabel("Article Mining")
        title.setStyleSheet(f"font-size: 15pt; font-weight: 700; color: {COLORS['text_primary']}; background: transparent; border: none;")
        sub = QLabel("Library of articles · detect object citations")
        sub.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_secondary']}; background: transparent; border: none;")
        ts = QVBoxLayout(); ts.setSpacing(1); ts.addWidget(title); ts.addWidget(sub)
        hdr_lay.addLayout(ts)
        hdr_lay.addStretch()

        btn_add_pdf  = make_btn("⬆  Add PDF(s)", primary=True)
        btn_add_man  = make_btn("＋  Add Manually")
        btn_scan     = make_btn("🔍  Scan Selected")
        btn_scan_all = make_btn("🔍  Scan All")
        btn_add_pdf.setToolTip(
            "Import one or more PDF files into this Analysis.\n"
            "SLDM will index their text for extraction."
        )
        btn_add_man.setToolTip(
            "Add an article entry manually (title, authors, DOI, etc.)\n"
            "without uploading a PDF."
        )
        btn_scan.setToolTip(
            "Run the extraction engine on the selected article(s).\n"
            "Looks for Object mentions, parameters and values."
        )
        btn_scan_all.setToolTip(
            "Run extraction on ALL articles not yet scanned.\n"
            "May take a while for large collections."
        )
        btn_add_pdf.clicked.connect(self._add_pdfs)
        btn_add_man.clicked.connect(self._add_manually)
        btn_scan.clicked.connect(self._scan_selected)
        btn_scan_all.clicked.connect(self._scan_all)

        # Toggle: exclude reference section from scan
        self._btn_excl_refs = make_btn("📚  Skip References: ON", primary=False)
        self._btn_excl_refs.setToolTip(
            "When ON, text after the References / Bibliography heading is ignored during scanning.\n"
            "Turn OFF if your articles keep references in the middle or use non-standard headings."
        )
        self._btn_excl_refs.setCheckable(True)
        self._btn_excl_refs.setChecked(True)
        self._btn_excl_refs.clicked.connect(self._toggle_exclude_refs)
        self._update_refs_btn_style()

        # Section filter button — opens the modular section exclusion panel
        self._btn_section_filter = make_btn("🗂  Section Filters")
        self._btn_section_filter.setToolTip(
            "Choose which article sections (Introduction, Methods, Results, etc.)\n"
            "to EXCLUDE from object detection scanning."
        )
        self._btn_section_filter.clicked.connect(self._open_section_filter_dialog)
        self._update_section_filter_btn_style()

        for b in [btn_add_pdf, btn_add_man, btn_scan, btn_scan_all,
                  self._btn_excl_refs, self._btn_section_filter]:
            hdr_lay.addWidget(b)
        root.addWidget(hdr_bar)

        # ── Stats
        stats_bar = QWidget()
        stats_bar.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        stats_lay = QHBoxLayout(stats_bar)
        stats_lay.setContentsMargins(20, 0, 20, 10)
        self.stat_arts  = StatCard("Articles",   "0", COLORS["accent_blue"],   "📄")
        self.stat_cits  = StatCard("Citations",  "0", COLORS["accent_teal"],   "📌")
        self.stat_objs  = StatCard("Objects Found","0",COLORS["accent_amber"], "🔬")
        self.stat_years = StatCard("Year Range", "—", COLORS["accent_violet"], "📅")
        for s in [self.stat_arts, self.stat_cits, self.stat_objs, self.stat_years]:
            stats_lay.addWidget(s)
        root.addWidget(stats_bar)

        # ── Main splitter: article list (left) | detail panel (right)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setStyleSheet(f"QSplitter::handle {{ background: {COLORS['border']}; width: 1px; }}")
        root.addWidget(splitter)

        # LEFT: article list
        left = QWidget()
        left.setStyleSheet(f"background: {COLORS['bg_secondary']}; border: none;")
        left.setMinimumWidth(280)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)

        # Search + sort bar
        search_bar = QWidget()
        search_bar.setStyleSheet(f"background: {COLORS['bg_secondary']}; border-bottom: 1px solid {COLORS['border']};")
        search_bar.setFixedHeight(44)
        sb_lay = QHBoxLayout(search_bar)
        sb_lay.setContentsMargins(10, 0, 10, 0)
        self.search = SearchBar("Search articles…")
        self.search.textChanged.connect(self._filter_list)
        sb_lay.addWidget(self.search)
        left_lay.addWidget(search_bar)

        # List
        self.article_list = QListWidget()
        self.article_list.setStyleSheet(f"""
            QListWidget {{
                background: {COLORS['bg_secondary']};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                border-bottom: 1px solid {COLORS['border']};
                padding: 0;
            }}
            QListWidget::item:selected {{
                background: {COLORS['accent_blue']}18;
                border-left: 2px solid {COLORS['accent_blue']};
            }}
            QListWidget::item:hover:!selected {{
                background: {COLORS['bg_hover']};
            }}
        """)
        self.article_list.currentItemChanged.connect(self._on_article_selected)
        self.article_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.article_list.customContextMenuRequested.connect(self._context_menu)
        left_lay.addWidget(self.article_list)

        splitter.addWidget(left)

        # RIGHT: detail panel
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet(f"QScrollArea {{ background: {COLORS['bg_primary']}; border: none; }}")

        self.detail_panel = QWidget()
        self.detail_panel.setStyleSheet(f"background: {COLORS['bg_primary']}; border: none;")
        self.detail_layout = QVBoxLayout(self.detail_panel)
        self.detail_layout.setContentsMargins(20, 16, 20, 20)
        self.detail_layout.setSpacing(14)
        self.detail_layout.addWidget(EmptyState("📄", "Select an article", "Click an article in the list to see details"))
        self.detail_layout.addStretch()

        right_scroll.setWidget(self.detail_panel)
        splitter.addWidget(right_scroll)
        splitter.setSizes([340, 900])

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFixedHeight(4)
        root.addWidget(self.progress)

    # ── REFRESH ───────────────────────────────────────────────────────────────
    def refresh(self):
        # Single DB round-trip shared between list and stats
        articles  = self.db.get_articles()
        citations = self.db.get_citations()
        self._populate_list(articles, citations)
        self._update_stats(articles, citations)

    def _populate_list(self, articles=None, citations=None):
        if articles  is None: articles  = self.db.get_articles()
        if citations is None: citations = self.db.get_citations()

        # Build per-article citation count in-memory — no extra DB call
        art_cit = {}
        for c in citations:
            aid = c["article_id"]
            art_cit[aid] = art_cit.get(aid, 0) + 1

        self.article_list.clear()
        query = self.search.text().lower() if hasattr(self, 'search') else ""
        for art in articles:
            if query and query not in art["title"].lower() and query not in (art.get("authors","") or "").lower():
                continue
            item = QListWidgetItem()
            card = ArticleCard(art, art_cit.get(art["id"], 0))
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.UserRole, art["id"])
            self.article_list.addItem(item)
            self.article_list.setItemWidget(item, card)

    def _filter_list(self, text):
        self._populate_list()

    def _update_stats(self, articles=None, citations=None):
        if articles  is None: articles  = self.db.get_articles()
        if citations is None: citations = self.db.get_citations()
        years = [a["year"] for a in articles if a.get("year")]
        yr = f"{min(years)}–{max(years)}" if years else "—"
        unique_objs = len({c["object_name"] for c in citations})
        self.stat_arts.set_value(len(articles))
        self.stat_cits.set_value(len(citations))
        self.stat_objs.set_value(unique_objs)
        self.stat_years.set_value(yr)

    # ── DETAIL PANEL ──────────────────────────────────────────────────────────
    def _on_article_selected(self, current, previous):
        if not current: return
        aid = current.data(Qt.UserRole)
        self._selected_article_id = aid
        self._show_detail(aid)

    def _show_detail(self, aid: str):
        # Clear
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        art = self.db.get_article(aid)
        if not art:
            self.detail_layout.addWidget(EmptyState("📄","Not found",""))
            return

        # Title + actions row
        top = QHBoxLayout()
        title = QLabel(art["title"])
        title.setStyleSheet(f"font-size: 12pt; font-weight: 700; color: {COLORS['text_primary']}; background: transparent; border: none;")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        btn_edit = make_btn("✏  Edit")
        btn_del  = make_btn("🗑", danger=True)
        btn_scan = make_btn("🔍  Scan", primary=True)
        btn_edit.clicked.connect(lambda: self._edit_article(aid))
        btn_del.clicked.connect(lambda: self._delete_article(aid))
        btn_scan.clicked.connect(lambda: self._scan_article(aid))
        for b in [btn_edit, btn_del, btn_scan]: top.addWidget(b)
        self.detail_layout.addLayout(top)

        # Metadata grid
        meta_frame = QFrame()
        meta_frame.setStyleSheet(f"background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; border-radius: 8px;")
        mf_lay = QGridLayout(meta_frame)
        mf_lay.setContentsMargins(16, 12, 16, 12)
        mf_lay.setSpacing(8)

        fields = [
            ("Authors",  art.get("authors","") or "—"),
            ("Year",     str(art.get("year","")) or "—"),
            ("Journal",  art.get("journal","") or "—"),
            ("Volume/Issue", f"{art.get('volume','')} / {art.get('issue','')}".strip("/ ") or "—"),
            ("Pages",    art.get("pages","") or "—"),
            ("DOI",      art.get("doi","") or "—"),
            ("Keywords", art.get("keywords","") or "—"),
        ]
        for i, (lbl_txt, val_txt) in enumerate(fields):
            col = (i % 2) * 2
            row = i // 2
            lbl = QLabel(lbl_txt + ":")
            lbl.setStyleSheet(f"font-size: 8pt; font-weight: 600; color: {COLORS['text_muted']}; background: transparent; border: none; text-transform: uppercase;")
            val = QLabel(val_txt)
            val.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_primary']}; background: transparent; border: none;")
            val.setWordWrap(True)
            mf_lay.addWidget(lbl, row, col)
            mf_lay.addWidget(val, row, col+1)
        self.detail_layout.addWidget(meta_frame)

        # Abstract
        if art.get("abstract","").strip():
            ab_panel = Panel("Abstract", "📝")
            ab_txt = QLabel(art["abstract"])
            ab_txt.setWordWrap(True)
            ab_txt.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_secondary']}; background: transparent; border: none; line-height: 1.5;")
            ab_panel.add_body_widget(ab_txt)
            self.detail_layout.addWidget(ab_panel)

        # Citations found
        cits = [c for c in self.db.get_citations() if c["article_id"] == aid]
        cit_panel = Panel(f"Objects Detected  ({len(cits)})", "🔬")
        if cits:
            # Fetch all objects once into a lookup dict — avoids O(N×cits) DB calls
            objects_by_name = {o["name"]: o for o in self.db.get_objects()}

            flow = QWidget()
            flow.setStyleSheet("background: transparent; border: none;")
            fl = QHBoxLayout(flow)
            fl.setContentsMargins(0,0,0,0)
            fl.setSpacing(6)
            fl.setAlignment(Qt.AlignLeft)
            file_path = art.get("file_path", "")
            for c in cits:
                obj_name = c['object_name']
                obj_data = objects_by_name.get(obj_name)
                syns = _parse_syns(obj_data["synonyms"]) if obj_data else []
                terms = [obj_name] + syns

                btn = QPushButton(f"  {obj_name}  ")
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {COLORS['accent_blue']}15;
                        color: {COLORS['accent_blue']};
                        border: 1px solid {COLORS['accent_blue']}44;
                        border-radius: 10px;
                        padding: 2px 4px;
                        font-size: 8pt;
                        font-weight: 600;
                    }}
                    QPushButton:hover {{
                        background: {COLORS['accent_blue']}35;
                        border-color: {COLORS['accent_blue']}99;
                    }}
                """)
                btn.setCursor(Qt.PointingHandCursor)

                # Left click: open PDF viewer (if available)
                if file_path and os.path.isfile(file_path):
                    btn.setToolTip(f"Click: open PDF  ·  Right-click: edit '{obj_name}'")
                    btn.clicked.connect(lambda checked, fp=file_path, t=terms, n=obj_name:
                        self._open_pdf_viewer(fp, t, n))
                else:
                    btn.setToolTip(f"Right-click to edit '{obj_name}'")

                # Right click: edit object — always available
                btn.setContextMenuPolicy(Qt.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, n=obj_name, b=btn:
                        self._compound_context_menu(pos, n, b, aid)
                )
                fl.addWidget(btn)
            fl.addStretch()
            cit_panel.add_body_widget(flow)
        else:
            cit_panel.add_body_widget(EmptyState("🔍","No objects detected yet","Click 'Scan' to detect objects in this article"))
        self.detail_layout.addWidget(cit_panel)

        # File info
        if art.get("file_path",""):
            fp = QLabel(f"📎  {art['file_path']}")
            fp.setStyleSheet(f"font-size: 8pt; color: {COLORS['text_muted']}; background: transparent; border: none;")
            self.detail_layout.addWidget(fp)

        self.detail_layout.addStretch()

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

    def _get_scan_text(self, raw: str) -> str:
        """Return the text to be scanned, applying all active exclusion filters."""
        if self._exclude_refs:
            raw = _strip_references(raw)
        if self._excluded_sections:
            raw = _strip_sections(raw, self._excluded_sections)
        return raw

    def _open_pdf_viewer(self, pdf_path: str, terms: list, object_name: str):
        viewer = PdfViewerWindow(self, pdf_path, terms, object_name)
        viewer.show()

    def _compound_context_menu(self, pos, obj_name: str, btn: QPushButton, aid: str):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{COLORS['bg_secondary']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:4px;}}"
            f"QMenu::item{{padding:7px 20px;color:{COLORS['text_primary']};font-size:9pt;}}"
            f"QMenu::item:selected{{background:{COLORS['bg_hover']};}}"
            f"QMenu::separator{{height:1px;background:{COLORS['border']};margin:4px 8px;}}"
        )
        title = menu.addAction(f"🔬  {obj_name}")
        title.setEnabled(False)
        menu.addSeparator()
        menu.addAction("✏  Edit object (name, synonyms…)",
                       lambda: self._edit_object_from_citation(obj_name, aid))
        menu.addSeparator()
        # Only show PDF option if file exists
        art = self.db.get_article(aid)
        fp = art.get("file_path", "") if art else ""
        if fp and os.path.isfile(fp):
            obj_data = self.db.get_object_by_name(obj_name)
            syns = _parse_syns(obj_data["synonyms"]) if obj_data else []
            terms = [obj_name] + syns
            menu.addAction("📄  Open PDF with highlights",
                           lambda: self._open_pdf_viewer(fp, terms, obj_name))
        menu.exec_(btn.mapToGlobal(pos))

    def _edit_object_from_citation(self, obj_name: str, aid: str):
        """Open the ObjectDialog to edit an object directly from the citation badge."""
        obj_data = self.db.get_object_by_name(obj_name)
        if not obj_data:
            QMessageBox.warning(self, "Not found",
                f"Object '{obj_name}' not found in the Object List.")
            return
        syns = _parse_syns(obj_data["synonyms"])
        dlg = ObjectDialog(self, defaults={
            "name":        obj_data["name"],
            "category":    obj_data["category"],
            "subcategory": obj_data["subcategory"],
            "synonyms":    syns,
            "notes":       obj_data["notes"],
        })
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            self.db.update_object(obj_data["id"], **d)
            # Refresh detail panel to reflect any name change
            self._show_detail(aid)
            self.data_changed.emit()
            Toast.show_toast(self, f"'{d['name']}' updated", "success")

    # ── ACTIONS ───────────────────────────────────────────────────────────────
    def _add_pdfs(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add PDFs", "", "PDF Files (*.pdf);;Text Files (*.txt);;All Files (*)")
        if not paths: return
        objects = self.db.get_objects()
        self.progress.setVisible(True)
        self.progress.setRange(0, len(paths))
        added_ids = []
        for i, path in enumerate(paths):
            self.progress.setValue(i + 1)
            # Create article with filename as title
            name = os.path.splitext(os.path.basename(path))[0]
            # Try to extract text
            text = ""
            try:
                import fitz
                doc = fitz.open(path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
            except:
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                except: pass
            aid = self.db.add_article(title=name, file_path=path, raw_text=text)
            added_ids.append((aid, text))

            # Auto DOI detection: find DOI in extracted text and fetch metadata
            if text:
                doi_match = re.search(r'\b(10\.\d{4,}/[^\s"\'<>]+)', text)
                if doi_match:
                    doi_found = doi_match.group(1).rstrip(".,;)")
                    try:
                        meta = fetch_doi_metadata(doi_found)
                        # Only fill fields; keep file_path and raw_text
                        self.db.update_article(aid,
                            title    = meta["title"] or name,
                            authors  = meta["authors"],
                            year     = meta["year"],
                            journal  = meta["journal"],
                            volume   = meta["volume"],
                            issue    = meta["issue"],
                            pages    = meta["pages"],
                            doi      = meta["doi"],
                            abstract = meta["abstract"],
                            keywords = meta["keywords"],
                        )
                    except Exception:
                        pass  # silently ignore if DOI fetch fails
            QApplication.processEvents()

        # Bug 1 fix: auto-scan newly added PDFs if objects are defined
        if objects and added_ids:
            self.progress.setRange(0, len(added_ids))
            total_cit = 0
            for i, (aid, raw) in enumerate(added_ids):
                self.progress.setValue(i + 1)
                scan_text = self._get_scan_text(raw)
                if not scan_text:
                    continue
                self.db.delete_citations_for_article(aid)
                for obj in objects:
                    syns = _parse_syns(obj["synonyms"])
                    terms = [obj["name"]] + syns
                    if _any_term_matches(terms, scan_text):
                        art = self.db.get_article(aid)
                        self.db.add_citation(obj["id"], obj["name"], aid, art["title"] if art else "", art.get("year") if art else None)
                        total_cit += 1
                QApplication.processEvents()

        self.progress.setVisible(False)
        self.refresh()
        self.data_changed.emit()
        if objects and added_ids:
            Toast.show_toast(self, f"Added {len(paths)} article(s) · {total_cit} objects detected", "success")
        else:
            Toast.show_toast(self, f"Added {len(paths)} article(s)", "success")

    def _add_manually(self):
        dlg = ArticleDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            self.db.add_article(**d)
            self.refresh()
            self.data_changed.emit()
            Toast.show_toast(self, "Article added", "success")

    def _edit_article(self, aid: str):
        art = self.db.get_article(aid)
        if not art: return
        dlg = ArticleDialog(self, defaults=art)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            self.db.update_article(aid, **d)
            self.refresh()
            self._show_detail(aid)
            self.data_changed.emit()
            Toast.show_toast(self, "Article updated", "success")

    def _delete_article(self, aid: str):
        reply = QMessageBox.question(self, "Delete", "Delete this article and all its citations?",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return
        self.db.delete_article(aid)
        self._selected_article_id = None
        self.refresh()
        self.data_changed.emit()
        # Clear detail panel
        while self.detail_layout.count():
            item = self.detail_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.detail_layout.addWidget(EmptyState("📄","Select an article",""))
        Toast.show_toast(self, "Article deleted", "info")

    def _scan_article(self, aid: str):
        """Detect objects in a single article."""
        art = self.db.get_article(aid)
        if not art: return
        raw = self._get_scan_text(art.get("raw_text","") or "")
        if not raw:
            QMessageBox.information(self, "Scan", "No text content available for this article.\nImport as PDF or paste the abstract/text when editing.")
            return
        objects = self.db.get_objects()
        count = 0
        self.db.delete_citations_for_article(aid)
        for obj in objects:
            syns = _parse_syns(obj["synonyms"])
            terms = [obj["name"]] + syns
            if _any_term_matches(terms, raw):
                self.db.add_citation(obj["id"], obj["name"], aid, art["title"], art.get("year"))
                count += 1
        self.refresh()
        self._show_detail(aid)
        self.data_changed.emit()
        Toast.show_toast(self, f"Found {count} objects in article", "success" if count else "info")

    def _on_scan_all_done(self, total_cit: int):
        self.progress.setVisible(False)
        self.refresh()
        self.data_changed.emit()
        Toast.show_toast(self, f"Scan complete — {total_cit} citations found", "success")

    def _scan_selected(self):
        if self._selected_article_id:
            self._scan_article(self._selected_article_id)

    def _scan_all(self):
        articles = self.db.get_articles()
        objects  = self.db.get_objects()
        if not articles:
            Toast.show_toast(self, "No articles in library", "info"); return
        if not objects:
            Toast.show_toast(self, "No objects defined in Object List", "info"); return

        # Bug 2 fix: run scan in a background thread so the UI never freezes
        self.progress.setVisible(True)
        self.progress.setRange(0, len(articles))

        self._scan_thread = QThread()
        self._scan_worker = _ScanAllWorker(self.db, articles, objects,
                                           self._exclude_refs,
                                           self._excluded_sections)
        self._scan_worker.moveToThread(self._scan_thread)

        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self.progress.setValue)
        self._scan_worker.finished.connect(self._on_scan_all_done)
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)

        self._scan_thread.start()

    def _context_menu(self, pos):
        from PyQt5.QtWidgets import QMenu
        item = self.article_list.itemAt(pos)
        if not item: return
        aid = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.setStyleSheet(f"QMenu {{ background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}; }} QMenu::item {{ padding: 6px 20px; }} QMenu::item:selected {{ background: {COLORS['bg_hover']}; }}")
        menu.addAction("✏  Edit",         lambda: self._edit_article(aid))
        menu.addAction("🔍  Scan",        lambda: self._scan_article(aid))
        menu.addSeparator()
        menu.addAction("🗑  Delete",      lambda: self._delete_article(aid))
        menu.exec_(self.article_list.viewport().mapToGlobal(pos))



# ── BACKGROUND SCAN WORKER ────────────────────────────────────────────────────
class _ScanAllWorker(QObject):
    """Runs article scanning on a background thread (fixes UI freeze bug)."""
    progress = pyqtSignal(int)       # current article index
    finished = pyqtSignal(int)       # total citations found

    def __init__(self, db, articles, objects, exclude_refs: bool = True,
                 excluded_sections: set = None):
        super().__init__()
        self.db = db
        self.articles = articles
        self.objects = objects
        self.exclude_refs = exclude_refs
        self.excluded_sections = excluded_sections or set()

    @pyqtSlot()
    def run(self):
        total_cit = 0
        for i, art in enumerate(self.articles):
            self.progress.emit(i + 1)
            raw = (art.get("raw_text", "") or "")
            if self.exclude_refs:
                raw = _strip_references(raw)
            if self.excluded_sections:
                raw = _strip_sections(raw, self.excluded_sections)
            if not raw:
                continue
            self.db.delete_citations_for_article(art["id"])
            for obj in self.objects:
                syns = _parse_syns(obj["synonyms"])
                terms = [obj["name"]] + syns
                if _any_term_matches(terms, raw):
                    self.db.add_citation(obj["id"], obj["name"], art["id"], art["title"], art.get("year"))
                    total_cit += 1
        self.finished.emit(total_cit)


# ── SECTION FILTER DIALOG ────────────────────────────────────────────────────
class SectionFilterDialog(QDialog):
    """
    Lets the user pick which article sections to EXCLUDE from scanning.
    Each section (Introduction, Methods, Results, Discussion, Conclusion) is
    shown as a toggle card.  The dialog also previews which heading keywords
    will be matched for each selected section.
    """

    def __init__(self, parent=None, current_excluded: set = None):
        super().__init__(parent)
        self.setWindowTitle("Section Filters — Scan Exclusions")
        self.setMinimumWidth(560)
        self.setMinimumHeight(460)
        self._checks: dict = {}          # key → QCheckBox
        self._current = set(current_excluded or set())
        self._result: set = set(self._current)   # cached before widgets die
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(14)

        # Header
        h_lbl = QLabel("🗂  Section Filters")
        h_lbl.setStyleSheet(
            f"font-size: 13pt; font-weight: 700; color: {COLORS['text_primary']}; "
            f"background: transparent; border: none;")
        lay.addWidget(h_lbl)

        desc = QLabel(
            "Select the sections below to <b>exclude</b> them from object-detection scanning.\n"
            "Exclusions are applied on top of the 'Skip References' toggle."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 9pt; color: {COLORS['text_secondary']}; "
            f"background: transparent; border: none;")
        lay.addWidget(desc)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color: {COLORS['border']};")
        lay.addWidget(sep)

        # One card per section
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: transparent; }}")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(10)

        for key, sdef in SECTION_DEFS.items():
            card = QFrame()
            card.setStyleSheet(
                f"QFrame {{ background: {COLORS['bg_card']}; "
                f"border: 1px solid {COLORS['border']}; border-radius: 8px; }}"
            )
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(14, 10, 14, 10)
            card_lay.setSpacing(6)

            # Checkbox + label row
            row = QHBoxLayout()
            row.setSpacing(10)
            chk = QCheckBox()
            chk.setChecked(key in self._current)
            chk.setStyleSheet("QCheckBox { border: none; background: transparent; }")
            self._checks[key] = chk

            lbl = QLabel(f"{sdef['icon']}  <b>{sdef['label']}</b>")
            lbl.setStyleSheet(
                f"font-size: 10pt; color: {COLORS['text_primary']}; "
                f"background: transparent; border: none;")
            lbl.setTextFormat(Qt.RichText)

            # "Exclude" pill
            pill = QLabel("Exclude from scan")
            pill.setStyleSheet(
                f"font-size: 8pt; color: {COLORS['accent_violet']}; "
                f"background: {COLORS['accent_violet']}18; "
                f"border: 1px solid {COLORS['accent_violet']}44; "
                f"border-radius: 8px; padding: 1px 8px; font-weight: 600;")
            pill.setVisible(key in self._current)

            def _on_toggle(state, k=key, p=pill):
                p.setVisible(bool(state))
            chk.stateChanged.connect(_on_toggle)

            row.addWidget(chk)
            row.addWidget(lbl, 1)
            row.addWidget(pill)
            card_lay.addLayout(row)

            # Preview of matched headings (collapsed, first 6)
            sample_headings = sdef["headings"][:8]
            hint = QLabel("Matches: " + " · ".join(f'"{h}"' for h in sample_headings)
                          + ("  …" if len(sdef["headings"]) > 8 else ""))
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"font-size: 8pt; color: {COLORS['text_muted']}; "
                f"background: transparent; border: none; padding-left: 28px;")
            card_lay.addWidget(hint)

            inner_lay.addWidget(card)

        inner_lay.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        # Quick-select row
        quick = QHBoxLayout()
        btn_all  = make_btn("Select All")
        btn_none = make_btn("Clear All")
        btn_all.clicked.connect(self._select_all)
        btn_none.clicked.connect(self._clear_all)
        quick.addWidget(btn_all)
        quick.addWidget(btn_none)
        quick.addStretch()
        lay.addLayout(quick)

        # Action buttons
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = make_btn("Cancel")
        ok     = make_btn("Apply", primary=True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._apply_and_accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _apply_and_accept(self):
        # Cache the result NOW, while QCheckBox widgets are still alive
        self._result = {k for k, chk in self._checks.items() if chk.isChecked()}
        self.accept()

    def _select_all(self):
        for chk in self._checks.values():
            chk.setChecked(True)

    def _clear_all(self):
        for chk in self._checks.values():
            chk.setChecked(False)

    def get_excluded(self) -> set:
        # Always return the pre-cached result — never touch widgets after close
        return self._result


# ── ARTICLE DIALOG ────────────────────────────────────────────────────────────
class ArticleDialog(QDialog):
    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        self.setWindowTitle("Article")
        self.setMinimumWidth(560)
        self.setMinimumHeight(500)
        d = defaults or {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        title_lbl = QLabel("Add Article" if not defaults else "Edit Article")
        title_lbl.setStyleSheet(f"font-size: 12pt; font-weight: 700; color: {COLORS['text_primary']}; background: transparent; border: none;")
        layout.addWidget(title_lbl)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)
        lbl_s = f"color: {COLORS['text_secondary']}; font-size: 9pt; background: transparent;"

        self.f_title   = QLineEdit(d.get("title",""))
        self.f_authors = QLineEdit(d.get("authors",""))
        self.f_year    = QLineEdit(str(d.get("year","") or ""))
        self.f_journal = QLineEdit(d.get("journal",""))
        self.f_volume  = QLineEdit(d.get("volume",""))
        self.f_issue   = QLineEdit(d.get("issue",""))
        self.f_pages   = QLineEdit(d.get("pages",""))
        self.f_doi     = QLineEdit(d.get("doi",""))
        self.f_keywords= QLineEdit(d.get("keywords",""))

        # DOI fetch row — sits above the form fields
        doi_row = QHBoxLayout()
        doi_lbl = QLabel("DOI")
        doi_lbl.setStyleSheet(lbl_s)
        doi_lbl.setFixedWidth(90)
        doi_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._btn_fetch = make_btn("🌐  Fetch Metadata", primary=False)
        self._btn_fetch.setToolTip("Fetch title, authors, journal, etc. from Crossref using the DOI above")
        self._btn_fetch.clicked.connect(self._fetch_doi)
        self._fetch_status = QLabel("")
        self._fetch_status.setStyleSheet(f"font-size:8pt; color:{COLORS['text_muted']}; background:transparent; border:none;")
        doi_row.addWidget(doi_lbl)
        doi_row.addWidget(self.f_doi, 1)
        doi_row.addWidget(self._btn_fetch)
        doi_row.addWidget(self._fetch_status)
        layout.addLayout(doi_row)

        for lbl_txt, widget, ph in [
            ("Title *",     self.f_title,    "Article title"),
            ("Authors",     self.f_authors,  "Author1, Author2, …"),
            ("Year",        self.f_year,     "e.g. 2023"),
            ("Journal",     self.f_journal,  "Journal name"),
            ("Volume",      self.f_volume,   ""),
            ("Issue",       self.f_issue,    ""),
            ("Pages",       self.f_pages,    "e.g. 1–12"),
            ("Keywords",    self.f_keywords, "keyword1, keyword2"),
        ]:
            widget.setPlaceholderText(ph)
            lbl = QLabel(lbl_txt); lbl.setStyleSheet(lbl_s)
            form.addRow(lbl, widget)
        layout.addLayout(form)

        # Abstract
        ab_lbl = QLabel("Abstract"); ab_lbl.setStyleSheet(lbl_s)
        self.f_abstract = QTextEdit(d.get("abstract",""))
        self.f_abstract.setPlaceholderText("Paste or type the abstract here…")
        self.f_abstract.setFixedHeight(90)
        layout.addWidget(ab_lbl)
        layout.addWidget(self.f_abstract)

        # Paste raw text
        rt_lbl = QLabel("Full text / paste text for scanning")
        rt_lbl.setStyleSheet(f"font-size: 8pt; color: {COLORS['text_muted']}; background: transparent; border: none;")
        self.f_raw = QTextEdit(d.get("raw_text",""))
        self.f_raw.setPlaceholderText("Paste full article text here for object detection scanning…")
        self.f_raw.setFixedHeight(80)
        layout.addWidget(rt_lbl)
        layout.addWidget(self.f_raw)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = make_btn("Cancel"); ok = make_btn("Save", primary=True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._validate)
        btns.addWidget(cancel); btns.addWidget(ok)
        layout.addLayout(btns)

    def _fetch_doi(self):
        doi = self.f_doi.text().strip()
        if not doi:
            self._fetch_status.setText("Enter a DOI first")
            return
        self._btn_fetch.setEnabled(False)
        self._fetch_status.setText("Fetching…")
        QApplication.processEvents()

        # Run in background thread
        self._doi_thread = QThread()
        self._doi_worker = _DoiFetchWorker(doi)
        self._doi_worker.moveToThread(self._doi_thread)
        self._doi_thread.started.connect(self._doi_worker.run)
        self._doi_worker.finished.connect(self._on_doi_fetched)
        self._doi_worker.error.connect(self._on_doi_error)
        self._doi_worker.finished.connect(self._doi_thread.quit)
        self._doi_worker.error.connect(self._doi_thread.quit)
        self._doi_worker.finished.connect(self._doi_worker.deleteLater)
        self._doi_thread.finished.connect(self._doi_thread.deleteLater)
        self._doi_thread.start()

    def _on_doi_fetched(self, meta: dict):
        self._btn_fetch.setEnabled(True)
        # Fill only empty fields — don't overwrite what user typed
        if meta.get("title")    and not self.f_title.text().strip():
            self.f_title.setText(meta["title"])
        elif meta.get("title"):
            self.f_title.setText(meta["title"])   # always update title from DOI
        if meta.get("authors"):  self.f_authors.setText(meta["authors"])
        if meta.get("year"):     self.f_year.setText(str(meta["year"]))
        if meta.get("journal"):  self.f_journal.setText(meta["journal"])
        if meta.get("volume"):   self.f_volume.setText(meta["volume"])
        if meta.get("issue"):    self.f_issue.setText(meta["issue"])
        if meta.get("pages"):    self.f_pages.setText(meta["pages"])
        if meta.get("keywords"): self.f_keywords.setText(meta["keywords"])
        if meta.get("abstract") and not self.f_abstract.toPlainText().strip():
            self.f_abstract.setPlainText(meta["abstract"])
        self._fetch_status.setText("✔ Metadata filled")
        self._fetch_status.setStyleSheet(f"font-size:8pt; color:{COLORS['accent_teal']}; background:transparent; border:none;")

    def _on_doi_error(self, msg: str):
        self._btn_fetch.setEnabled(True)
        self._fetch_status.setText(f"✖ {msg}")
        self._fetch_status.setStyleSheet(f"font-size:8pt; color:#f43f5e; background:transparent; border:none;")

    def _validate(self):
        if not self.f_title.text().strip():
            self.f_title.setFocus(); return
        self.accept()

    def get_data(self) -> dict:
        yr = self.f_year.text().strip()
        return {
            "title":    self.f_title.text().strip(),
            "authors":  self.f_authors.text().strip(),
            "year":     int(yr) if yr.isdigit() else None,
            "journal":  self.f_journal.text().strip(),
            "volume":   self.f_volume.text().strip(),
            "issue":    self.f_issue.text().strip(),
            "pages":    self.f_pages.text().strip(),
            "doi":      self.f_doi.text().strip(),
            "keywords": self.f_keywords.text().strip(),
            "abstract": self.f_abstract.toPlainText().strip(),
            "raw_text": self.f_raw.toPlainText().strip(),
        }

