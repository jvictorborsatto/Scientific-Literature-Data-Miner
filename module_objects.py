"""
SLDM — Module 1: Object List
Define and manage scientific objects (compounds, species, genes, etc.)
"""

import json
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QFormLayout, QLineEdit, QTextEdit, QFileDialog, QMessageBox,
    QAbstractItemView, QSplitter, QFrame, QComboBox,
    QGridLayout, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal, QSortFilterProxyModel
from PyQt5.QtGui import QColor, QFont

from core.database import Database
from core.widgets import StatCard, Panel, SearchBar, make_btn, EmptyState, Toast
from core.theme import COLORS
from modules.csv_editor import CsvEditorDialog, SUPPORTED_FILTER


class ObjectListModule(QWidget):
    data_changed = pyqtSignal()

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(14)

        # ── Page header
        hdr = QHBoxLayout()
        title = QLabel("Object List")
        title.setStyleSheet(f"font-size: 15pt; font-weight: 700; color: {COLORS['text_primary']}; background: transparent; border: none;")
        sub = QLabel("Define the scientific objects to be mined across literature")
        sub.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_secondary']}; background: transparent; border: none;")
        t_stack = QVBoxLayout(); t_stack.setSpacing(2); t_stack.addWidget(title); t_stack.addWidget(sub)
        hdr.addLayout(t_stack)
        hdr.addStretch()
        btn_import = make_btn("⬆  Import CSV", primary=False)
        btn_export = make_btn("⬇  Export CSV", flat=True)
        btn_add    = make_btn("＋  Add Object", primary=True)
        btn_import.clicked.connect(self._import_csv)
        btn_export.clicked.connect(self._export_csv)
        btn_add.clicked.connect(self._add_object)
        hdr.addWidget(btn_import); hdr.addWidget(btn_export); hdr.addWidget(btn_add)
        root.addLayout(hdr)

        # ── Stats row
        self.stats_row = QHBoxLayout()
        self.stat_total = StatCard("Total Objects",     "0", COLORS["accent_blue"],   "🔬")
        self.stat_cats  = StatCard("Categories",        "0", COLORS["accent_teal"],   "📂")
        self.stat_sub   = StatCard("Subcategories",     "0", COLORS["accent_amber"],  "🏷️")
        self.stat_syn   = StatCard("Total Synonyms",    "0", COLORS["accent_violet"], "🔗")
        for s in [self.stat_total, self.stat_cats, self.stat_sub, self.stat_syn]:
            self.stats_row.addWidget(s)
        root.addLayout(self.stats_row)

        # ── Search + filter bar
        filter_row = QHBoxLayout()
        self.search = SearchBar("Search objects, categories…")
        self.search.textChanged.connect(self._filter_table)
        filter_row.addWidget(self.search)
        root.addLayout(filter_row)

        # No-match feedback label (hidden by default)
        self._no_match_lbl = QLabel("No matching objects found.")
        self._no_match_lbl.setAlignment(Qt.AlignCenter)
        self._no_match_lbl.setStyleSheet(
            f"font-size:9pt;color:{COLORS['text_muted']};background:transparent;border:none;padding:8px;"
        )
        self._no_match_lbl.hide()
        root.addWidget(self._no_match_lbl)

        # ── Table  (columns built dynamically in refresh())
        panel = Panel("Objects Registry", "🔬")
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda idx: self._edit_selected())
        self.table.setSortingEnabled(True)
        self.table.setShowGrid(False)

        btn_edit = panel.add_header_button("✏  Edit")
        btn_del  = panel.add_header_button("🗑  Delete", danger=True)
        btn_edit.clicked.connect(self._edit_selected)
        btn_del.clicked.connect(self._delete_selected)

        panel.add_body_widget(self.table)
        panel.set_body_margins(0, 0, 0, 0)
        root.addWidget(panel)

        # ── CSV format hint
        hint = QLabel("CSV format: object; category_1; category_2; … category_N; synonyms (separated by ;); notes")
        hint.setStyleSheet(f"font-size: 8pt; color: {COLORS['text_muted']}; background: transparent; border: none; padding: 4px 0;")
        root.addWidget(hint)

    # ── DATA ──────────────────────────────────────────────────────────────────
    def refresh(self):
        rows = self.db.get_objects()

        # Determine max number of category levels across all objects
        max_cats = max((len(o.get("categories") or []) for o in rows), default=0)
        max_cats = max(max_cats, 1)   # always at least 1 column

        # Build dynamic column headers: Object | Cat 1 | Cat 2 | … | Synonyms | Notes
        cat_headers = [f"Category {i+1}" for i in range(max_cats)]
        headers = ["Object"] + cat_headers + ["Synonyms", "Notes"]
        n_cols = len(headers)
        syn_col  = n_cols - 2
        note_col = n_cols - 1

        self.table.setSortingEnabled(False)
        self.table.setColumnCount(n_cols)
        self.table.setHorizontalHeaderLabels(headers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for ci in range(1, max_cats + 1):
            hh.setSectionResizeMode(ci, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(syn_col,  QHeaderView.Stretch)
        hh.setSectionResizeMode(note_col, QHeaderView.Stretch)

        CAT_COLORS = [COLORS["accent_blue"], COLORS["accent_teal"],
                      COLORS["accent_violet"], COLORS["accent_amber"],
                      COLORS["accent_green"]]

        self.table.setRowCount(len(rows))
        for i, obj in enumerate(rows):
            cats = obj.get("categories") or []
            self.table.setItem(i, 0, self._item(obj["name"], bold=True))
            for ci in range(max_cats):
                val   = cats[ci] if ci < len(cats) else ""
                color = CAT_COLORS[ci % len(CAT_COLORS)]
                self.table.setItem(i, ci + 1, self._colored_item(val, color))
            syns = json.loads(obj["synonyms"]) if isinstance(obj["synonyms"], str) else (obj["synonyms"] or [])
            self.table.setItem(i, syn_col,  self._item(", ".join(syns), muted=True))
            self.table.setItem(i, note_col, self._item(obj["notes"] or "", muted=True))
            self.table.item(i, 0).setData(Qt.UserRole, obj["id"])
        self.table.setSortingEnabled(True)

        # Update stats: unique values per category level
        all_cats = [set() for _ in range(max_cats)]
        for obj in rows:
            for ci, val in enumerate(obj.get("categories") or []):
                if val and ci < max_cats:
                    all_cats[ci].add(val)
        total_syn = sum(
            len(json.loads(o["synonyms"]) if isinstance(o["synonyms"], str) else (o["synonyms"] or []))
            for o in rows
        )
        self.stat_total.set_value(len(rows))
        self.stat_cats.set_value(len(all_cats[0]) if all_cats else 0)
        self.stat_sub.set_value(len(all_cats[1]) if len(all_cats) > 1 else 0)
        self.stat_syn.set_value(total_syn)

    def _item(self, text, bold=False, muted=False):
        it = QTableWidgetItem(str(text) if text else "")
        if bold:
            f = it.font(); f.setWeight(QFont.DemiBold); it.setFont(f)
        if muted:
            it.setForeground(QColor(COLORS["text_secondary"]))
        return it

    def _colored_item(self, text, color):
        it = QTableWidgetItem(str(text) if text else "")
        if text:
            it.setForeground(QColor(color))
        else:
            it.setForeground(QColor(COLORS["text_muted"]))
        return it

    def _filter_table(self, text):
        visible = 0
        for i in range(self.table.rowCount()):
            match = any(
                text.lower() in (self.table.item(i, c).text().lower() if self.table.item(i, c) else "")
                for c in range(self.table.columnCount())
            )
            self.table.setRowHidden(i, not match)
            if match:
                visible += 1
        has_filter = bool(text.strip())
        self._no_match_lbl.setVisible(has_filter and visible == 0)

    # ── ACTIONS ───────────────────────────────────────────────────────────────
    def _add_object(self):
        dlg = ObjectDialog(self)
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            try:
                self.db.add_object(**d)
                self.refresh()
                self.data_changed.emit()
                Toast.show_toast(self, "Object added", "success")
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _edit_selected(self):
        rows_sel = self.table.selectedItems()
        if not rows_sel: return
        row = self.table.currentRow()
        oid = self.table.item(row, 0).data(Qt.UserRole) if self.table.item(row, 0) else None
        if not oid: return
        objs = {o["id"]: o for o in self.db.get_objects()}
        obj = objs.get(oid)
        if not obj: return
        syns = json.loads(obj["synonyms"]) if isinstance(obj["synonyms"], str) else (obj["synonyms"] or [])
        dlg = ObjectDialog(self, defaults={
            "name": obj["name"],
            "categories": obj.get("categories") or [],
            "synonyms": syns,
            "notes": obj.get("notes", "")
        })
        if dlg.exec_() == QDialog.Accepted:
            d = dlg.get_data()
            self.db.update_object(oid, **d)
            self.refresh()
            self.data_changed.emit()
            Toast.show_toast(self, "Object updated", "success")

    def _delete_selected(self):
        rows = list({idx.row() for idx in self.table.selectedIndexes()})
        if not rows: return
        reply = QMessageBox.question(self, "Delete", f"Delete {len(rows)} object(s)?",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes: return
        for row in rows:
            oid = self.table.item(row, 0).data(Qt.UserRole) if self.table.item(row, 0) else None
            if oid: self.db.delete_object(oid)
        self.refresh()
        self.data_changed.emit()
        Toast.show_toast(self, f"Deleted {len(rows)} object(s)", "info")

    def _import_csv_from_path(self, path: str):
        """Called externally (e.g. toolbar) with a path already chosen."""
        self._open_csv_editor(path)

    def _import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Spreadsheet", "",
            SUPPORTED_FILTER
        )
        if not path:
            return
        self._open_csv_editor(path)

    def _open_csv_editor(self, path: str):
        """Open the full spreadsheet editor dialog, then map columns on confirm."""
        dlg = CsvEditorDialog(self, filepath=path)
        dlg.import_requested.connect(self._on_editor_import)
        dlg.exec_()

    def _on_editor_import(self, data_rows: list, header: list):
        """Called when user confirms import in the CSV editor."""
        preview = data_rows[:5]
        preview_dicts = [dict(zip(header, row)) for row in preview]
        dlg = ColumnMappingDialog(self, header, preview_dicts)
        if dlg.exec_() != QDialog.Accepted:
            return
        mapping = dlg.get_mapping()

        name_col     = mapping.get('name_col', '')
        syn_col      = mapping.get('synonym_col', '')
        notes_col    = mapping.get('notes_col', '')
        cat_cols     = mapping.get('category_cols', [])   # ordered list

        if not name_col or name_col not in header:
            QMessageBox.warning(self, "Import", "No valid 'Object Name' column selected.")
            return

        name_idx  = header.index(name_col)
        syn_idx   = header.index(syn_col)   if syn_col   and syn_col   in header else -1
        notes_idx = header.index(notes_col) if notes_col and notes_col in header else -1
        cat_idxs  = [header.index(c) for c in cat_cols if c in header]

        # Category 1 → stored as category, Category 2 → subcategory,
        # Category 3+ stored in notes as "Cat3: …; Cat4: …"
        def get_cell(row, idx):
            return row[idx].strip() if 0 <= idx < len(row) else ""

        grouped = {}
        for row in data_rows:
            name = get_cell(row, name_idx)
            if not name:
                continue
            if name not in grouped:
                cats = [get_cell(row, ci) for ci in cat_idxs]
                base_notes = get_cell(row, notes_idx)
                grouped[name] = {
                    'categories': cats,
                    'synonyms':   [],
                    'notes':      base_notes,
                }
            # Synonyms
            if syn_idx >= 0:
                raw_syn = get_cell(row, syn_idx)
                for syn in raw_syn.split(';'):
                    syn = syn.strip()
                    if syn and syn != name and syn not in grouped[name]['synonyms']:
                        grouped[name]['synonyms'].append(syn)

        import sqlite3
        count = 0
        for name, data in grouped.items():
            try:
                self.db.add_object(
                    name=name,
                    categories=data['categories'],
                    synonyms=data['synonyms'],
                    notes=data['notes'],
                )
                count += 1
            except sqlite3.IntegrityError:
                pass

        # Store real column names so the viz module can use them
        if cat_idxs:
            import json as _j
            real_names = [header[ci] for ci in cat_idxs]
            try:
                self.db.set_meta("category_col_names", _j.dumps(real_names))
            except Exception:
                pass

        self.refresh()
        self.data_changed.emit()
        Toast.show_toast(self, f"Imported {count} objects", "success")

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Objects", "objects.csv", "CSV (*.csv)")
        if not path: return
        import csv as _csv
        objs = self.db.get_objects()
        max_cats = max((len(o.get("categories") or []) for o in objs), default=1)
        cat_headers = [f"category_{i+1}" for i in range(max_cats)]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f, delimiter=';')
            w.writerow(["object"] + cat_headers + ["synonyms", "notes"])
            for o in objs:
                cats = o.get("categories") or []
                cat_vals = [(cats[i] if i < len(cats) else "") for i in range(max_cats)]
                syns = json.loads(o["synonyms"]) if isinstance(o["synonyms"], str) else (o["synonyms"] or [])
                w.writerow([o["name"]] + cat_vals + ["; ".join(syns), o.get("notes","") or ""])
        Toast.show_toast(self, "Exported", "success")

    def _context_menu(self, pos):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(f"QMenu {{ background: {COLORS['bg_secondary']}; border: 1px solid {COLORS['border']}; border-radius: 6px; }} QMenu::item {{ padding: 6px 20px; }} QMenu::item:selected {{ background: {COLORS['bg_hover']}; color: {COLORS['text_primary']}; }}")
        menu.addAction("✏  Edit", self._edit_selected)
        menu.addAction("🗑  Delete", self._delete_selected)
        menu.exec_(self.table.viewport().mapToGlobal(pos))


# ── OBJECT DIALOG ─────────────────────────────────────────────────────────────
class ObjectDialog(QDialog):
    """Edit/add dialog with dynamic N category fields (Add/Remove buttons)."""

    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        self.setWindowTitle("Object")
        self.setMinimumWidth(480)
        d = defaults or {}
        self.setStyleSheet(
            f"QDialog {{ background: {COLORS['bg_secondary']}; "
            f"border: 1px solid {COLORS['border']}; border-radius: 10px; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)

        title = QLabel("Add Object" if not defaults else "Edit Object")
        title.setStyleSheet(
            f"font-size:12pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        root.addWidget(title)

        self._form = QFormLayout()
        self._form.setSpacing(10)
        self._form.setLabelAlignment(Qt.AlignRight)
        lbl_style = f"color:{COLORS['text_secondary']};font-size:9pt;background:transparent;"

        # Object name
        self.f_name = QLineEdit(d.get("name", ""))
        self.f_name.setPlaceholderText("e.g.  atrazine")
        lbl = QLabel("Object name *"); lbl.setStyleSheet(lbl_style)
        self._form.addRow(lbl, self.f_name)

        # Dynamic category fields
        self._cat_fields = []   # list of QLineEdit
        cats = d.get("categories") or []
        if not cats:
            # Back-compat: build from legacy keys
            if d.get("category"):    cats.append(d["category"])
            if d.get("subcategory"): cats.append(d["subcategory"])
        if not cats:
            cats = [""]   # always at least one field

        self._cat_container = QWidget()
        self._cat_container.setStyleSheet("background:transparent;border:none;")
        self._cat_layout = QVBoxLayout(self._cat_container)
        self._cat_layout.setContentsMargins(0, 0, 0, 0)
        self._cat_layout.setSpacing(6)

        for val in cats:
            self._add_cat_row(val)

        # "+" button to add another category
        add_btn = QPushButton("+ Add Category Level")
        add_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['accent_teal']};"
            f"border:1px dashed {COLORS['border']};border-radius:4px;padding:4px 10px;"
            f"font-size:8pt;}} QPushButton:hover{{background:{COLORS['bg_hover']};}}"
        )
        add_btn.clicked.connect(lambda: self._add_cat_row(""))
        self._cat_layout.addWidget(add_btn)

        cat_wrapper_lbl = QLabel("Categories"); cat_wrapper_lbl.setStyleSheet(lbl_style)
        self._form.addRow(cat_wrapper_lbl, self._cat_container)

        # Synonyms
        syns_val = d.get("synonyms", [])
        if isinstance(syns_val, list): syns_val = ", ".join(syns_val)
        self.f_syn = QLineEdit(syns_val)
        self.f_syn.setPlaceholderText("comma-separated e.g.  ATZ, 2-chloro-4-ethylamine")
        lbl2 = QLabel("Synonyms"); lbl2.setStyleSheet(lbl_style)
        self._form.addRow(lbl2, self.f_syn)

        # Notes
        self.f_notes = QLineEdit(d.get("notes", ""))
        self.f_notes.setPlaceholderText("Optional notes")
        lbl3 = QLabel("Notes"); lbl3.setStyleSheet(lbl_style)
        self._form.addRow(lbl3, self.f_notes)

        root.addLayout(self._form)

        btns = QHBoxLayout(); btns.addStretch()
        cancel = make_btn("Cancel"); ok = make_btn("Save", primary=True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._validate)
        btns.addWidget(cancel); btns.addWidget(ok)
        root.addLayout(btns)

    def _add_cat_row(self, value=""):
        row_w = QWidget(); row_w.setStyleSheet("background:transparent;border:none;")
        row_l = QHBoxLayout(row_w); row_l.setContentsMargins(0,0,0,0); row_l.setSpacing(4)
        idx = len(self._cat_fields) + 1
        field = QLineEdit(value)
        field.setPlaceholderText(f"Category {idx}")
        self._cat_fields.append(field)
        row_l.addWidget(field)
        rem_btn = QPushButton("×")
        rem_btn.setFixedWidth(24)
        rem_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{COLORS['text_muted']};"
            "border:none;font-size:11pt;}} QPushButton:hover{color:#f43f5e;}"
        )
        rem_btn.clicked.connect(lambda: self._remove_cat_row(row_w, field))
        row_l.addWidget(rem_btn)
        # Insert before the "+" button (last item)
        self._cat_layout.insertWidget(self._cat_layout.count() - 1, row_w)

    def _remove_cat_row(self, row_w, field):
        if len(self._cat_fields) <= 1:
            return   # keep at least one
        self._cat_fields.remove(field)
        row_w.setParent(None)
        row_w.deleteLater()

    def _validate(self):
        if not self.f_name.text().strip():
            self.f_name.setStyleSheet(self.f_name.styleSheet() + "border-color:#f43f5e;")
            return
        self.accept()

    def get_data(self) -> dict:
        syns = [s.strip() for s in self.f_syn.text().split(",") if s.strip()]
        cats = [f.text().strip() for f in self._cat_fields]
        # Strip trailing empty categories
        while cats and not cats[-1]:
            cats.pop()
        return {
            "name":       self.f_name.text().strip(),
            "categories": cats,
            "synonyms":   syns,
            "notes":      self.f_notes.text().strip(),
        }


# ── COLUMN MAPPING DIALOG ─────────────────────────────────────────────────────
class ColumnMappingDialog(QDialog):
    """
    Inverted mapping: each ROW = one CSV column.
    User assigns a ROLE to each column via a combo on the right.

    Roles available:
      Object Name *  — required, one per table
      Synonym        — synonym/alias column
      Category 1..N  — unlimited category levels
      Notes          — free-text notes
      Ignore         — skip this column
    """

    # Fixed roles (always present in dropdown)
    _FIXED_ROLES = ["Ignore", "Object Name *", "Synonym", "Notes"]
    # Category roles are generated dynamically up to N columns
    _CAT_PREFIX = "Category "

    def __init__(self, parent, columns: list, preview: list):
        super().__init__(parent)
        self.setWindowTitle("Assign Column Roles")
        self.setMinimumWidth(680)
        self.setMinimumHeight(520)
        self.columns = list(columns)
        self.preview = preview   # list of dicts or list of lists
        self._combos = {}        # col_name → QComboBox
        self._build()

    # ── Build roles list: fixed + "Category 1" .. "Category N" ───────────────
    def _role_options(self):
        n_cat = max(3, len(self.columns))
        cats = [f"{self._CAT_PREFIX}{i}" for i in range(1, n_cat + 1)]
        return self._FIXED_ROLES + cats

    # ── Auto-detect best role for a column name ───────────────────────────────
    def _auto_role(self, col: str, used: set) -> str:
        c = col.lower().strip()
        name_kw    = {'name','compound','object','substance','chemical','compound name','object name'}
        syn_kw     = {'synonym','synonyms','alias','aliases','alt name','alternative'}
        cat_kw     = {'category','class','group','type','family'}
        sub_kw     = {'subcategory','subclass','subgroup','subtype','subfamily','sub'}
        notes_kw   = {'notes','note','remarks','comment','comments','description','info'}

        if c in name_kw    and "Object Name *" not in used: return "Object Name *"
        if c in syn_kw     and "Synonym"        not in used: return "Synonym"
        if c in notes_kw   and "Notes"          not in used: return "Notes"
        if c in cat_kw     and f"{self._CAT_PREFIX}1" not in used: return f"{self._CAT_PREFIX}1"
        if c in sub_kw     and f"{self._CAT_PREFIX}2" not in used: return f"{self._CAT_PREFIX}2"
        return "Ignore"

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)

        # ── Title + description
        title = QLabel("Assign Column Roles")
        title.setStyleSheet(
            f"font-size: 12pt; font-weight: 700; color: {COLORS['text_primary']};"
            "background: transparent; border: none;"
        )
        root.addWidget(title)

        desc = QLabel(
            "For each column in your file, choose what role it plays in SLDM.\n"
            "Only  Object Name  is required. Rows sharing the same Object Name "
            "are merged and their synonyms grouped automatically."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 9pt; color: {COLORS['text_secondary']};"
            "background: transparent; border: none;"
        )
        root.addWidget(desc)

        # ── Mapping table: column name | sample value | role combo
        roles = self._role_options()
        combo_style = (
            f"QComboBox {{ background: {COLORS['bg_tertiary']}; border: 1px solid {COLORS['border']};"
            f" border-radius: 4px; color: {COLORS['text_primary']}; padding: 2px 8px;"
            f" font-size: 8pt; min-width: 140px; }}"
            f"QComboBox::drop-down {{ border: none; padding-right: 6px; }}"
            f"QComboBox QAbstractItemView {{ background: {COLORS['bg_secondary']};"
            f" border: 1px solid {COLORS['border']};"
            f" selection-background-color: {COLORS['bg_hover']};"
            f" color: {COLORS['text_primary']}; }}"
        )

        map_frame = QFrame()
        map_frame.setStyleSheet(
            f"background: {COLORS['bg_card']}; border: 1px solid {COLORS['border']};"
            "border-radius: 8px;"
        )
        grid = QGridLayout(map_frame)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setSpacing(6)
        grid.setColumnStretch(1, 1)

        hdr_style = (
            f"font-size: 8pt; font-weight: 700; color: {COLORS['text_muted']};"
            "text-transform: uppercase; background: transparent; border: none;"
        )
        for col_idx, text in enumerate(["CSV Column", "Sample value", "Assign role as…"]):
            lbl = QLabel(text)
            lbl.setStyleSheet(hdr_style)
            grid.addWidget(lbl, 0, col_idx)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLORS['border']}; border: none;")
        grid.addWidget(sep, 1, 0, 1, 3)

        # Build sample lookup: first non-empty value per column
        sample = {}
        if self.preview:
            for row in self.preview:
                if isinstance(row, dict):
                    for k, v in row.items():
                        if k not in sample and str(v).strip():
                            sample[k] = str(v).strip()
                else:  # list
                    for i, v in enumerate(row):
                        col = self.columns[i] if i < len(self.columns) else str(i)
                        if col not in sample and str(v).strip():
                            sample[col] = str(v).strip()

        used_roles: set = set()
        col_name_style = (
            f"font-size: 9pt; font-weight: 600; color: {COLORS['text_primary']};"
            "background: transparent; border: none;"
        )
        sample_style = (
            f"font-size: 8pt; color: {COLORS['text_muted']};"
            "background: transparent; border: none;"
        )

        for row_idx, col in enumerate(self.columns):
            r = row_idx + 2  # offset for header + separator

            name_lbl = QLabel(col)
            name_lbl.setStyleSheet(col_name_style)
            grid.addWidget(name_lbl, r, 0)

            samp_lbl = QLabel(sample.get(col, "—")[:40])
            samp_lbl.setStyleSheet(sample_style)
            grid.addWidget(samp_lbl, r, 1)

            cb = QComboBox()
            cb.addItems(roles)
            cb.setStyleSheet(combo_style)
            auto = self._auto_role(col, used_roles)
            idx = cb.findText(auto)
            cb.setCurrentIndex(max(0, idx))
            used_roles.add(auto)
            cb.currentTextChanged.connect(self._on_role_changed)
            self._combos[col] = cb
            grid.addWidget(cb, r, 2)

        # Wrap in scroll area in case many columns
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setWidget(map_frame)
        scroll.setMaximumHeight(300)
        root.addWidget(scroll)

        # ── Validation warning label
        self._warn_lbl = QLabel("")
        self._warn_lbl.setStyleSheet(
            "color: #f87171; font-size: 8pt; background: transparent; border: none;"
        )
        root.addWidget(self._warn_lbl)

        # ── Buttons
        root.addStretch()
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = make_btn("Cancel")
        ok = make_btn("Import", primary=True)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._validate)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _on_role_changed(self, _text):
        # Clear warning when user changes anything
        self._warn_lbl.setText("")

    def _validate(self):
        # Check exactly one "Object Name *"
        name_cols = [c for c, cb in self._combos.items()
                     if cb.currentText() == "Object Name *"]
        if not name_cols:
            self._warn_lbl.setText("⚠  Please assign 'Object Name *' to at least one column.")
            return
        if len(name_cols) > 1:
            self._warn_lbl.setText(
                f"⚠  Only one column can be 'Object Name *'. "
                f"Currently assigned to: {', '.join(name_cols)}"
            )
            return
        self.accept()

    def get_mapping(self) -> dict:
        """
        Returns a dict with canonical keys:
          name_col       → column name assigned as Object Name
          synonym_col    → column name for Synonym (or "")
          category_cols  → ordered list of column names for Category 1, 2, …
          notes_col      → column name for Notes (or "")
        """
        result = {
            'name_col':      "",
            'synonym_col':   "",
            'category_cols': [],
            'notes_col':     "",
        }
        cat_map = {}   # "Category N" → col_name
        for col, cb in self._combos.items():
            role = cb.currentText()
            if role == "Object Name *":
                result['name_col'] = col
            elif role == "Synonym":
                result['synonym_col'] = col
            elif role == "Notes":
                result['notes_col'] = col
            elif role.startswith(self._CAT_PREFIX):
                n = int(role[len(self._CAT_PREFIX):])
                cat_map[n] = col
        # Sort category columns by their number
        result['category_cols'] = [cat_map[n] for n in sorted(cat_map)]
        return result
