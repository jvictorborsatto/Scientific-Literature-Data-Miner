"""
SLDM — Main Window  (v5 — light theme)
"""

import os, json, tempfile, shutil
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QTabWidget, QLabel, QToolBar, QFileDialog,
    QStatusBar, QApplication, QMessageBox, QInputDialog,
    QPushButton, QAction
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QKeySequence

from core.theme import COLORS
from modules.module_analysis import AnalysisWorkspace
from modules.module_combine  import CombineModule
from modules.module_search   import SearchModule


MAX_ANALYSES = 5

ANALYSIS_COLORS = [
    "#4e9af1", "#2ecc71", "#e67e22", "#9b59b6", "#e74c3c",
]


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self._analyses    = []
        self._combine_mod = None
        self._search_mod  = None
        self._project_path = None
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        self._new_session()

    # ── UI setup ──────────────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle("SLDM — Scientific Literature Data Miner")
        self.resize(1400, 860)
        self.setMinimumSize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        self._header_widget = self._make_header()
        ml.addWidget(self._header_widget)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)
        self.tabs.setStyleSheet(self._tab_style())
        self.tabs.currentChanged.connect(self._on_tab_changed)
        ml.addWidget(self.tabs, 1)

    def _tab_style(self):
        return f"""
        QTabWidget::pane {{border:none;background:{COLORS["bg_primary"]};}}
        QTabBar::tab {{
            background:{COLORS["bg_tertiary"]};color:{COLORS["text_muted"]};
            padding:8px 18px;border:none;
            border-right:1px solid {COLORS["border"]};font-size:9pt;
        }}
        QTabBar::tab:selected {{
            background:{COLORS["bg_primary"]};color:{COLORS["accent_blue"]};
            border-bottom:2px solid {COLORS["accent_blue"]};
        }}
        QTabBar::tab:hover:!selected {{
            background:{COLORS["bg_hover"]};color:{COLORS["text_primary"]};
        }}
        """

    def _make_header(self):
        hdr = QWidget()
        hdr.setObjectName("mainHeader")
        hdr.setFixedHeight(54)
        hdr.setStyleSheet(
            f"background:{COLORS['bg_secondary']};"
            f"border-bottom:1px solid {COLORS['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 16, 0)
        hl.setSpacing(12)

        icon = QLabel("⚗")
        icon.setStyleSheet(
            f"font-size:20px;"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {COLORS['accent_blue']},stop:1 {COLORS['accent_teal']});"
            "border-radius:8px;padding:4px 8px;color:white;"
        )
        txt = QLabel("SLDM")
        txt.setStyleSheet(
            f"font-size:14pt;font-weight:700;color:{COLORS['text_primary']};"
            "background:transparent;border:none;"
        )
        sub = QLabel("Scientific Literature Data Miner")
        sub.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_secondary']};background:transparent;border:none;"
        )
        stk = QWidget(); stk.setStyleSheet("background:transparent;")
        sl = QVBoxLayout(stk); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)
        sl.addWidget(txt); sl.addWidget(sub)
        hl.addWidget(icon); hl.addWidget(stk)

        sep = QWidget(); sep.setFixedSize(1,28)
        sep.setStyleSheet(f"background:{COLORS['border']};border:none;")
        hl.addWidget(sep)

        self._proj_lbl = QLabel("New Session")
        self._proj_lbl.setStyleSheet(
            f"font-size:10pt;font-weight:600;color:{COLORS['text_secondary']};"
            "background:transparent;border:none;padding:2px 6px;border-radius:4px;"
        )
        self._proj_lbl.setToolTip("Double-click to rename session")
        self._proj_lbl.mouseDoubleClickEvent = lambda e: self._rename_session()
        hl.addWidget(self._proj_lbl)
        hl.addStretch()

        self._path_lbl = QLabel("  (unsaved)")
        self._path_lbl.setStyleSheet(
            f"font-size:8pt;color:{COLORS['text_muted']};"
            "background:transparent;border:none;"
        )
        hl.addWidget(self._path_lbl)

        return hdr

    def _refresh_dynamic_styles(self):
        """Legacy helper — kept for compatibility."""
        pass

    def _setup_menu(self):
        mb = self.menuBar()

        # ── File ──────────────────────────────────────────────────────────────
        fm = mb.addMenu("File")
        fm.addAction("New Session",      self._new_session,     QKeySequence.New)
        fm.addAction("Open Session…",    self._open_session,    QKeySequence.Open)
        fm.addSeparator()
        fm.addAction("Save Session",     self._save_session,    QKeySequence.Save)
        fm.addAction("Save Session As…", self._save_session_as, QKeySequence.SaveAs)
        fm.addSeparator()
        fm.addAction("Exit",             self.close,            QKeySequence.Quit)

        # ── Analyses ──────────────────────────────────────────────────────────
        am = mb.addMenu("Analyses")
        am.addAction("Add Analysis",            self._add_analysis)
        am.addAction("Remove Current Analysis", self._remove_analysis)

        # ── View ──────────────────────────────────────────────────────────────
        vm = mb.addMenu("View")
        vm.addAction("Zoom In",  lambda: None)   # placeholder for future
        vm.menuAction().setVisible(False)         # hide View menu entirely for now

        # ── Help ──────────────────────────────────────────────────────────────
        hm = mb.addMenu("Help")
        hm.addAction("User Guide",         self._show_user_guide)
        hm.addAction("Keyboard Shortcuts", self._show_shortcuts)
        hm.addSeparator()
        hm.addAction("About SLDM",         self._show_about)

    def _setup_toolbar(self):
        tb = QToolBar("Main"); tb.setMovable(False)
        tb.setIconSize(QSize(16,16))
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        a_new  = tb.addAction("📁  New",    self._new_session)
        a_open = tb.addAction("📂  Open",   self._open_session)
        a_save = tb.addAction("💾  Save",   self._save_session)
        a_new.setToolTip(
            "New Session  (Ctrl+N)\n"
            "Create a brand-new empty session. Save first if you have unsaved work."
        )
        a_open.setToolTip(
            "Open Session  (Ctrl+O)\n"
            "Load a previously saved .sldmsession file."
        )
        a_save.setToolTip(
            "Save Session  (Ctrl+S)\n"
            "Save all open Analyses and the session layout to disk."
        )

        tb.addSeparator()
        a_add = tb.addAction("➕  Add Analysis",   self._add_analysis)
        a_rem = tb.addAction("🗑  Remove Analysis", self._remove_analysis)
        a_add.setToolTip(
            "Add a new Analysis workspace to this session.\n"
            "Each Analysis has its own database, Mining, and Visualization.\n"
            "Up to 5 Analyses can be open simultaneously."
        )
        a_rem.setToolTip(
            "Remove the currently visible Analysis from the session.\n"
            "The database file on disk is NOT deleted."
        )

    def _setup_statusbar(self):
        sb = QStatusBar(); self.setStatusBar(sb)
        self.status_msg = QLabel("Ready")
        sb.addWidget(self.status_msg)
        self.status_right = QLabel("")
        self.status_right.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:8pt;"
        )
        sb.addPermanentWidget(self.status_right)

    # ── Session management ────────────────────────────────────────────────────
    def _new_session(self):
        self._project_path = None
        self._proj_lbl.setText("New Session")
        self._path_lbl.setText("  (unsaved)")
        self.setWindowTitle("SLDM — New Session")
        self._build_tabs([])
        self.status_msg.setText("New session created.")

    def _open_session(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Session", "",
            "SLDM Session (*.sldmsession);;All Files (*)"
        )
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("session_name","Session")
            analyses_data = data.get("analyses", [])
            self._project_path = path
            self._proj_lbl.setText(name)
            self._path_lbl.setText(f"  {os.path.basename(path)}")
            self.setWindowTitle(f"SLDM — {name}")
            self._build_tabs(analyses_data)
            self.status_msg.setText(f"Opened: {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Cannot open session:\n{exc}")

    def _save_session(self):
        if self._project_path:
            self._do_save(self._project_path)
            self.status_msg.setText("Session saved.")
        else:
            self._save_session_as()

    def _save_session_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session As",
            f"{self._proj_lbl.text()}.sldmsession",
            "SLDM Session (*.sldmsession)"
        )
        if not path: return
        if not path.endswith(".sldmsession"): path += ".sldmsession"
        folder = os.path.dirname(path)
        for ana in self._analyses:
            if not ana.is_saved:
                db_path = os.path.join(
                    folder, f"{ana.name.replace(' ','_')}.sldm"
                )
                ana._do_save(db_path)
        self._project_path = path
        self._path_lbl.setText(f"  {os.path.basename(path)}")
        self._do_save(path)
        self.status_msg.setText(f"Saved: {path}")

    def _do_save(self, path: str):
        data = {
            "session_name": self._proj_lbl.text(),
            "analyses": [a.to_dict() for a in self._analyses],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _rename_session(self):
        name, ok = QInputDialog.getText(
            self, "Rename Session", "Session name:",
            text=self._proj_lbl.text()
        )
        if ok and name.strip():
            self._proj_lbl.setText(name.strip())
            self.setWindowTitle(f"SLDM — {name.strip()}")

    # ── Tab management ────────────────────────────────────────────────────────
    def _build_tabs(self, analyses_data: list):
        self.tabs.clear()
        self._analyses = []
        self._combine_mod = CombineModule()
        self._search_mod  = SearchModule()

        if analyses_data:
            for d in analyses_data:
                self._add_analysis_from_dict(d)
        else:
            self._add_fresh_analysis("Analysis 1")

        self._add_plus_tab()
        self._add_combine_tab()
        self._add_search_tab()
        self._sync_combine()

    def _add_fresh_analysis(self, name: str = None):
        if len(self._analyses) >= MAX_ANALYSES:
            QMessageBox.information(
                self, "Limit reached",
                f"Maximum of {MAX_ANALYSES} Analyses allowed."
            )
            return None
        n = len(self._analyses) + 1
        name = name or f"Analysis {n}"
        ws = AnalysisWorkspace(name=name)
        ws.data_changed.connect(self._on_data_changed)
        ws.name_changed.connect(lambda nm, w=ws: self._on_ana_renamed(nm, w))
        self._analyses.append(ws)

        insert_idx = self._combine_insert_pos()
        self.tabs.insertTab(insert_idx, ws, f"  {name}  ")
        self._recolor_all_tabs()
        return ws

    def _add_analysis_from_dict(self, d: dict):
        n = len(self._analyses) + 1
        ws = AnalysisWorkspace.from_dict(d)
        ws.data_changed.connect(self._on_data_changed)
        ws.name_changed.connect(lambda nm, w=ws: self._on_ana_renamed(nm, w))
        self._analyses.append(ws)
        self.tabs.addTab(ws, f"  {ws.name}  ")
        self._recolor_all_tabs()
        return ws

    def _add_analysis(self):
        if len(self._analyses) >= MAX_ANALYSES:
            QMessageBox.information(
                self, "Limit reached",
                f"Maximum of {MAX_ANALYSES} Analyses allowed."
            ); return
        n = len(self._analyses) + 1
        name, ok = QInputDialog.getText(
            self, "New Analysis", "Analysis name:",
            text=f"Analysis {n}"
        )
        if not ok or not name.strip(): return
        ws = self._add_fresh_analysis(name.strip())
        if ws:
            idx = self.tabs.indexOf(ws)
            self.tabs.setCurrentIndex(idx)
        self._sync_combine()

    def _remove_analysis(self):
        if len(self._analyses) <= 1:
            QMessageBox.information(
                self, "Cannot remove",
                "At least one Analysis must remain."
            ); return
        idx = self.tabs.currentIndex()
        w = self.tabs.widget(idx)
        if w not in self._analyses:
            QMessageBox.information(
                self, "Select an Analysis",
                "Switch to the Analysis tab you want to remove."
            ); return
        reply = QMessageBox.question(
            self, "Remove Analysis",
            f"Remove '{w.name}'? The database file will not be deleted.",
            QMessageBox.Yes | QMessageBox.Cancel
        )
        if reply != QMessageBox.Yes: return
        self._analyses.remove(w)
        self.tabs.removeTab(idx)
        self._recolor_all_tabs()
        self._sync_combine()

    def _add_plus_tab(self):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).strip() == "＋":
                self.tabs.removeTab(i); break
        if len(self._analyses) < MAX_ANALYSES:
            ph = QWidget()
            self.tabs.addTab(ph, " ＋ ")
            self.tabs.setTabToolTip(self.tabs.count()-1,
                                    f"Add Analysis (max {MAX_ANALYSES})")

    def _add_combine_tab(self):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).strip() == "⚡  Combine":
                return
        self.tabs.addTab(self._combine_mod, " ⚡  Combine ")

    def _add_search_tab(self):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).strip() == "🔍  Search":
                return
        self.tabs.addTab(self._search_mod, " 🔍  Search ")

    def _combine_insert_pos(self):
        for i in range(self.tabs.count()):
            t = self.tabs.tabText(i).strip()
            if t in ("＋", "⚡  Combine", "🔍  Search"):
                return i
        return self.tabs.count()

    def _recolor_all_tabs(self):
        for i, ana in enumerate(self._analyses):
            tab_idx = self.tabs.indexOf(ana)
            if tab_idx >= 0:
                color = ANALYSIS_COLORS[i % len(ANALYSIS_COLORS)]
                self._color_tab(tab_idx, color)
        self._add_plus_tab()

    def _color_tab(self, idx, color):
        self.tabs.tabBar().setTabTextColor(idx, Qt.white)

    def _sync_combine(self):
        if self._combine_mod:
            self._combine_mod.set_analyses(self._analyses)
        if self._search_mod:
            self._search_mod.set_analyses(self._analyses)

    # ── Events ────────────────────────────────────────────────────────────────
    def _on_tab_changed(self, idx):
        text = self.tabs.tabText(idx).strip()
        if text == "＋":
            self._add_analysis()
            if self._analyses:
                self.tabs.setCurrentIndex(
                    self.tabs.indexOf(self._analyses[-1])
                )
            return
        w = self.tabs.widget(idx)
        if w and hasattr(w, "refresh"):
            w.refresh()
        self._update_statusbar()

    def _on_data_changed(self):
        self._update_statusbar()
        self._sync_combine()

    def _on_ana_renamed(self, new_name: str, ws: AnalysisWorkspace):
        idx = self.tabs.indexOf(ws)
        if idx >= 0:
            self.tabs.setTabText(idx, f"  {new_name}  ")
        self._sync_combine()

    def _update_statusbar(self):
        total_obj = total_art = total_cit = 0
        for ana in self._analyses:
            try:
                total_obj += len(ana.db.get_objects())
                total_art += len(ana.db.get_articles())
                total_cit += len(ana.db.get_citations())
            except Exception:
                pass
        self.status_right.setText(
            f"Objects: {total_obj}  |  Articles: {total_art}  "
            f"|  Citations: {total_cit}  |  Analyses: {len(self._analyses)}"
        )

    # ── About / shortcuts / user guide ───────────────────────────────────────
    def _show_about(self):
        QMessageBox.about(self, "About SLDM",
            "<b>SLDM — Scientific Literature Data Miner</b><br>"
            "Version 5.0<br><br>"
            "Each <b>Analysis</b> is an independent workspace with its own<br>"
            "database, Object List, Mining, and Visualization.<br><br>"
            "Use <b>Combine</b> to compare objects, parameters and values<br>"
            "across multiple Analyses simultaneously.<br><br>"
            f"Supports up to {MAX_ANALYSES} Analyses per session."
        )

    def _show_shortcuts(self):
        QMessageBox.information(self, "Keyboard Shortcuts",
            "<b>Global</b><br>"
            "Ctrl+N — New Session<br>"
            "Ctrl+O — Open Session<br>"
            "Ctrl+S — Save Session<br>"
            "Ctrl+W — Close (Exit)<br><br>"
            "<b>Tips</b><br>"
            "Double-click the session name in the header to rename it.<br>"
            "Double-click an analysis name bar to rename it.<br>"
            "Click ☀ / 🌙 in the header to toggle the theme."
        )

    def _show_user_guide(self):
        from modules.help_guide import UserGuideDialog
        dlg = UserGuideDialog(self)
        dlg.exec_()

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, "Exit", "Save session before exiting?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
        )
        if reply == QMessageBox.Save:
            self._save_session(); event.accept()
        elif reply == QMessageBox.Discard:
            event.accept()
        else:
            event.ignore()
