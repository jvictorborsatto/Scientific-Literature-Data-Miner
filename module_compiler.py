"""
SLDM — Module 4: Data Compiler  (v7)

Flow:
  1. Main window — list of loaded PDFs on the left
  2. Double-click PDF → PdfReaderDialog opens
       · Native PDF rendering via pypdfium2 (NOT rasterized upfront)
       · All pages in continuous scroll
       · "Select Region" → rubber-band drag → that region is captured as image
       · Multiple selections: Table A, B, C…
       · "Advance →" opens TableReviewDialog
  3. TableReviewDialog — rename, delete, unify (append or join), run OCR
  4. Tables appear in main window right panel — view, edit, export
"""

import os, csv, json
from collections import defaultdict

from PIL import Image

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QLineEdit, QFileDialog, QMessageBox, QAbstractItemView,
    QSplitter, QFrame, QComboBox, QScrollArea,
    QListWidget, QListWidgetItem, QGridLayout, QApplication,
    QInputDialog, QProgressDialog, QRubberBand, QCheckBox,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QObject, QRect, QPoint, QSize
from PyQt5.QtGui import QColor, QFont, QPixmap, QPainter, QPen, QImage, QCursor

from core.database import Database
from core.widgets import make_btn, Toast
from core.theme import COLORS


# ── style helpers ──────────────────────────────────────────────────────────────
TABLE_STYLE = f"""
QTableWidget {{
    background:{COLORS['bg_secondary']};
    alternate-background-color:{COLORS['bg_tertiary']};
    color:{COLORS['text_primary']};
    gridline-color:{COLORS['border']};
    border:none; font-size:9pt;
    selection-background-color:{COLORS['accent_blue']}33;
}}
QHeaderView::section {{
    background:{COLORS['bg_primary']};
    color:{COLORS['text_secondary']};
    font-size:8pt; font-weight:700;
    padding:5px 8px; border:none;
    border-bottom:1px solid {COLORS['border']};
    border-right:1px solid  {COLORS['border']};
}}
QTableWidget::item {{ padding:4px 8px; border:none; }}
"""
CB_STYLE = (
    f"QComboBox{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
    f"border-radius:4px;color:{COLORS['text_primary']};padding:3px 8px;font-size:9pt;}}"
    f"QComboBox::drop-down{{border:none;}}"
    f"QComboBox QAbstractItemView{{background:{COLORS['bg_secondary']};"
    f"border:1px solid {COLORS['border']};"
    f"selection-background-color:{COLORS['bg_hover']};"
    f"color:{COLORS['text_primary']};}}"
)
LIST_STYLE = f"""
QListWidget {{
    background:{COLORS['bg_secondary']};
    border:1px solid {COLORS['border']}; border-radius:4px;
    color:{COLORS['text_primary']}; font-size:9pt; outline:none;
}}
QListWidget::item {{
    padding:7px 10px; border-bottom:1px solid {COLORS['border']};
}}
QListWidget::item:selected {{
    background:{COLORS['accent_blue']}22; color:{COLORS['accent_blue']};
}}
QListWidget::item:hover:!selected {{ background:{COLORS['bg_hover']}; }}
"""
SEARCH_STYLE = (
    f"QLineEdit{{background:{COLORS['bg_tertiary']};border:1px solid {COLORS['border']};"
    f"border-radius:4px;color:{COLORS['text_primary']};padding:4px 8px;font-size:9pt;}}"
)

def _lbl(text, muted=False):
    l = QLabel(text)
    l.setStyleSheet(
        f"font-size:8.5pt;color:{COLORS['text_muted' if muted else 'text_secondary']};"
        "background:transparent;border:none;"
    )
    return l

def _sec(text):
    l = QLabel(text)
    l.setStyleSheet(
        f"font-size:7.5pt;font-weight:700;color:{COLORS['text_muted']};"
        "text-transform:uppercase;letter-spacing:1px;"
        "background:transparent;border:none;margin-top:6px;"
    )
    return l

def _next_label(i: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if i < 26: return f"Table {letters[i]}"
    return f"Table {letters[i//26-1]}{letters[i%26]}"


# ══════════════════════════════════════════════════════════════════════════════
# PDF rendering helpers  (pypdfium2)
# ══════════════════════════════════════════════════════════════════════════════
RENDER_DPI = 150    # display DPI — good balance of quality vs speed
CROP_DPI   = 250    # higher DPI for the cropped region sent to OCR


def _render_page_to_pixmap(pdf_doc, page_idx: int, scale: float) -> tuple:
    """
    Render one PDF page to a QPixmap.
    Returns (QPixmap, page_width_pt, page_height_pt).
    """
    page = pdf_doc[page_idx]
    w_pt = page.get_width()
    h_pt = page.get_height()
    bitmap = page.render(scale=scale * RENDER_DPI / 72.0)
    pil = bitmap.to_pil()
    page.close()
    return _pil_to_pixmap(pil), w_pt, h_pt


def _crop_page_to_pil(pdf_doc, page_idx: int,
                      x_pt: float, y_pt: float,
                      w_pt: float, h_pt: float) -> Image.Image:
    """
    Render the full page at high DPI, then PIL-crop the selected region.
    x_pt, y_pt are top-left in PDF-point coords (origin top-left of page).
    w_pt, h_pt are width and height in PDF points.
    """
    page   = pdf_doc[page_idx]
    pw_pt  = page.get_width()
    ph_pt  = page.get_height()
    s      = CROP_DPI / 72.0

    # Render full page at high DPI
    bitmap = page.render(scale=s)
    full   = bitmap.to_pil()
    page.close()

    # Convert PDF-point coords (top-left origin) → pixel coords
    px_per_pt = CROP_DPI / 72.0
    x0 = int(max(0,        x_pt          * px_per_pt))
    y0 = int(max(0,        y_pt          * px_per_pt))
    x1 = int(min(full.width,  (x_pt + w_pt) * px_per_pt))
    y1 = int(min(full.height, (y_pt + h_pt) * px_per_pt))

    if x1 - x0 < 4 or y1 - y0 < 4:
        return full   # fallback: return full page

    return full.crop((x0, y0, x1, y1))


def _pil_to_pixmap(pil_img: Image.Image) -> QPixmap:
    img = pil_img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg)


def _pil_to_qimage(pil_img: Image.Image) -> QImage:
    img = pil_img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    return QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)


# ══════════════════════════════════════════════════════════════════════════════
# Native PDF text extraction  (pypdfium2 — no OCR needed)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_region_text(pdf_doc, page_idx: int,
                         x_pt: float, y_pt: float,
                         w_pt: float, h_pt: float) -> list:
    """
    Extract all characters with their bounding boxes from the selected region.
    Coordinates are in PDF points, origin top-left.
    Returns list of {"text", "x", "y", "w", "h"} — each char, in PDF-point space.
    """
    page    = pdf_doc[page_idx]
    page_h  = page.get_height()
    textpg  = page.get_textpage()

    # pypdfium2 uses bottom-left origin for text extraction
    left   = x_pt
    bottom = page_h - (y_pt + h_pt)
    right  = x_pt + w_pt
    top    = page_h - y_pt

    chars = []
    n = textpg.count_chars()
    for i in range(n):
        cx1, cy1, cx2, cy2 = textpg.get_charbox(i, loose=False)
        # Filter: keep only chars within the selection bounding box
        # (cy1 is bottom in PDF coords)
        if cx1 < left or cx2 > right: continue
        if cy1 < bottom or cy2 > top: continue
        ch = textpg.get_text_range(i, 1)
        if not ch or not ch.strip(): continue
        # Convert to top-left origin
        chars.append({
            "text": ch,
            "x":    cx1,
            "y":    page_h - cy2,   # flip to top-left origin
            "h":    cy2 - cy1,
        })

    textpg.close()
    page.close()
    return chars


def _chars_to_table(chars: list) -> tuple:
    """
    Reconstruct a table from character bounding boxes (pypdfium2).

    Steps:
      1. Sort chars by Y then X; merge horizontally-adjacent chars into words
         using inter-character spacing as threshold
      2. Cluster words into text-lines by Y proximity
      3. Detect N column bands via histogram of word left-X edges
         with gap >= 5% of region width
      4. Assign each word to a column band
      5. Merge consecutive text-lines that are wrapped continuations of the
         same logical row (a new logical row starts when a word appears in
         the leftmost column band AND it was also occupied by the previous line)
      6. Build final grid; first text-line = headers
    """
    if not chars:
        return ["No text"], [["No text found in selected region."]]

    # ── 1. Merge chars → words ─────────────────────────────────────────────────
    chars.sort(key=lambda c: (c["y"], c["x"]))

    words = []
    buf   = chars[0]["text"]
    x0    = chars[0]["x"]
    rx    = chars[0]["x"] + chars[0].get("w", chars[0]["h"] * 0.55)
    y0    = chars[0]["y"]
    h0    = chars[0]["h"]

    for ch in chars[1:]:
        cw        = ch.get("w", ch["h"] * 0.55)
        same_line = abs(ch["y"] - y0) < max(h0, ch["h"]) * 0.55
        gap       = ch["x"] - rx
        unit      = max(h0, ch["h"]) * 0.55   # ~1 average char width

        if same_line and gap < unit * 0.8:
            # chars very close → same word (no space between them)
            buf += ch["text"]
            rx   = ch["x"] + cw
        elif same_line and gap < unit * 2.5:
            # small gap → same word but add a space
            buf += " " + ch["text"]
            rx   = ch["x"] + cw
        else:
            if buf.strip():
                words.append({"text": buf.strip(), "x": x0, "y": y0, "h": h0})
            buf = ch["text"]
            x0  = ch["x"]
            rx  = ch["x"] + cw
            y0  = ch["y"]
            h0  = ch["h"]

    if buf.strip():
        words.append({"text": buf.strip(), "x": x0, "y": y0, "h": h0})

    if not words:
        return ["Col1"], [["(empty)"]]

    # ── 2. Cluster words → text-lines ─────────────────────────────────────────
    words.sort(key=lambda w: (w["y"], w["x"]))
    lines      = []
    cur_words  = [words[0]]
    cur_y      = words[0]["y"]
    cur_h      = words[0]["h"]

    for w in words[1:]:
        if w["y"] - cur_y < max(cur_h, w["h"]) * 0.7:
            cur_words.append(w)
            # update running average y and h for robustness
            cur_h = max(cur_h, w["h"])
        else:
            lines.append(sorted(cur_words, key=lambda c: c["x"]))
            cur_words = [w]
            cur_y     = w["y"]
            cur_h     = w["h"]
    lines.append(sorted(cur_words, key=lambda c: c["x"]))

    if not lines:
        return ["Col1"], [["(empty)"]]

    # ── 3. Detect column bands ────────────────────────────────────────────────
    all_x    = [w["x"] for line in lines for w in line]
    x_min, x_max = min(all_x), max(all_x)
    region_w = x_max - x_min if x_max > x_min else 1.0
    min_gap  = max(4.0, region_w * 0.05)   # 5% of region width

    x_sorted  = sorted(set(round(x, 1) for x in all_x))
    col_bands = [x_sorted[0]]
    for x in x_sorted[1:]:
        if x - col_bands[-1] >= min_gap:
            col_bands.append(x)

    n_cols = len(col_bands)

    def col_of(x):
        return min(range(n_cols), key=lambda i: abs(x - col_bands[i]))

    # ── 4. Assign each text-line's words to columns ───────────────────────────
    def line_to_cells(line):
        cells = [""] * n_cols
        for w in line:
            ci = col_of(w["x"])
            cells[ci] = (cells[ci] + " " + w["text"]).strip()
        return cells

    # ── 5. Merge wrapped lines into logical table rows ─────────────────────────
    # Rule: a text-line starts a NEW table row if it has a word in column 0
    #       (leftmost band). Otherwise it is a continuation/wrap of the
    #       previous row — append its text to the same cells.
    table_rows = []   # list of cells-lists (already merged)

    for line in lines:
        cells     = line_to_cells(line)
        cols_used = {col_of(w["x"]) for w in line}
        starts_at_col0 = (0 in cols_used)

        prev_col0_filled = bool(table_rows and table_rows[-1][0].strip())
        # New row if: no rows yet, OR this line starts at col0 AND
        # the previous row already had something in col0 (= true new entry,
        # not a wrap of a multi-line first column)
        is_new_row = (not table_rows) or (starts_at_col0 and prev_col0_filled)

        if is_new_row:
            table_rows.append(list(cells))
        else:
            # Wrap continuation — merge into current row
            for ci, val in enumerate(cells):
                if val.strip():
                    table_rows[-1][ci] = (table_rows[-1][ci] + " " + val).strip()

    if not table_rows:
        return ["Col1"], [["(empty)"]]

    # ── 6. Build final output ──────────────────────────────────────────────────
    headers   = [h.strip() if h.strip() else f"Col{i+1}"
                 for i, h in enumerate(table_rows[0])]
    data_rows = table_rows[1:] if len(table_rows) > 1 else [[""] * n_cols]
    return headers, data_rows

class ExtractWorker(QObject):
    """Extracts text from PDF regions natively — no OCR, no Tesseract."""
    progress = pyqtSignal(int, str)
    done     = pyqtSignal(list)   # list of {"headers", "rows"}
    error    = pyqtSignal(str)

    def __init__(self, pdf_path: str, regions: list, groups: list, modes: list):
        """
        pdf_path: path to the PDF file (re-opened in worker thread)
        regions:  list of {"page_idx", "x_pt", "y_pt", "w_pt", "h_pt"}
        groups:   list of lists of region indices [[0,1],[2],...]
        modes:    list of {"mode": "append"|"join", "key": str}
        """
        super().__init__()
        self._path   = pdf_path
        self._regions = regions
        self._groups  = groups
        self._modes   = modes

    def run(self):
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(self._path)
        except Exception as exc:
            self.error.emit(f"Cannot open PDF:\n{exc}")
            return

        results = []
        total = len(self._groups)

        for gi, group in enumerate(self._groups):
            self.progress.emit(int(gi / total * 100),
                               f"Extracting group {gi+1}/{total}…")
            mode    = self._modes[gi].get("mode", "append")
            key_col = self._modes[gi].get("key", "")
            grp_res = []

            for ri in group:
                reg = self._regions[ri]
                try:
                    chars = _extract_region_text(
                        doc,
                        reg["page_idx"],
                        reg["x_pt"], reg["y_pt"],
                        reg["w_pt"], reg["h_pt"],
                    )
                    h, r = _chars_to_table(chars)
                    if not r or all(all(c == "" for c in row) for row in r):
                        r = [[""] * len(h)]
                    grp_res.append((h, r))
                except Exception as exc:
                    self.error.emit(
                        f"Extraction failed on region {ri+1}:\n"
                        f"{type(exc).__name__}: {exc}"
                    )
                    doc.close()
                    return

            if not grp_res:
                continue

            if mode == "join" and key_col and len(grp_res) > 1:
                merged = {}; all_hdrs = []
                for hdrs, rows in grp_res:
                    ki = hdrs.index(key_col) if key_col in hdrs else 0
                    for h in hdrs:
                        if h != key_col and h not in all_hdrs:
                            all_hdrs.append(h)
                    for row in rows:
                        kv = row[ki] if ki < len(row) else ""
                        if kv not in merged: merged[kv] = {}
                        for j, h in enumerate(hdrs):
                            if h != key_col and j < len(row):
                                merged[kv][h] = row[j]
                headers  = [key_col] + all_hdrs
                all_rows = [[kv] + [merged[kv].get(h,"") for h in all_hdrs]
                            for kv in sorted(merged)]
            else:
                headers  = grp_res[0][0]
                all_rows = list(grp_res[0][1])
                for hdrs, rows in grp_res[1:]:
                    for row in rows:
                        while len(row) < len(headers): row.append("")
                        all_rows.append(row[:len(headers)])

            if headers:
                results.append({"headers": headers, "rows": all_rows})

        doc.close()
        self.progress.emit(100, "Done")
        self.done.emit(results)


# ══════════════════════════════════════════════════════════════════════════════
# PDF Canvas  — renders PDF natively, rubber-band selection
# ══════════════════════════════════════════════════════════════════════════════
PAGE_GAP = 16   # px between pages

class PdfCanvas(QWidget):
    """
    Renders all pages of a PDF document natively (via pypdfium2).
    Pages are stacked vertically. On "select mode", user can drag a
    rubber-band rectangle; releasing it emits region_captured(pil_image, page_idx).
    """
    region_captured = pyqtSignal(object, int)   # (region_dict, page_index 0-based)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._doc         = None   # pypdfium2 PdfDocument
        self._n_pages     = 0
        self._scale       = 1.0
        self._pixmaps     = {}     # {page_idx: QPixmap}  — lazy cache
        self._page_tops   = []     # y-offset of each page top (widget coords)
        self._page_sizes  = []     # [(w_pt, h_pt)] in PDF points
        self._select_mode = False
        self._origin      = QPoint()
        self._rb          = QRubberBand(QRubberBand.Rectangle, self)
        self._last_pi     = 0
        self.setMouseTracking(True)

    # ── public ─────────────────────────────────────────────────────────────────
    def load_doc(self, doc, scale: float = 1.0):
        self._doc    = doc
        self._n_pages = len(doc)
        self._scale  = scale
        self._pixmaps.clear()
        self._compute_layout()
        self.update()

    def set_scale(self, scale: float):
        self._scale = scale
        self._pixmaps.clear()
        self._compute_layout()
        self.update()

    def set_select_mode(self, on: bool):
        self._select_mode = on
        self.setCursor(QCursor(Qt.CrossCursor if on else Qt.ArrowCursor))

    # ── layout ─────────────────────────────────────────────────────────────────
    def _compute_layout(self):
        if not self._doc: return
        self._page_tops  = []
        self._page_sizes = []
        y = 0
        max_w = 0
        for i in range(self._n_pages):
            page = self._doc[i]
            w_pt = page.get_width()
            h_pt = page.get_height()
            page.close()
            self._page_sizes.append((w_pt, h_pt))
            self._page_tops.append(y)
            px_w = int(w_pt * self._scale * RENDER_DPI / 72.0)
            px_h = int(h_pt * self._scale * RENDER_DPI / 72.0)
            y += px_h + PAGE_GAP
            max_w = max(max_w, px_w)
        total_h = y
        self.setMinimumSize(max_w + 40, total_h)
        self.resize(max_w + 40, total_h)

    def _page_pixmap(self, pi: int) -> QPixmap:
        if pi not in self._pixmaps:
            pm, _, _ = _render_page_to_pixmap(self._doc, pi, self._scale)
            self._pixmaps[pi] = pm
        return self._pixmaps[pi]

    def _page_x(self, pi: int) -> int:
        """Left x offset to center page horizontally."""
        pm_w = self._pixmaps.get(pi)
        if pm_w is None:
            # estimate from size
            w_pt, _ = self._page_sizes[pi]
            pm_w_val = int(w_pt * self._scale * RENDER_DPI / 72.0)
        else:
            pm_w_val = pm_w.width()
        return max(0, (self.width() - pm_w_val) // 2)

    def _page_at_y(self, y: int):
        """Return page index whose bounds contain y, or nearest."""
        for i in range(self._n_pages - 1, -1, -1):
            if y >= self._page_tops[i]:
                return i
        return 0

    # ── paint ──────────────────────────────────────────────────────────────────
    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1a1a1a"))
        if not self._doc: return
        # Only draw visible pages
        visible_top    = ev.rect().top()    - 50
        visible_bottom = ev.rect().bottom() + 50
        for i, top in enumerate(self._page_tops):
            pm = self._page_pixmap(i)
            px_h = pm.height()
            if top + px_h < visible_top: continue
            if top > visible_bottom: break
            x = self._page_x(i)
            # White page background shadow
            p.fillRect(x - 2, top - 2, pm.width() + 4, pm.height() + 4,
                       QColor("#333333"))
            p.drawPixmap(x, top, pm)
            # Page number
            p.setPen(QPen(QColor(COLORS["text_muted"])))
            f = p.font(); f.setPointSize(8); p.setFont(f)
            p.drawText(x, top + pm.height() + PAGE_GAP - 3,
                       f"— Page {i+1} —")

    # ── mouse ──────────────────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if self._select_mode and ev.button() == Qt.LeftButton:
            self._origin = ev.pos()
            self._rb.setGeometry(QRect(self._origin, QSize()))
            self._rb.show()

    def mouseMoveEvent(self, ev):
        if self._select_mode and not self._origin.isNull():
            self._rb.setGeometry(QRect(self._origin, ev.pos()).normalized())

    def mouseReleaseEvent(self, ev):
        if not (self._select_mode and ev.button() == Qt.LeftButton
                and not self._origin.isNull()):
            return
        self._rb.hide()
        rect = QRect(self._origin, ev.pos()).normalized()
        self._origin = QPoint()
        if rect.width() < 8 or rect.height() < 8:
            return
        self._emit_crop(rect)

    def _emit_crop(self, rect: QRect):
        if not self._doc: return
        pi = self._page_at_y(rect.y())
        self._last_pi = pi
        pm   = self._page_pixmap(pi)
        px   = self._page_x(pi)
        top  = self._page_tops[pi]
        w_pt, h_pt = self._page_sizes[pi]

        # Widget rect → PDF points (top-left origin)
        scale_x = w_pt / pm.width()
        scale_y = h_pt / pm.height()
        lx = max(0.0, (rect.x() - px)   * scale_x)
        ly = max(0.0, (rect.y() - top)   * scale_y)
        rw = min(rect.width()  * scale_x, w_pt - lx)
        rh = min(rect.height() * scale_y, h_pt - ly)
        if rw < 2 or rh < 2: return

        # Render region as PIL image for thumbnail/preview only
        pil_thumb = _crop_page_to_pil(self._doc, pi, lx, ly, rw, rh)

        region = {
            "page_idx": pi,
            "x_pt":     lx,
            "y_pt":     ly,
            "w_pt":     rw,
            "h_pt":     rh,
            "pil_thumb": pil_thumb,
        }
        self.region_captured.emit(region, pi)


# ══════════════════════════════════════════════════════════════════════════════
# PDF Reader Dialog
# ══════════════════════════════════════════════════════════════════════════════
class PdfReaderDialog(QDialog):
    tables_ready = pyqtSignal(list)

    def __init__(self, parent, pdf_path: str, article_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"PDF Reader — {os.path.basename(pdf_path)}")
        self.setMinimumSize(1050, 700)
        self.resize(1200, 820)
        self._path       = pdf_path
        self._article    = article_name
        self._doc        = None
        self._scale      = 1.0
        self._selections = []
        self._build_ui()
        self._load_doc()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top toolbar ────────────────────────────────────────────────────────
        tb = QWidget()
        tb.setFixedHeight(46)
        tb.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        tl = QHBoxLayout(tb)
        tl.setContentsMargins(10, 0, 10, 0)
        tl.setSpacing(8)

        # Zoom
        self._zoom_lbl = QLabel("100%")
        self._zoom_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;min-width:36px;"
        )
        bz_out = make_btn("−"); bz_out.setFixedWidth(28)
        bz_out.clicked.connect(lambda: self._set_zoom(self._scale - 0.15))
        bz_in  = make_btn("+"); bz_in.setFixedWidth(28)
        bz_in.clicked.connect(lambda: self._set_zoom(self._scale + 0.15))
        bz_fit = make_btn("Fit")
        bz_fit.clicked.connect(self._zoom_fit)
        tl.addWidget(bz_out); tl.addWidget(self._zoom_lbl); tl.addWidget(bz_in)
        tl.addWidget(bz_fit)
        tl.addStretch()

        self._count_lbl = QLabel("0 regions selected")
        self._count_lbl.setStyleSheet(
            f"font-size:8.5pt;color:{COLORS['accent_teal']};"
            "background:transparent;border:none;"
        )
        tl.addWidget(self._count_lbl)

        self._sel_btn = make_btn("⬚  Select Table Region", primary=True)
        self._sel_btn.setCheckable(True)
        self._sel_btn.toggled.connect(self._toggle_sel_mode)
        tl.addWidget(self._sel_btn)

        btn_adv = QPushButton("Advance  →")
        btn_adv.setStyleSheet(
            f"QPushButton{{background:{COLORS['accent_teal']};color:#fff;"
            "border-radius:5px;padding:5px 14px;font-size:9pt;font-weight:700;}}"
            f"QPushButton:hover{{background:{COLORS['accent_blue']};}}"
        )
        btn_adv.clicked.connect(self._advance)
        tl.addWidget(btn_adv)
        root.addWidget(tb)

        # ── Body ───────────────────────────────────────────────────────────────
        body = QSplitter(Qt.Horizontal)
        body.setStyleSheet(f"QSplitter::handle{{background:{COLORS['border']};width:1px;}}")

        # PDF scroll area
        self._scroll = QScrollArea()
        self._scroll.setStyleSheet("QScrollArea{background:#1a1a1a;border:none;}")
        self._scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._canvas = PdfCanvas()
        self._canvas.region_captured.connect(self._on_crop)
        self._scroll.setWidget(self._canvas)
        self._scroll.setWidgetResizable(False)
        body.addWidget(self._scroll)

        # Selection sidebar
        side = QWidget()
        side.setMinimumWidth(210); side.setMaximumWidth(270)
        side.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-left:1px solid {COLORS['border']};"
        )
        sl = QVBoxLayout(side); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)

        sh = QLabel("  Selections")
        sh.setFixedHeight(32)
        sh.setStyleSheet(
            f"font-size:8pt;font-weight:700;color:{COLORS['text_muted']};"
            f"background:{COLORS['bg_primary']};"
            f"border-bottom:1px solid {COLORS['border']};padding-left:8px;"
        )
        sl.addWidget(sh)

        self._sel_list = QListWidget()
        self._sel_list.setStyleSheet(LIST_STYLE)
        self._sel_list.currentRowChanged.connect(self._preview_sel)
        sl.addWidget(self._sel_list, 1)

        self._thumb = QLabel()
        self._thumb.setFixedHeight(110)
        self._thumb.setAlignment(Qt.AlignCenter)
        self._thumb.setStyleSheet(
            f"background:{COLORS['bg_primary']};"
            f"border-top:1px solid {COLORS['border']};"
        )
        sl.addWidget(self._thumb)

        btn_rm = make_btn("🗑  Remove", danger=True)
        btn_rm.clicked.connect(self._remove_sel)
        sl.addWidget(btn_rm)

        body.addWidget(side)
        body.setSizes([880, 240])
        root.addWidget(body, 1)

        # Status bar
        self._status = QLabel("  Loading PDF…")
        self._status.setFixedHeight(24)
        self._status.setStyleSheet(
            f"font-size:7.5pt;color:{COLORS['text_muted']};"
            f"background:{COLORS['bg_secondary']};"
            f"border-top:1px solid {COLORS['border']};padding-left:8px;"
        )
        root.addWidget(self._status)

    # ── PDF loading ────────────────────────────────────────────────────────────
    def _load_doc(self):
        self._status.setText("  Opening PDF…")
        QApplication.processEvents()
        try:
            import pypdfium2 as pdfium
            self._doc = pdfium.PdfDocument(self._path)
            self._canvas.load_doc(self._doc, self._scale)
            n = len(self._doc)
            self._status.setText(
                f"  {n} page(s)  —  click  ⬚ Select Table Region,  "
                f"then drag a rectangle over any table."
            )
        except Exception as e:
            self._status.setText(f"  ❌  {e}")
            QMessageBox.critical(self, "Cannot open PDF", str(e))

    def _set_zoom(self, scale: float):
        self._scale = max(0.3, min(4.0, scale))
        self._canvas.set_scale(self._scale)
        self._zoom_lbl.setText(f"{int(self._scale*100)}%")

    def _zoom_fit(self):
        """Fit page width to scroll area width."""
        if not self._doc: return
        page = self._doc[0]
        w_pt = page.get_width()
        page.close()
        avail_w = self._scroll.viewport().width() - 20
        px_per_pt = RENDER_DPI / 72.0
        fit_scale = avail_w / (w_pt * px_per_pt)
        self._set_zoom(fit_scale)

    def _toggle_sel_mode(self, on: bool):
        self._canvas.set_select_mode(on)
        self._sel_btn.setText(
            "⬚  Selecting…  drag on page" if on else "⬚  Select Table Region"
        )

    # ── Selection handling ─────────────────────────────────────────────────────
    def _on_crop(self, region: dict, page_idx: int):
        label = _next_label(len(self._selections))
        # Make thumbnail from the pre-rendered PIL image
        pil_thumb = region["pil_thumb"]
        thumb = pil_thumb.copy()
        thumb.thumbnail((240, 100), Image.LANCZOS)
        td  = thumb.tobytes("raw", "RGB")
        tqi = QImage(td, thumb.width, thumb.height,
                     thumb.width * 3, QImage.Format_RGB888)
        thumb_pm = QPixmap.fromImage(tqi)

        self._selections.append({
            "label":    label,
            "page":     page_idx + 1,
            "region":   region,          # contains page_idx, x_pt, y_pt, w_pt, h_pt
            "pil_crop": pil_thumb,       # kept for preview in TableReviewDialog
            "thumb":    thumb_pm,
        })
        item = QListWidgetItem(f"  {label}  —  page {page_idx+1}")
        self._sel_list.addItem(item)
        self._sel_list.setCurrentRow(self._sel_list.count() - 1)
        self._count_lbl.setText(f"{len(self._selections)} region(s)")
        self._sel_btn.setChecked(False)
        self._status.setText(
            f"  ✅  {label} captured  (page {page_idx+1}).  "
            "Select another region or click Advance."
        )

    def _preview_sel(self, row: int):
        if 0 <= row < len(self._selections):
            pm = self._selections[row]["thumb"]
            self._thumb.setPixmap(
                pm.scaled(self._thumb.width()-4, self._thumb.height()-4,
                          Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def _remove_sel(self):
        row = self._sel_list.currentRow()
        if row < 0: return
        self._selections.pop(row)
        self._sel_list.takeItem(row)
        for i, s in enumerate(self._selections):
            s["label"] = _next_label(i)
            self._sel_list.item(i).setText(
                f"  {s['label']}  —  page {s['page']}")
        self._count_lbl.setText(f"{len(self._selections)} region(s)")

    # ── Advance ────────────────────────────────────────────────────────────────
    def _advance(self):
        if not self._selections:
            QMessageBox.information(
                self, "No regions",
                "Select at least one table region first.\n\n"
                "① Click  ⬚ Select Table Region\n"
                "② Drag a rectangle over the table in the PDF\n"
                "③ Click Advance"
            )
            return
        dlg = TableReviewDialog(self, self._selections, self._article,
                                pdf_path=self._path)
        dlg.tables_ready.connect(self.tables_ready)
        if dlg.exec_() == QDialog.Accepted:
            self.accept()

    def closeEvent(self, ev):
        if self._doc:
            try: self._doc.close()
            except Exception: pass
        super().closeEvent(ev)


# ══════════════════════════════════════════════════════════════════════════════
# UnifyModeDialog
# ══════════════════════════════════════════════════════════════════════════════
class UnifyModeDialog(QDialog):
    def __init__(self, parent, labels: list):
        super().__init__(parent)
        self.setWindowTitle("Unify selections")
        self.setFixedSize(420, 240)
        self._mode = "append"; self._key = ""
        self._build(labels)

    def _build(self, labels):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14); lay.setSpacing(10)

        t = QLabel("  +  ".join(labels))
        t.setWordWrap(True)
        t.setStyleSheet(
            f"font-size:10pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        lay.addWidget(t)
        lay.addWidget(_lbl("How to combine OCR results:"))

        self._rb_app = QCheckBox("Append  —  stack rows vertically")
        self._rb_app.setChecked(True)
        self._rb_app.setStyleSheet(
            f"QCheckBox{{color:{COLORS['text_primary']};font-size:9pt;"
            "background:transparent;border:none;}")
        self._rb_join = QCheckBox("Join  —  merge side-by-side on a key column")
        self._rb_join.setStyleSheet(self._rb_app.styleSheet())
        self._rb_app.toggled.connect(lambda on: self._rb_join.setChecked(not on))
        self._rb_join.toggled.connect(lambda on: self._rb_app.setChecked(not on))
        lay.addWidget(self._rb_app); lay.addWidget(self._rb_join)

        kr = QHBoxLayout()
        kr.addWidget(_lbl("Key column:"))
        self._key_ed = QLineEdit()
        self._key_ed.setPlaceholderText("e.g. Compound  (blank = first column)")
        self._key_ed.setStyleSheet(SEARCH_STYLE)
        self._key_ed.setEnabled(False)
        self._rb_join.toggled.connect(self._key_ed.setEnabled)
        kr.addWidget(self._key_ed, 1)
        lay.addLayout(kr)

        lay.addStretch()
        btns = QHBoxLayout(); btns.addStretch()
        c = make_btn("Cancel"); ok = make_btn("✔  Unify", primary=True)
        c.clicked.connect(self.reject); ok.clicked.connect(self._ok)
        btns.addWidget(c); btns.addWidget(ok); lay.addLayout(btns)

    def _ok(self):
        self._mode = "join" if self._rb_join.isChecked() else "append"
        self._key  = self._key_ed.text().strip()
        self.accept()

    def get_mode(self):    return self._mode
    def get_key_col(self): return self._key


# ══════════════════════════════════════════════════════════════════════════════
# Table Review Dialog
# ══════════════════════════════════════════════════════════════════════════════
class TableReviewDialog(QDialog):
    tables_ready = pyqtSignal(list)

    def __init__(self, parent, selections: list, article_name: str = "",
                 pdf_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Review & Process")
        self.setMinimumSize(960, 620)
        self.resize(1000, 680)
        self._sels     = [dict(s) for s in selections]
        self._article  = article_name
        self._pdf_path = pdf_path
        self._results  = []
        self._build_ui()
        self._reload_list()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        hdr = QWidget(); hdr.setFixedHeight(50)
        hdr.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        hl = QHBoxLayout(hdr); hl.setContentsMargins(16,0,16,0); hl.setSpacing(10)
        hl.addWidget(_lbl("Review your selections, then click Process OCR."))
        hl.addStretch()
        btn_proc = make_btn("⚙  Process OCR", primary=True)
        btn_proc.clicked.connect(self._run_ocr)
        hl.addWidget(btn_proc)
        root.addWidget(hdr)

        body = QSplitter(Qt.Horizontal)
        body.setStyleSheet(f"QSplitter::handle{{background:{COLORS['border']};width:1px;}}")

        # Left panel
        left = QWidget()
        left.setMinimumWidth(270); left.setMaximumWidth(330)
        left.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-right:1px solid {COLORS['border']};"
        )
        ll = QVBoxLayout(left); ll.setContentsMargins(12,12,12,12); ll.setSpacing(8)
        ll.addWidget(_sec("Selections"))
        self._rev_list = QListWidget()
        self._rev_list.setStyleSheet(LIST_STYLE)
        self._rev_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._rev_list.currentRowChanged.connect(self._on_sel_click)
        ll.addWidget(self._rev_list, 1)

        self._rev_thumb = QLabel()
        self._rev_thumb.setFixedHeight(120)
        self._rev_thumb.setAlignment(Qt.AlignCenter)
        self._rev_thumb.setStyleSheet(
            f"background:{COLORS['bg_primary']};"
            f"border:1px solid {COLORS['border']};border-radius:4px;"
        )
        ll.addWidget(self._rev_thumb)

        ll.addWidget(_sec("Actions"))
        for label, fn in [
            ("✏  Rename",           self._rename),
            ("🗑  Delete",           self._delete),
            ("🔗  Unify checked",    self._unify),
        ]:
            b = make_btn(label, danger=label.startswith("🗑"))
            b.clicked.connect(fn)
            ll.addWidget(b)
        body.addWidget(left)

        # Right panel
        right = QWidget()
        right.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        rl = QVBoxLayout(right); rl.setContentsMargins(16,16,16,16); rl.setSpacing(10)
        rl.addWidget(_sec("Article / source name"))
        self._art_ed = QLineEdit(self._article)
        self._art_ed.setPlaceholderText("e.g. Smith_2020")
        self._art_ed.setStyleSheet(SEARCH_STYLE)
        rl.addWidget(self._art_ed)
        rl.addWidget(_sec("Preview"))
        self._big = QLabel()
        self._big.setAlignment(Qt.AlignCenter)
        self._big.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._big.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border:1px solid {COLORS['border']};border-radius:6px;"
        )
        sp = QScrollArea()
        sp.setWidget(self._big); sp.setWidgetResizable(True)
        sp.setStyleSheet(f"QScrollArea{{border:none;background:{COLORS['bg_secondary']};}}")
        rl.addWidget(sp, 1)
        body.addWidget(right)
        body.setSizes([300, 700])
        root.addWidget(body, 1)

        # Footer
        ftr = QWidget(); ftr.setFixedHeight(48)
        ftr.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-top:1px solid {COLORS['border']};"
        )
        fl = QHBoxLayout(ftr); fl.setContentsMargins(16,0,16,0); fl.setSpacing(10)
        self._ocr_lbl = QLabel("  Ready.")
        self._ocr_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;"
        )
        fl.addWidget(self._ocr_lbl, 1)
        c = make_btn("Cancel"); c.clicked.connect(self.reject)
        fl.addWidget(c)
        root.addWidget(ftr)

    def _reload_list(self):
        self._rev_list.clear()
        for s in self._sels:
            item = QListWidgetItem(f"  {s['label']}  —  page {s['page']}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self._rev_list.addItem(item)

    def _on_sel_click(self, row):
        if 0 <= row < len(self._sels):
            pm = self._sels[row]["thumb"]
            self._rev_thumb.setPixmap(
                pm.scaled(260, 116, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            crop = self._sels[row]["pil_crop"]
            bw = max(200, self._big.width()-10)
            bh = max(200, self._big.height()-10)
            preview = crop.copy(); preview.thumbnail((bw*2, bh*2), Image.LANCZOS)
            d = preview.tobytes("raw","RGB")
            qi = QImage(d, preview.width, preview.height,
                        preview.width*3, QImage.Format_RGB888)
            big_pm = QPixmap.fromImage(qi)
            self._big.setPixmap(big_pm)
            self._big.resize(big_pm.size())

    def _rename(self):
        row = self._rev_list.currentRow()
        if row < 0: return
        name, ok = QInputDialog.getText(
            self, "Rename", "New label:", text=self._sels[row]["label"])
        if ok and name.strip():
            self._sels[row]["label"] = name.strip()
            self._rev_list.item(row).setText(
                f"  {name.strip()}  —  page {self._sels[row]['page']}")

    def _delete(self):
        rows = sorted({self._rev_list.row(i)
                       for i in self._rev_list.selectedItems()}, reverse=True)
        for r in rows: self._sels.pop(r)
        self._reload_list()

    def _unify(self):
        checked = [i for i in range(self._rev_list.count())
                   if self._rev_list.item(i).checkState() == Qt.Checked]
        if len(checked) < 2:
            QMessageBox.information(self, "Unify",
                "Check the checkbox (☐) next to at least 2 items, "
                "then click Unify."); return
        labels = [self._sels[i]["label"] for i in checked]
        dlg = UnifyModeDialog(self, labels)
        if dlg.exec_() != QDialog.Accepted: return
        base = checked[0]
        self._sels[base]["label"]      = " + ".join(labels)
        # unify_with needs the full selection dict including "region"
        self._sels[base]["unify_with"] = [dict(self._sels[i]) for i in checked[1:]]
        self._sels[base]["unify_mode"] = dlg.get_mode()
        self._sels[base]["unify_key"]  = dlg.get_key_col()
        for i in sorted(checked[1:], reverse=True): self._sels.pop(i)
        self._reload_list()

    def _run_ocr(self):
        if not self._sels:
            QMessageBox.information(self, "Empty", "Nothing to process."); return
        art = self._art_ed.text().strip() or "Article"

        # Build flat region list and groups
        regions, groups, modes = [], [], []
        for s in self._sels:
            gi = [len(regions)]
            regions.append(s["region"])
            for ex in s.get("unify_with", []):
                gi.append(len(regions))
                regions.append(ex["region"])
            groups.append(gi)
            modes.append({"mode": s.get("unify_mode", "append"),
                          "key":  s.get("unify_key",  "")})

        prog = QProgressDialog("Extracting text…", None, 0, 100, self)
        prog.setWindowTitle("Extracting"); prog.setWindowModality(Qt.WindowModal)
        prog.setValue(0); QApplication.processEvents()

        self._thr = QThread()
        self._wkr = ExtractWorker(self._pdf_path, regions, groups, modes)
        self._wkr.moveToThread(self._thr)
        self._thr.started.connect(self._wkr.run)
        self._wkr.progress.connect(
            lambda v, m: (prog.setValue(v), prog.setLabelText(m),
                          QApplication.processEvents()))
        self._wkr.done.connect(lambda res: self._ocr_done(res, art, prog))
        self._wkr.error.connect(
            lambda e: (prog.close(),
                       QMessageBox.critical(self, "Extraction Error", e)))
        self._thr.start()

    def _ocr_done(self, results, art, prog):
        prog.close(); self._thr.quit()
        if not results:
            self._ocr_lbl.setText("  ⚠  No text found in selected region."); return
        named = [{"name":    f"{s['label']} — {art}",
                  "headers": r["headers"],
                  "rows":    r["rows"],
                  "source":  art}
                 for s, r in zip(self._sels, results)]
        self._results = named
        self.tables_ready.emit(named)
        self._ocr_lbl.setText(f"  ✅  {len(named)} table(s) extracted.")
        self.accept()

    def get_results(self): return self._results


# ══════════════════════════════════════════════════════════════════════════════
# Editable table widget
# ══════════════════════════════════════════════════════════════════════════════
class EditableTable(QTableWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(TABLE_STYLE)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionsMovable(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx)
        self.itemChanged.connect(lambda _: self.changed.emit())

    def load(self, headers, rows):
        self.blockSignals(True)
        self.clear()
        self.setColumnCount(len(headers)); self.setRowCount(len(rows))
        self.setHorizontalHeaderLabels(headers)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.setItem(r, c, QTableWidgetItem(str(val) if val else ""))
        self.resizeColumnsToContents()
        self.blockSignals(False)

    def get_headers(self):
        return [self.horizontalHeaderItem(c).text()
                if self.horizontalHeaderItem(c) else f"Col{c}"
                for c in range(self.columnCount())]

    def get_rows(self):
        return [[(self.item(r,c).text() if self.item(r,c) else "")
                 for c in range(self.columnCount())]
                for r in range(self.rowCount())]

    def _ctx(self, pos):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{COLORS['bg_secondary']};border:1px solid {COLORS['border']};}}"
            f"QMenu::item{{padding:6px 20px;color:{COLORS['text_primary']};}}"
            f"QMenu::item:selected{{background:{COLORS['bg_hover']};}}"
        )
        menu.addAction("➕  Insert row above", lambda: self._ins_row(True))
        menu.addAction("➕  Insert row below", lambda: self._ins_row(False))
        menu.addAction("🗑  Delete rows",       self._del_rows)
        menu.addSeparator()
        menu.addAction("➕  Insert column",    self._ins_col)
        menu.addAction("✏  Rename column",     self._ren_col)
        menu.addAction("🗑  Delete column",    self._del_col)
        menu.addSeparator()
        menu.addAction("📋  Copy",             self._copy)
        menu.exec_(self.viewport().mapToGlobal(pos))

    def _ins_row(self, before):
        rows = sorted({i.row() for i in self.selectedItems()})
        r = (rows[0] if rows else self.rowCount()) if before \
            else (rows[-1]+1 if rows else self.rowCount())
        self.insertRow(r); self.changed.emit()

    def _del_rows(self):
        for r in sorted({i.row() for i in self.selectedItems()}, reverse=True):
            self.removeRow(r)
        self.changed.emit()

    def _ins_col(self):
        c = self.columnCount(); self.insertColumn(c)
        self.setHorizontalHeaderItem(c, QTableWidgetItem(f"Col{c+1}"))
        self.changed.emit()

    def _ren_col(self):
        cols = sorted({i.column() for i in self.selectedItems()})
        if not cols: return
        cur = self.horizontalHeaderItem(cols[0]).text() \
              if self.horizontalHeaderItem(cols[0]) else ""
        text, ok = QInputDialog.getText(self, "Rename Column", "New name:", text=cur)
        if ok and text.strip():
            self.setHorizontalHeaderItem(cols[0], QTableWidgetItem(text.strip()))
            self.changed.emit()

    def _del_col(self):
        for c in sorted({i.column() for i in self.selectedItems()}, reverse=True):
            self.removeColumn(c)
        self.changed.emit()

    def _copy(self):
        rows = defaultdict(dict)
        for it in self.selectedItems():
            rows[it.row()][it.column()] = it.text()
        lines = ["\t".join(rows[r].get(c,"") for c in sorted(rows[r]))
                 for r in sorted(rows)]
        QApplication.clipboard().setText("\n".join(lines))


# ══════════════════════════════════════════════════════════════════════════════
# Main Module
# ══════════════════════════════════════════════════════════════════════════════
class CompilerModule(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self._active_tid = None
        self._pdf_paths  = []
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        hdr.setFixedHeight(60)
        hl = QHBoxLayout(hdr); hl.setContentsMargins(20,0,20,0)
        title = QLabel("Data Compiler")
        title.setStyleSheet(
            f"font-size:15pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;")
        sub = QLabel("Load PDFs · select table regions · OCR · edit · export")
        sub.setStyleSheet(
            f"font-size:9pt;color:{COLORS['text_secondary']};"
            "background:transparent;border:none;")
        ts = QVBoxLayout(); ts.setSpacing(1)
        ts.addWidget(title); ts.addWidget(sub)
        hl.addLayout(ts); hl.addStretch()
        root.addWidget(hdr)

        body = QSplitter(Qt.Horizontal)
        body.setStyleSheet(f"QSplitter::handle{{background:{COLORS['border']};width:1px;}}")

        # ── Left: PDF list ─────────────────────────────────────────────────────
        pdf_pane = QWidget()
        pdf_pane.setMinimumWidth(190); pdf_pane.setMaximumWidth(250)
        pdf_pane.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-right:1px solid {COLORS['border']};"
        )
        pl = QVBoxLayout(pdf_pane); pl.setContentsMargins(0,0,0,0); pl.setSpacing(0)
        ph = QLabel("  Loaded PDFs")
        ph.setFixedHeight(32)
        ph.setStyleSheet(
            f"font-size:8pt;font-weight:700;color:{COLORS['text_muted']};"
            f"background:{COLORS['bg_primary']};"
            f"border-bottom:1px solid {COLORS['border']};padding-left:8px;"
        )
        pl.addWidget(ph)
        self._pdf_list = QListWidget()
        self._pdf_list.setStyleSheet(LIST_STYLE)
        self._pdf_list.doubleClicked.connect(self._open_reader)
        pl.addWidget(self._pdf_list, 1)

        ptb = QWidget()
        ptb.setStyleSheet(
            f"background:{COLORS['bg_primary']};"
            f"border-top:1px solid {COLORS['border']};"
        )
        ptbl = QVBoxLayout(ptb); ptbl.setContentsMargins(8,6,8,6); ptbl.setSpacing(4)
        for label, fn in [
            ("📂  Add PDF(s)",     self._add_pdfs),
            ("📖  Open Reader",    self._open_reader),
            ("🗑  Remove PDF",     self._remove_pdf),
        ]:
            b = make_btn(label,
                         primary=label.startswith("📂"),
                         danger=label.startswith("🗑"))
            b.clicked.connect(fn)
            ptbl.addWidget(b)
        pl.addWidget(ptb)
        body.addWidget(pdf_pane)

        # ── Right: captured tables ─────────────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        rl = QVBoxLayout(right); rl.setContentsMargins(0,0,0,0); rl.setSpacing(0)

        rtb = QWidget(); rtb.setFixedHeight(46)
        rtb.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        rtbl = QHBoxLayout(rtb); rtbl.setContentsMargins(12,0,12,0); rtbl.setSpacing(8)
        self._tbl_lbl = QLabel("  Select a table →")
        self._tbl_lbl.setStyleSheet(
            f"font-size:9pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;")
        rtbl.addWidget(self._tbl_lbl, 1)
        for label, fn in [
            ("✏  Rename",              self._rename_tbl),
            ("🗑  Delete",              self._delete_tbl),
            ("📤  Send to Review Data", self._send_review),
            ("⬇  Export CSV",          self._export_csv),
            ("📋  Copy",               self._copy_tbl),
        ]:
            b = make_btn(label,
                         primary=label.startswith("📤"),
                         danger=label.startswith("🗑"))
            b.clicked.connect(fn)
            rtbl.addWidget(b)
        rl.addWidget(rtb)

        rs = QSplitter(Qt.Horizontal)
        rs.setStyleSheet(f"QSplitter::handle{{background:{COLORS['border']};width:1px;}}")

        tlp = QWidget()
        tlp.setMinimumWidth(190); tlp.setMaximumWidth(250)
        tlp.setStyleSheet(f"background:{COLORS['bg_secondary']};")
        tlpl = QVBoxLayout(tlp); tlpl.setContentsMargins(0,0,0,0); tlpl.setSpacing(0)
        tlh = QLabel("  Captured Tables")
        tlh.setFixedHeight(32)
        tlh.setStyleSheet(
            f"font-size:8pt;font-weight:700;color:{COLORS['text_muted']};"
            f"background:{COLORS['bg_primary']};"
            f"border-bottom:1px solid {COLORS['border']};padding-left:8px;"
        )
        tlpl.addWidget(tlh)
        self._tbl_list = QListWidget()
        self._tbl_list.setStyleSheet(LIST_STYLE)
        self._tbl_list.currentRowChanged.connect(self._on_tbl_select)
        tlpl.addWidget(self._tbl_list, 1)
        rs.addWidget(tlp)

        tv = QWidget()
        tv.setStyleSheet(f"background:{COLORS['bg_primary']};border:none;")
        tvl = QVBoxLayout(tv); tvl.setContentsMargins(0,0,0,0); tvl.setSpacing(0)
        sbw = QWidget(); sbw.setFixedHeight(38)
        sbw.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        sbl = QHBoxLayout(sbw); sbl.setContentsMargins(10,0,10,0)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search in table…")
        self._search.setStyleSheet(SEARCH_STYLE)
        self._search.textChanged.connect(self._apply_search)
        sbl.addWidget(self._search)
        tvl.addWidget(sbw)
        self._tbl_view = EditableTable()
        self._tbl_view.changed.connect(self._persist_edits)
        tvl.addWidget(self._tbl_view, 1)
        rs.addWidget(tv)
        rs.setSizes([220, 900])
        rl.addWidget(rs, 1)

        self._status = QLabel("  Add a PDF, open the Reader, select a table region.")
        self._status.setFixedHeight(26)
        self._status.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            f"background:{COLORS['bg_secondary']};"
            f"border-top:1px solid {COLORS['border']};padding-left:8px;"
        )
        rl.addWidget(self._status)
        body.addWidget(right)
        body.setSizes([220, 1000])
        root.addWidget(body, 1)

    # ── PDF management ─────────────────────────────────────────────────────────
    def _add_pdfs(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add PDF(s)", "", "PDF Files (*.pdf)")
        for path in paths:
            if path in self._pdf_paths: continue
            self._pdf_paths.append(path)
            item = QListWidgetItem(f"  {os.path.basename(path)}")
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self._pdf_list.addItem(item)
        if paths:
            self._pdf_list.setCurrentRow(self._pdf_list.count()-1)

    def _remove_pdf(self):
        item = self._pdf_list.currentItem()
        if not item: return
        path = item.data(Qt.UserRole)
        self._pdf_list.takeItem(self._pdf_list.currentRow())
        if path in self._pdf_paths: self._pdf_paths.remove(path)

    def _open_reader(self):
        item = self._pdf_list.currentItem()
        if not item:
            Toast.show_toast(self, "Select a PDF first", "warning"); return
        path = item.data(Qt.UserRole)
        art  = self._guess_article(path)
        dlg  = PdfReaderDialog(self, path, art)
        dlg.tables_ready.connect(self._on_tables_ready)
        dlg.exec_()

    def _guess_article(self, path: str) -> str:
        fname = os.path.splitext(os.path.basename(path))[0]
        for a in (self.db.get_articles() if hasattr(self.db,"get_articles") else []):
            if fname.lower() in a.get("title","").lower():
                author = a.get("authors","").split(",")[0].strip()
                year   = a.get("year","")
                return f"{author}_{year}" if author else fname
        return fname

    def _on_tables_ready(self, tables: list):
        for t in tables:
            self.db.save_extracted_table(
                t["name"], t["headers"], t["rows"],
                source_file=t.get("source",""), page_num=0)
        self.refresh(); self.data_changed.emit()
        Toast.show_toast(self, f"{len(tables)} table(s) added", "success")
        self._status.setText(f"  ✅  {len(tables)} table(s) captured and saved.")

    # ── table list ─────────────────────────────────────────────────────────────
    def refresh(self):
        self._tbl_list.blockSignals(True)
        self._tbl_list.clear()
        for t in self.db.get_extracted_tables():
            item = QListWidgetItem(f"  {t['name']}")
            item.setData(Qt.UserRole, t["id"])
            item.setToolTip(
                f"Source: {t.get('source_file','?')}\n"
                f"{len(t['headers'])} cols · {len(t['rows'])} rows")
            self._tbl_list.addItem(item)
        self._tbl_list.blockSignals(False)

    def _on_tbl_select(self, row):
        item = self._tbl_list.item(row)
        if not item: return
        tid = item.data(Qt.UserRole)
        self._active_tid = tid
        t = self.db.get_extracted_table(tid)
        if not t: return
        self._tbl_lbl.setText(f"  {t['name']}")
        self._tbl_view.load(t["headers"], t["rows"])
        self._status.setText(
            f"  {t['name']}  —  {len(t['headers'])} cols · {len(t['rows'])} rows")

    def _persist_edits(self):
        if self._active_tid is None: return
        self.db.update_extracted_table(
            self._active_tid,
            headers=self._tbl_view.get_headers(),
            rows=self._tbl_view.get_rows())

    def _apply_search(self):
        if self._active_tid is None: return
        t = self.db.get_extracted_table(self._active_tid)
        if not t: return
        q = self._search.text().strip().lower()
        rows = t["rows"] if not q else [
            r for r in t["rows"] if q in " ".join(str(c).lower() for c in r)]
        self._tbl_view.load(t["headers"], rows)

    # ── table actions ──────────────────────────────────────────────────────────
    def _rename_tbl(self):
        item = self._tbl_list.currentItem()
        if not item: return
        tid = item.data(Qt.UserRole)
        t = self.db.get_extracted_table(tid)
        if not t: return
        name, ok = QInputDialog.getText(
            self, "Rename", "New name:", text=t["name"])
        if ok and name.strip():
            self.db.update_extracted_table(tid, name=name.strip())
            self.refresh()

    def _delete_tbl(self):
        item = self._tbl_list.currentItem()
        if not item: return
        tid = item.data(Qt.UserRole)
        t = self.db.get_extracted_table(tid)
        if not t: return
        if QMessageBox.question(self, "Delete", f'Delete "{t["name"]}"?',
                                QMessageBox.Yes|QMessageBox.No) == QMessageBox.Yes:
            self.db.delete_extracted_table(tid)
            self._active_tid = None
            self.refresh(); self._tbl_view.clearContents()

    def _send_review(self):
        if self._active_tid is None:
            Toast.show_toast(self, "No table selected","warning"); return
        t = self.db.get_extracted_table(self._active_tid)
        if not t or not t["headers"]: return
        dlg = SendToReviewDialog(self, t["headers"], t["rows"], self.db)
        if dlg.exec_() == QDialog.Accepted:
            self.data_changed.emit()
            Toast.show_toast(self, f"Sent {dlg.get_count()} rows","success")

    def _export_csv(self):
        if self._active_tid is None:
            Toast.show_toast(self,"No table selected","warning"); return
        t = self.db.get_extracted_table(self._active_tid)
        if not t: return
        path, _ = QFileDialog.getSaveFileName(
            self,"Export CSV",f"{t['name']}.csv","CSV (*.csv)")
        if not path: return
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            w = csv.writer(f); w.writerow(t["headers"]); w.writerows(t["rows"])
        Toast.show_toast(self, f"Exported {len(t['rows'])} rows","success")

    def _copy_tbl(self):
        if self._active_tid is None:
            Toast.show_toast(self,"No table selected","warning"); return
        t = self.db.get_extracted_table(self._active_tid)
        if not t: return
        lines = ["\t".join(t["headers"])]
        lines += ["\t".join(str(c) for c in r) for r in t["rows"]]
        QApplication.clipboard().setText("\n".join(lines))
        Toast.show_toast(self, f"Copied {len(t['rows'])} rows","success")


# ══════════════════════════════════════════════════════════════════════════════
# Send to Review Data dialog
# ══════════════════════════════════════════════════════════════════════════════
class SendToReviewDialog(QDialog):
    FIELDS = [
        ("object_name","Object *",      True),
        ("parameter",  "Parameter *",   True),
        ("value",      "Value",         False),
        ("unit",       "Unit",          False),
        ("species",    "Species",       False),
        ("article_ref","Article/Source",False),
        ("notes",      "Notes",         False),
    ]
    def __init__(self, parent, headers, rows, db):
        super().__init__(parent)
        self.setWindowTitle("Send to Review Data")
        self.setMinimumWidth(500)
        self._h=headers; self._r=rows; self._db=db; self._n=0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20,20,20,16); lay.setSpacing(10)
        t = QLabel("Map columns → Review Data fields")
        t.setStyleSheet(
            f"font-size:11pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;")
        lay.addWidget(t)
        grid = QGridLayout(); grid.setSpacing(8); grid.setColumnStretch(1,1)
        self._cbs = {}
        opts = ["— skip —"] + self._h
        for i,(field,label,req) in enumerate(self.FIELDS):
            lb = QLabel(label)
            lb.setStyleSheet(
                f"color:{COLORS['text_primary'] if req else COLORS['text_secondary']};"
                "font-size:9pt;background:transparent;border:none;")
            if req: f2=lb.font(); f2.setBold(True); lb.setFont(f2)
            cb = QComboBox(); cb.setStyleSheet(CB_STYLE); cb.addItems(opts)
            for opt in self._h:
                if any(kw in opt.lower() for kw in field.split("_")):
                    cb.setCurrentText(opt); break
            self._cbs[field] = cb
            grid.addWidget(lb,i,0); grid.addWidget(cb,i,1)
        lay.addLayout(grid)
        self._art = QLineEdit()
        self._art.setPlaceholderText("Fixed article ref (optional)")
        self._art.setStyleSheet(SEARCH_STYLE)
        lay.addWidget(self._art)
        btns = QHBoxLayout(); btns.addStretch()
        c = make_btn("Cancel"); ok = make_btn("✔  Import",primary=True)
        c.clicked.connect(self.reject); ok.clicked.connect(self._do)
        btns.addWidget(c); btns.addWidget(ok); lay.addLayout(btns)

    def _do(self):
        m = {f: self._cbs[f].currentText() for f in self._cbs}
        if m["object_name"]=="— skip —" or m["parameter"]=="— skip —":
            QMessageBox.warning(self,"Required","Object and Parameter must be mapped."); return
        def cv(row,f):
            col=m.get(f,"— skip —")
            if col=="— skip —" or col not in self._h: return ""
            i=self._h.index(col); return row[i] if i<len(row) else ""
        art=self._art.text().strip(); n=0
        for row in self._r:
            obj=cv(row,"object_name").strip(); par=cv(row,"parameter").strip()
            if not obj or not par: continue
            self._db.add_review_row(object_name=obj,parameter=par,
                value=cv(row,"value"),unit=cv(row,"unit"),species=cv(row,"species"),
                article_ref=cv(row,"article_ref") or art,notes=cv(row,"notes"))
            n+=1
        self._n=n; self.accept()

    def get_count(self): return self._n
