"""
SLDM — Analysis Workspace

Each Analysis is a fully self-contained workspace:
  - Its own SQLite database (.sldm file)
  - Object List
  - Article Mining
  - Visualization
  - Open / Save / Rename controls built-in

Up to MAX_ANALYSES (5) can run simultaneously in the main window.
"""

import os, tempfile
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QFileDialog, QMessageBox, QInputDialog, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from core.database import Database
from core.theme import COLORS
from core.widgets import make_btn, Toast
from modules.module_objects import ObjectListModule
from modules.module_mining import MiningModule
from modules.module_viz import VizModule


class AnalysisWorkspace(QWidget):
    """
    Self-contained workspace with its own db, Object List, Mining, and Viz.
    Emits data_changed when any sub-module modifies data.
    Emits name_changed(str) when the analysis is renamed.
    """
    data_changed = pyqtSignal()
    name_changed = pyqtSignal(str)

    def __init__(self, name: str = "Analysis 1", db_path: str = None):
        super().__init__()
        self._name = name
        self._saved_path = db_path   # None = unsaved

        # Create or open database
        if db_path and os.path.isfile(db_path):
            self.db = Database(db_path)
        else:
            tmp = os.path.join(tempfile.gettempdir(),
                               f"sldm_{name.replace(' ','_')}_unsaved.sldm")
            self.db = Database(tmp)

        self._build_ui()

    # ── Properties ────────────────────────────────────────────────────────────
    @property
    def name(self): return self._name

    @property
    def saved_path(self): return self._saved_path

    @property
    def is_saved(self): return bool(self._saved_path)

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ────────────────────────────────────────────────────────────
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 0, 12, 0)
        bl.setSpacing(8)

        self._name_lbl = QLabel(self._name)
        self._name_lbl.setStyleSheet(
            f"font-size:10pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        self._name_lbl.setToolTip("Double-click to rename")
        self._name_lbl.mouseDoubleClickEvent = lambda _: self._rename()
        bl.addWidget(self._name_lbl)

        self._path_lbl = QLabel("  (unsaved)")
        self._path_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;"
        )
        bl.addWidget(self._path_lbl, 1)

        # Badges
        self._bdg_obj  = self._badge("0 obj",  COLORS['accent_blue'])
        self._bdg_art  = self._badge("0 art",  COLORS['accent_teal'])
        self._bdg_cit  = self._badge("0 cit",  COLORS['accent_amber'])
        for b in [self._bdg_obj, self._bdg_art, self._bdg_cit]:
            bl.addWidget(b)

        btn_open = make_btn("📂  Open")
        btn_open.clicked.connect(self._open_db)
        btn_open.setToolTip(
            "Open an existing Analysis database (.sldm file).\n"
            "Loads all Objects, Articles and extraction results."
        )
        btn_save = make_btn("💾  Save")
        btn_save.clicked.connect(self._save_db)
        btn_save.setToolTip(
            "Save this Analysis database to its current file.\n"
            "If not saved yet, you will be asked for a location."
        )
        btn_saveas = make_btn("💾  Save As")
        btn_saveas.clicked.connect(self._save_db_as)
        btn_saveas.setToolTip(
            "Save this Analysis database to a new file name or location.\n"
            "The original file is kept unchanged."
        )
        for b in [btn_open, btn_save, btn_saveas]:
            bl.addWidget(b)

        root.addWidget(bar)

        # ── Sub-tabs ───────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.setDocumentMode(True)
        self._tabs.setStyleSheet(self._tab_style())
        root.addWidget(self._tabs, 1)

        self._build_sub_tabs()

    def _tab_style(self):
        return f"""
        QTabWidget::pane {{
            border: none;
            background: {COLORS['bg_primary']};
        }}
        QTabBar::tab {{
            background: {COLORS['bg_tertiary']};
            color: {COLORS['text_muted']};
            padding: 6px 16px;
            border: none;
            border-right: 1px solid {COLORS['border']};
            font-size: 8.5pt;
        }}
        QTabBar::tab:selected {{
            background: {COLORS['bg_primary']};
            color: {COLORS['accent_blue']};
            border-bottom: 2px solid {COLORS['accent_blue']};
        }}
        QTabBar::tab:hover:!selected {{
            background: {COLORS['bg_hover']};
            color: {COLORS['text_primary']};
        }}
        """

    def _build_sub_tabs(self):
        self._tabs.clear()
        self.mod_objects = ObjectListModule(self.db)
        self.mod_mining  = MiningModule(self.db)
        self.mod_viz     = VizModule(self.db)

        self._tabs.addTab(self.mod_objects, "🔬  Objects")
        self._tabs.addTab(self.mod_mining,  "📄  Mining")
        self._tabs.addTab(self.mod_viz,     "📊  Visualization")

        for mod in [self.mod_objects, self.mod_mining, self.mod_viz]:
            mod.data_changed.connect(self._on_sub_changed)

        self._tabs.currentChanged.connect(self._on_sub_tab_changed)
        self._refresh_badges()

    def _badge(self, text, color):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"background:{color}18;color:{color};"
            f"border:1px solid {color}44;border-radius:8px;"
            "padding:1px 8px;font-size:7.5pt;font-weight:600;"
        )
        return lbl

    # ── Sub-module events ──────────────────────────────────────────────────────
    def _on_sub_changed(self):
        self._refresh_badges()
        # Mark all sub-tabs as needing refresh on next visit
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if w:
                w._tab_loaded = False
        self.data_changed.emit()

    def _on_sub_tab_changed(self, idx):
        w = self._tabs.widget(idx)
        if w and hasattr(w, "refresh"):
            # Only refresh if tab hasn't been loaded yet or explicitly dirty
            if not getattr(w, "_tab_loaded", False):
                w.refresh()
                w._tab_loaded = True

    def _refresh_badges(self):
        if not self.db: return
        try:
            objs = len(self.db.get_objects())
            arts = len(self.db.get_articles())
            cits = len(self.db.get_citations())
            self._bdg_obj.setText(f"{objs} obj")
            self._bdg_art.setText(f"{arts} art")
            self._bdg_cit.setText(f"{cits} cit")
        except Exception:
            pass

    def refresh(self):
        self._refresh_badges()
        idx = self._tabs.currentIndex()
        w = self._tabs.widget(idx)
        if w and hasattr(w, "refresh"):
            w.refresh()

    def _refresh_theme(self):
        """Re-apply inline styles that embed COLORS after a theme switch."""
        # Top bar
        bar = self._name_lbl.parent()
        if bar:
            bar.setStyleSheet(
                f"background:{COLORS['bg_secondary']};"
                f"border-bottom:1px solid {COLORS['border']};"
            )
        self._name_lbl.setStyleSheet(
            f"font-size:10pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        self._path_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;"
        )
        # Badges — recreate with correct colours
        for bdg, color in [
            (self._bdg_obj, COLORS['accent_blue']),
            (self._bdg_art, COLORS['accent_teal']),
            (self._bdg_cit, COLORS['accent_amber']),
        ]:
            bdg.setStyleSheet(
                f"background:{color}18;color:{color};"
                f"border:1px solid {color}44;border-radius:8px;"
                "padding:1px 8px;font-size:7.5pt;font-weight:600;"
            )
        self._tabs.setStyleSheet(self._tab_style())

    # ── DB management ──────────────────────────────────────────────────────────
    def _open_db(self):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Open database for {self._name}",
            "", "SLDM Database (*.sldm);;All Files (*)"
        )
        if not path: return
        self.db = Database(path)
        self._saved_path = path
        self._path_lbl.setText(f"  {os.path.basename(path)}")
        self._build_sub_tabs()
        self.data_changed.emit()

    def _save_db(self):
        if self._saved_path:
            self._do_save(self._saved_path)
        else:
            self._save_db_as()

    def _save_db_as(self):
        default = f"{self._name.replace(' ','_')}.sldm"
        path, _ = QFileDialog.getSaveFileName(
            self, f"Save {self._name}", default,
            "SLDM Database (*.sldm)"
        )
        if not path: return
        if not path.endswith(".sldm"): path += ".sldm"
        self._do_save(path)
        self._saved_path = path
        self._path_lbl.setText(f"  {os.path.basename(path)}")
        Toast.show_toast(self, f"Saved: {os.path.basename(path)}", "success")

    def _do_save(self, path: str):
        import shutil
        if self.db.path != path:
            shutil.copy2(self.db.path, path)
            self.db = Database(path)
            self._saved_path = path

    def _rename(self):
        name, ok = QInputDialog.getText(
            self, "Rename Analysis", "New name:", text=self._name
        )
        if ok and name.strip():
            self._name = name.strip()
            self._name_lbl.setText(self._name)
            self.name_changed.emit(self._name)

    # ── Serialization (for project save/load) ──────────────────────────────────
    def to_dict(self) -> dict:
        return {"name": self._name, "db_path": self._saved_path or ""}

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisWorkspace":
        return cls(name=d.get("name","Analysis"),
                   db_path=d.get("db_path") or None)
