"""
SLDM — CSV / Spreadsheet Editor Dialog
Opens CSV, XLSX, XLS, ODS files as an editable table with:
  - Auto-delimiter detection (;  ,  space+comma)
  - Toggle delimiter button
  - Error detection (wrong column count → red rows)
  - Inline cell editing
  - Add / delete rows
  - Sort by any column (alphabetical, numeric, string-length)
  - Import into SLDM Object List
"""

import os
import csv
import json
import re
import io

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QMessageBox, QApplication, QWidget, QFrame,
    QToolButton, QMenu, QAction, QFileDialog, QSizePolicy,
    QButtonGroup, QCheckBox, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal, QSortFilterProxyModel, QSize
from PyQt5.QtGui import QColor, QFont, QBrush

from core.widgets import make_btn, Toast
from core.theme import COLORS

# ── SUPPORTED EXTENSIONS ──────────────────────────────────────────────────────
SUPPORTED_FILTER = (
    "Spreadsheets (*.csv *.xlsx *.xls *.ods *.ots);;"
    "CSV files (*.csv);;"
    "Excel files (*.xlsx *.xls);;"
    "OpenDocument (*.ods *.ots);;"
    "All files (*)"
)

# Row-error background
_COLOR_ERR  = QColor("#3d1a1a")   # dark red tint
_COLOR_WARN = QColor("#3d2e0a")   # amber tint
_COLOR_OK   = QColor(COLORS["bg_secondary"])


# ── FILE READERS ──────────────────────────────────────────────────────────────

def _read_xlsx(path: str):
    """Read xlsx/xlsm → list of rows (list of strings)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append([str(c) if c is not None else "" for c in row])
    wb.close()
    return rows


def _read_xls(path: str):
    """Read legacy .xls — tries xlrd, falls back to openpyxl."""
    try:
        import xlrd
        wb = xlrd.open_workbook(path)
        ws = wb.sheet_by_index(0)
        return [[str(ws.cell_value(r, c)) for c in range(ws.ncols)]
                for r in range(ws.nrows)]
    except ImportError:
        pass
    # Fallback: openpyxl can sometimes open xls
    try:
        return _read_xlsx(path)
    except Exception as e:
        raise ValueError(f"Cannot read .xls file (xlrd not installed): {e}")


def _read_ods(path: str):
    """Read ODS/OTS (OpenDocument Spreadsheet)."""
    from odf.opendocument import load as odf_load
    from odf.table import Table, TableRow, TableCell
    from odf.text import P

    doc = odf_load(path)
    sheets = doc.spreadsheet.getElementsByType(Table)
    if not sheets:
        return []
    rows_out = []
    for row in sheets[0].getElementsByType(TableRow):
        cells = row.getElementsByType(TableCell)
        row_data = []
        for cell in cells:
            repeat = int(cell.getAttribute("numbercolumnsrepeated") or 1)
            texts = cell.getElementsByType(P)
            val = " ".join(str(t) for t in texts) if texts else ""
            row_data.extend([val] * repeat)
        rows_out.append(row_data)
    return rows_out


def read_spreadsheet(path: str):
    """Dispatch to the right reader based on extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    elif ext == ".xls":
        return _read_xls(path)
    elif ext in (".ods", ".ots"):
        return _read_ods(path)
    else:
        return None   # caller will handle as CSV


# ── DELIMITER DETECTION ───────────────────────────────────────────────────────

DELIMITERS = {
    ";":          ";",
    ",":          ",",
    " ,":         " ,",   # space+comma
    "\\t":        "\t",
}
DELIM_LABELS = {
    ";":    "Semicolon  ( ; )",
    ",":    "Comma  ( , )",
    " ,":   "Space+Comma  ( space, )",
    "\\t":  "Tab  ( \\t )",
}


def detect_delimiter(text: str) -> str:
    """Return the most likely column delimiter for the given text sample."""
    first_line = text.split('\n')[0]
    counts = {
        ";":   first_line.count(';'),
        ",":   first_line.count(','),
        "\t":  first_line.count('\t'),
    }
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        return ";"
    return best


def parse_csv_rows(text: str, delimiter: str) -> list:
    """Parse CSV text into list of rows (list of strings) using given delimiter."""
    if delimiter == " ,":
        # Space+comma: split on ", " (comma preceded by optional space)
        lines = text.splitlines()
        rows = []
        for line in lines:
            if not line.strip():
                continue
            rows.append([cell.strip() for cell in re.split(r'\s*,\s*', line)])
        return rows
    else:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        return [row for row in reader if any(c.strip() for c in row)]


# ── MAIN DIALOG ───────────────────────────────────────────────────────────────

class CsvEditorDialog(QDialog):
    """
    Full-featured spreadsheet preview/editor dialog.
    Emits `import_requested(rows, header)` when user clicks Import.
    """
    import_requested = pyqtSignal(list, list)   # (data_rows, header_row)

    def __init__(self, parent=None, filepath: str = None):
        super().__init__(parent)
        self.setWindowTitle("Spreadsheet Editor")
        self.setMinimumSize(1100, 700)
        self.setAttribute(Qt.WA_DeleteOnClose)

        self._filepath  = filepath
        self._raw_text  = ""          # original CSV text (empty for xlsx/ods)
        self._delimiter = ";"         # current delimiter key
        self._all_rows  = []          # list[list[str]] — raw parsed rows
        self._header    = []          # first row used as header
        self._expected_cols = 0       # column count from header row

        self._build_ui()

        if filepath:
            self._load_file(filepath)

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(12, 0, 12, 0)
        tb_lay.setSpacing(8)

        # File info
        self._lbl_file = QLabel("No file loaded")
        self._lbl_file.setStyleSheet(
            f"color:{COLORS['text_secondary']};font-size:9pt;"
            "background:transparent;border:none;"
        )
        tb_lay.addWidget(self._lbl_file, 1)

        # Delimiter selector
        delim_lbl = QLabel("Delimiter:")
        delim_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:8pt;"
            "background:transparent;border:none;"
        )
        tb_lay.addWidget(delim_lbl)

        self._delim_combo = QComboBox()
        for key, label in DELIM_LABELS.items():
            self._delim_combo.addItem(label, key)
        self._delim_combo.setFixedWidth(180)
        self._delim_combo.currentIndexChanged.connect(self._on_delim_changed)
        tb_lay.addWidget(self._delim_combo)

        tb_lay.addWidget(self._vsep())

        # Sort menu
        self._sort_btn = make_btn("⇅  Sort…")
        self._sort_btn.clicked.connect(self._show_sort_menu)
        tb_lay.addWidget(self._sort_btn)

        # Add / delete row
        btn_add_row = make_btn("＋ Row")
        btn_del_row = make_btn("－ Row", danger=True)
        btn_add_row.clicked.connect(self._add_row)
        btn_del_row.clicked.connect(self._delete_selected_rows)
        tb_lay.addWidget(btn_add_row)
        tb_lay.addWidget(btn_del_row)

        tb_lay.addWidget(self._vsep())

        # Import button
        btn_import = make_btn("⬇  Import into SLDM", primary=True)
        btn_import.clicked.connect(self._do_import)
        tb_lay.addWidget(btn_import)

        root.addWidget(toolbar)

        # ── Error banner (hidden by default)
        self._error_banner = QLabel("")
        self._error_banner.setWordWrap(True)
        self._error_banner.setStyleSheet(
            "background:#4a1e1e;color:#f87171;"
            "padding:6px 14px;font-size:8pt;border:none;"
        )
        self._error_banner.setVisible(False)
        root.addWidget(self._error_banner)

        # ── Stats bar
        self._stats_bar = QLabel("")
        self._stats_bar.setStyleSheet(
            f"background:{COLORS['bg_primary']};color:{COLORS['text_muted']};"
            "padding:3px 14px;font-size:8pt;border:none;"
        )
        root.addWidget(self._stats_bar)

        # ── Table
        self._table = QTableWidget()
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setShowGrid(False)
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: {COLORS['bg_primary']};
                border: none;
                gridline-color: {COLORS['border']};
            }}
            QTableWidget::item {{
                padding: 4px 8px;
                color: {COLORS['text_primary']};
            }}
            QTableWidget::item:selected {{
                background: {COLORS['accent_blue']}33;
            }}
            QHeaderView::section {{
                background: {COLORS['bg_secondary']};
                color: {COLORS['text_secondary']};
                padding: 4px 8px;
                border: none;
                border-right: 1px solid {COLORS['border']};
                font-size: 8pt;
                font-weight: 600;
            }}
        """)
        root.addWidget(self._table)

        # ── Bottom bar
        bot = QWidget()
        bot.setFixedHeight(40)
        bot.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-top:1px solid {COLORS['border']};"
        )
        bl = QHBoxLayout(bot)
        bl.setContentsMargins(12, 0, 12, 0)
        self._lbl_errors = QLabel("")
        self._lbl_errors.setStyleSheet(
            "color:#f87171;font-size:8pt;background:transparent;border:none;"
        )
        bl.addWidget(self._lbl_errors)
        bl.addStretch()
        btn_close = make_btn("Close")
        btn_close.clicked.connect(self.reject)
        bl.addWidget(btn_close)
        root.addWidget(bot)

    def _vsep(self):
        sep = QFrame()
        sep.setFixedSize(1, 28)
        sep.setStyleSheet(f"background:{COLORS['border']};border:none;")
        return sep

    # ── LOAD ──────────────────────────────────────────────────────────────────
    def _load_file(self, path: str):
        self._filepath = path
        self._lbl_file.setText(f"📄  {os.path.basename(path)}  —  {path}")

        ext = os.path.splitext(path)[1].lower()
        rows = None

        if ext not in (".csv", ".tsv", ".txt"):
            try:
                rows = read_spreadsheet(path)
            except Exception as e:
                QMessageBox.critical(self, "Cannot open file", str(e))
                return
            if rows is None:
                QMessageBox.critical(self, "Unsupported format", f"Cannot read: {ext}")
                return
            # Non-CSV: no delimiter needed, hide combo
            self._delim_combo.setEnabled(False)
            self._all_rows = rows
        else:
            with open(path, newline="", encoding="utf-8-sig") as f:
                self._raw_text = f.read()
            # Auto-detect delimiter
            detected = detect_delimiter(self._raw_text)
            self._delimiter = detected
            # Update combo to match
            for i in range(self._delim_combo.count()):
                if self._delim_combo.itemData(i) == detected:
                    self._delim_combo.blockSignals(True)
                    self._delim_combo.setCurrentIndex(i)
                    self._delim_combo.blockSignals(False)
                    break
            self._all_rows = parse_csv_rows(self._raw_text, self._delimiter)

        self._populate_table()

    def _on_delim_changed(self, _idx):
        if not self._raw_text:
            return
        key = self._delim_combo.currentData()
        self._delimiter = key
        self._all_rows = parse_csv_rows(self._raw_text, self._delimiter)
        self._populate_table()

    # ── TABLE POPULATION ──────────────────────────────────────────────────────
    def _populate_table(self):
        if not self._all_rows:
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            return

        header = self._all_rows[0]
        data   = self._all_rows[1:]
        self._header = header
        self._expected_cols = len(header)

        self._table.blockSignals(True)
        self._table.setColumnCount(len(header))
        self._table.setHorizontalHeaderLabels(header)
        self._table.setRowCount(len(data))

        error_rows = []
        for r, row in enumerate(data):
            n = len(row)
            is_error = (n != self._expected_cols)
            if is_error:
                error_rows.append(r + 1)   # 1-based for display

            for c in range(self._expected_cols):
                val = row[c] if c < len(row) else ""
                item = QTableWidgetItem(val)
                if is_error:
                    item.setBackground(QBrush(_COLOR_ERR))
                    item.setToolTip(
                        f"⚠ Row has {n} columns, expected {self._expected_cols}"
                    )
                self._table.setItem(r, c, item)

            # If row is shorter, fill missing cells with error bg
            for c in range(len(row), self._expected_cols):
                item = QTableWidgetItem("")
                item.setBackground(QBrush(_COLOR_ERR))
                item.setToolTip(f"⚠ Missing column value")
                self._table.setItem(r, c, item)

        self._table.blockSignals(False)
        self._table.resizeColumnsToContents()

        # Stats
        total = len(data)
        n_err = len(error_rows)
        self._stats_bar.setText(
            f"  {total} data rows  ·  {len(header)} columns"
            + (f"  ·  ⚠ {n_err} rows with wrong column count" if n_err else "  ·  ✔ No structural errors")
        )

        # Error banner
        if error_rows:
            sample = error_rows[:5]
            more = len(error_rows) - 5
            msg = "⚠  Rows with wrong column count: " + ", ".join(str(r) for r in sample)
            if more > 0:
                msg += f" … and {more} more"
            self._error_banner.setText(msg)
            self._error_banner.setVisible(True)
            self._lbl_errors.setText(f"⚠  {n_err} error(s)")
        else:
            self._error_banner.setVisible(False)
            self._lbl_errors.setText("")

    # ── SORTING ───────────────────────────────────────────────────────────────
    def _show_sort_menu(self):
        if not self._header:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{COLORS['bg_secondary']};border:1px solid {COLORS['border']};"
            f"border-radius:6px;padding:4px;}}"
            f"QMenu::item{{padding:6px 20px;color:{COLORS['text_primary']};}}"
            f"QMenu::item:selected{{background:{COLORS['bg_hover']};}}"
            f"QMenu::separator{{height:1px;background:{COLORS['border']};margin:4px 8px;}}"
        )

        for col_idx, col_name in enumerate(self._header):
            sub = menu.addMenu(f"  {col_name}")
            sub.setStyleSheet(menu.styleSheet())
            sub.addAction("A → Z  (alphabetical)",
                lambda ci=col_idx: self._sort_table(ci, "alpha", False))
            sub.addAction("Z → A  (alphabetical desc)",
                lambda ci=col_idx: self._sort_table(ci, "alpha", True))
            sub.addSeparator()
            sub.addAction("0 → 9  (numeric)",
                lambda ci=col_idx: self._sort_table(ci, "numeric", False))
            sub.addAction("9 → 0  (numeric desc)",
                lambda ci=col_idx: self._sort_table(ci, "numeric", True))
            sub.addSeparator()
            sub.addAction("Shortest first  (string length)",
                lambda ci=col_idx: self._sort_table(ci, "length", False))
            sub.addAction("Longest first  (string length)",
                lambda ci=col_idx: self._sort_table(ci, "length", True))

        menu.exec_(self._sort_btn.mapToGlobal(
            self._sort_btn.rect().bottomLeft()))

    def _sort_table(self, col_idx: int, mode: str, reverse: bool):
        rows = []
        for r in range(self._table.rowCount()):
            row = [
                (self._table.item(r, c).text() if self._table.item(r, c) else "")
                for c in range(self._table.columnCount())
            ]
            rows.append(row)

        def key_fn(row):
            val = row[col_idx] if col_idx < len(row) else ""
            if mode == "alpha":
                return val.lower()
            elif mode == "numeric":
                try: return float(val)
                except: return float('inf') if not reverse else float('-inf')
            elif mode == "length":
                return len(val)
            return val

        rows.sort(key=key_fn, reverse=reverse)

        self._table.blockSignals(True)
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = self._table.item(r, c) or QTableWidgetItem()
                item.setText(val)
                self._table.setItem(r, c, item)
        self._table.blockSignals(False)

    # ── ROW OPERATIONS ────────────────────────────────────────────────────────
    def _add_row(self):
        r = self._table.rowCount()
        self._table.insertRow(r)
        for c in range(self._table.columnCount()):
            self._table.setItem(r, c, QTableWidgetItem(""))
        self._table.scrollToBottom()
        self._table.setCurrentCell(r, 0)

    def _delete_selected_rows(self):
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        reply = QMessageBox.question(
            self, "Delete rows", f"Delete {len(rows)} selected row(s)?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for r in rows:
                self._table.removeRow(r)

    def _context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{COLORS['bg_secondary']};border:1px solid {COLORS['border']};}}"
            f"QMenu::item{{padding:6px 20px;color:{COLORS['text_primary']};}}"
            f"QMenu::item:selected{{background:{COLORS['bg_hover']};}}"
        )
        menu.addAction("＋  Insert row above", self._insert_row_above)
        menu.addAction("＋  Insert row below", self._insert_row_below)
        menu.addSeparator()
        menu.addAction("🗑  Delete selected rows", self._delete_selected_rows)
        menu.exec_(self._table.viewport().mapToGlobal(pos))

    def _insert_row_above(self):
        r = self._table.currentRow()
        if r < 0: r = 0
        self._table.insertRow(r)
        for c in range(self._table.columnCount()):
            self._table.setItem(r, c, QTableWidgetItem(""))

    def _insert_row_below(self):
        r = self._table.currentRow()
        self._table.insertRow(r + 1)
        for c in range(self._table.columnCount()):
            self._table.setItem(r + 1, c, QTableWidgetItem(""))

    # ── GET DATA ──────────────────────────────────────────────────────────────
    def get_table_rows(self) -> list:
        """Return current table contents as list of lists (no header)."""
        rows = []
        for r in range(self._table.rowCount()):
            row = [
                (self._table.item(r, c).text() if self._table.item(r, c) else "")
                for c in range(self._table.columnCount())
            ]
            rows.append(row)
        return rows

    # ── IMPORT ────────────────────────────────────────────────────────────────
    def _do_import(self):
        if not self._header:
            QMessageBox.warning(self, "No data", "Load a file first.")
            return
        rows = self.get_table_rows()
        self.import_requested.emit(rows, self._header)
        self.accept()
