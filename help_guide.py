"""
SLDM — Help Guide Module
Provides:
  - TOOLTIPS dict  : rich tooltip texts for every interactive widget
  - apply_tooltips(): utility to attach tooltips to widgets by key
  - UserGuideDialog: full usage guide dialog (Help → User Guide)
"""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QTabWidget, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont

# ── Tooltip texts ─────────────────────────────────────────────────────────────
# Keys match the conceptual button/action name throughout the app.
# Use apply_tooltip(widget, key) to attach them.

TOOLTIPS = {
    # ── Toolbar / session controls ────────────────────────────────────────────
    "new_session": (
        "Create a brand-new empty session.\n"
        "Any unsaved work will be lost — save first if needed."
    ),
    "open_session": (
        "Open a previously saved SLDM session file (.sldmsession).\n"
        "The session restores all Analyses and their databases."
    ),
    "save_session": (
        "Save the current session to disk (.sldmsession).\n"
        "Unsaved Analyses are saved automatically alongside the session file."
    ),
    "save_session_as": (
        "Save the session under a new name or location.\n"
        "Useful for creating a copy before making major changes."
    ),
    "add_analysis": (
        "Add a new Analysis workspace to this session.\n"
        "Each Analysis has its own database, Mining, and Visualization.\n"
        "Up to 5 Analyses can be open simultaneously."
    ),
    "remove_analysis": (
        "Remove the currently visible Analysis from the session.\n"
        "The database file on disk is NOT deleted — only removed from view."
    ),
    "toggle_theme": (
        "Switch between Light and Dark interface theme.\n"
        "Your preference is applied immediately."
    ),
    "session_name_label": (
        "The current session name.\n"
        "Double-click to rename it."
    ),

    # ── Analysis workspace ────────────────────────────────────────────────────
    "analysis_open_db": (
        "Open an existing Analysis database (.sldm file).\n"
        "Loads all Objects, Articles and extraction results."
    ),
    "analysis_save_db": (
        "Save this Analysis database to its current file.\n"
        "If not saved yet, you will be asked for a location."
    ),
    "analysis_save_db_as": (
        "Save this Analysis database to a new file name or location.\n"
        "The original file is kept unchanged."
    ),
    "analysis_name_label": (
        "The name of this Analysis workspace.\n"
        "Double-click to rename it."
    ),

    # ── Objects tab ───────────────────────────────────────────────────────────
    "obj_add": (
        "Add a new Object (e.g. a compound, gene, material) to track.\n"
        "You can define synonyms so Mining finds all name variants."
    ),
    "obj_edit": (
        "Edit the selected Object: change its name, synonyms, or notes.\n"
        "Changes affect future Mining runs."
    ),
    "obj_delete": (
        "Delete the selected Object and all its extracted data.\n"
        "This action cannot be undone."
    ),
    "obj_search_bar": (
        "Filter the Object list in real time.\n"
        "Type any part of an object name or synonym."
    ),

    # ── Mining tab ────────────────────────────────────────────────────────────
    "mining_add_pdf": (
        "Import one or more PDF files into this Analysis.\n"
        "SLDM will index their text for extraction."
    ),
    "mining_add_manual": (
        "Add an article entry manually (title, authors, DOI, etc.)\n"
        "without uploading a PDF."
    ),
    "mining_scan_selected": (
        "Run the extraction engine on the selected article(s).\n"
        "Looks for Object mentions, parameters, and values."
    ),
    "mining_scan_all": (
        "Run extraction on ALL articles that have not been scanned yet.\n"
        "May take a while for large collections."
    ),
    "mining_skip_refs": (
        "Toggle whether the References / Bibliography section of each PDF\n"
        "is excluded from extraction (ON = skip references).\n"
        "Recommended ON to avoid false positives."
    ),
    "mining_section_filter": (
        "Choose which PDF sections (Abstract, Introduction, Methods…)\n"
        "are included in or excluded from extraction."
    ),
    "mining_search_btn": (
        "Execute the keyword/object search across all loaded articles.\n"
        "Results appear in the article list below."
    ),
    "mining_zoom_in": (
        "Increase the zoom level of the PDF viewer."
    ),
    "mining_zoom_out": (
        "Decrease the zoom level of the PDF viewer."
    ),
    "mining_fetch_metadata": (
        "Fetch article metadata (title, authors, journal, year) from\n"
        "Crossref online using the DOI entered above."
    ),
    "mining_edit_article": (
        "Edit the metadata of this article (title, authors, journal, DOI)."
    ),
    "mining_delete_article": (
        "Remove this article and all its extracted data from the Analysis.\n"
        "The original PDF file is NOT deleted."
    ),

    # ── Visualization tab ─────────────────────────────────────────────────────
    "viz_plot": (
        "Generate a plot from the current data and settings.\n"
        "Select chart type and axes before clicking."
    ),
    "viz_export": (
        "Export the current chart as an image file (PNG, SVG, PDF)."
    ),
    "viz_clear": (
        "Clear the current chart from the display."
    ),

    # ── Combine tab ───────────────────────────────────────────────────────────
    "combine_refresh": (
        "Refresh the Combine view with the latest data from all Analyses.\n"
        "Run this after adding or editing data in any Analysis."
    ),
    "combine_export": (
        "Export the combined table to a CSV or Excel file."
    ),
    "combine_filter": (
        "Filter the combined results by Object, parameter, or Analysis."
    ),

    # ── Search tab ────────────────────────────────────────────────────────────
    "search_run": (
        "Run the search query across all loaded Analyses.\n"
        "Matches are highlighted in the results table."
    ),
    "search_clear": (
        "Clear the search query and reset the results view."
    ),
    "search_export": (
        "Export the current search results to CSV."
    ),
}


def apply_tooltip(widget, key: str):
    """Attach a tooltip from TOOLTIPS to a widget by key."""
    tip = TOOLTIPS.get(key, "")
    if tip:
        widget.setToolTip(tip)


# ── User Guide Dialog ─────────────────────────────────────────────────────────

_GUIDE_SECTIONS = [
    {
        "title": "🚀  Getting Started",
        "content": """
<h3>What is SLDM?</h3>
<p><b>SLDM (Scientific Literature Data Miner)</b> helps researchers extract, 
organise and compare structured data from scientific PDFs automatically.</p>

<h3>Typical workflow</h3>
<ol>
  <li><b>Create a Session</b> — File → New Session (or Ctrl+N).</li>
  <li><b>Open or create an Analysis</b> — each Analysis is an independent 
      workspace with its own database file (.sldm).</li>
  <li><b>Define your Objects</b> — go to the <i>Objects</i> sub-tab and add 
      the entities you want to track (compounds, genes, materials…).</li>
  <li><b>Import PDFs</b> — switch to the <i>Mining</i> sub-tab and click 
      <i>Add PDF(s)</i>.</li>
  <li><b>Run extraction</b> — click <i>Scan All</i> to extract mentions, 
      parameters and values for every Object.</li>
  <li><b>Visualise results</b> — go to the <i>Visualization</i> sub-tab to 
      plot charts.</li>
  <li><b>Compare Analyses</b> — use the <i>Combine</i> tab to see data from 
      multiple Analyses side by side.</li>
  <li><b>Save your session</b> — File → Save Session (Ctrl+S).</li>
</ol>
""",
    },
    {
        "title": "📂  Sessions & Files",
        "content": """
<h3>Session files (.sldmsession)</h3>
<p>A <b>session</b> is a JSON file that records which Analysis workspaces 
are open and where their databases are located. It does <i>not</i> embed the 
PDF files themselves.</p>

<h3>Analysis databases (.sldm)</h3>
<p>Each Analysis stores its objects, articles, and all extracted data in a 
<b>.sldm</b> file (SQLite database). You can open the same .sldm file in 
different sessions.</p>

<h3>Tips</h3>
<ul>
  <li>Keep the .sldmsession and all .sldm files in the same folder for easy 
      portability.</li>
  <li>Double-click the session name in the top bar to rename it without 
      saving.</li>
  <li>Use <i>Save As</i> to branch a session before making experimental 
      changes.</li>
</ul>
""",
    },
    {
        "title": "🔬  Objects",
        "content": """
<h3>What is an Object?</h3>
<p>An <b>Object</b> is any named entity you want SLDM to find in your 
literature — for example a chemical compound, a protein, a material, or a 
process.</p>

<h3>Synonyms</h3>
<p>Add synonyms (alternative names, abbreviations, IUPAC names…) so the 
mining engine recognises all variants. Example: <i>aspirin</i> → synonyms: 
<i>acetylsalicylic acid</i>, <i>ASA</i>.</p>

<h3>Managing objects</h3>
<ul>
  <li><b>Add</b> — click <i>＋ Add</i> or press the toolbar button.</li>
  <li><b>Edit</b> — double-click an object or use the <i>✏ Edit</i> 
      button.</li>
  <li><b>Delete</b> — select and click <i>🗑 Delete</i>. All extracted 
      data for that object is also removed.</li>
  <li>Use the <b>search bar</b> at the top to filter objects by name.</li>
</ul>
""",
    },
    {
        "title": "📄  Mining",
        "content": """
<h3>Importing articles</h3>
<ul>
  <li><b>Add PDF(s)</b> — imports files and indexes their text.</li>
  <li><b>Add Manually</b> — enter article metadata without a PDF 
      (useful for DOI-only references).</li>
  <li><b>Fetch Metadata</b> — auto-fill title, authors and journal from 
      Crossref using the DOI.</li>
</ul>

<h3>Running extraction</h3>
<ul>
  <li><b>Scan Selected</b> — process only the highlighted articles.</li>
  <li><b>Scan All</b> — process every article that hasn't been scanned yet.</li>
</ul>

<h3>Filtering options</h3>
<ul>
  <li><b>Skip References (ON)</b> — excludes the bibliography section to 
      avoid false positives. Recommended.</li>
  <li><b>Section Filters</b> — include or exclude specific sections 
      (Abstract, Methods, Results…) from extraction.</li>
</ul>

<h3>PDF viewer</h3>
<p>Click an article in the list to open its PDF with extracted mentions 
highlighted. Use <i>＋ Zoom</i> / <i>－ Zoom</i> to adjust size.</p>
""",
    },
    {
        "title": "📊  Visualization",
        "content": """
<h3>Chart types available</h3>
<p>Select from bar charts, scatter plots, box plots, heatmaps and more using 
the chart-type dropdown.</p>

<h3>Configuring axes</h3>
<p>Choose which parameter goes on each axis using the axis selectors. 
You can group by Object, by Analysis, or by article.</p>

<h3>Exporting charts</h3>
<p>Click <i>Export</i> to save the current chart as PNG, SVG or PDF.</p>

<h3>Tips</h3>
<ul>
  <li>Run <i>Scan All</i> first — empty data produces empty charts.</li>
  <li>Use the <i>Combine</i> tab to plot data from multiple Analyses 
      together.</li>
</ul>
""",
    },
    {
        "title": "⚡  Combine",
        "content": """
<h3>Purpose</h3>
<p>The <b>Combine</b> tab merges extracted data from all open Analyses into a 
single table so you can compare results across datasets.</p>

<h3>How to use it</h3>
<ol>
  <li>Make sure at least two Analyses have scanned data.</li>
  <li>Open the <b>Combine</b> tab — data loads automatically.</li>
  <li>Use the <b>filter controls</b> to narrow down by Object, parameter 
      type, or source Analysis.</li>
  <li>Click <b>Export</b> to save the combined table as CSV or Excel.</li>
</ol>

<h3>Refresh</h3>
<p>After adding new data to any Analysis, click <b>Refresh</b> in the 
Combine tab to update the combined view.</p>
""",
    },
    {
        "title": "🔍  Search",
        "content": """
<h3>Full-text search</h3>
<p>The <b>Search</b> tab lets you run keyword queries across the text of all 
imported articles in all open Analyses simultaneously.</p>

<h3>Using search</h3>
<ol>
  <li>Type your query in the search box.</li>
  <li>Click <b>🔍 Search</b> or press Enter.</li>
  <li>Results show matching articles with context snippets.</li>
  <li>Click a result to open the article PDF at that location.</li>
</ol>

<h3>Exporting results</h3>
<p>Use <b>Export</b> to save the result list to CSV.</p>
""",
    },
    {
        "title": "⌨  Shortcuts & Tips",
        "content": """
<h3>Keyboard shortcuts</h3>
<table cellspacing="0" cellpadding="4">
  <tr><td><b>Ctrl+N</b></td><td>New Session</td></tr>
  <tr><td><b>Ctrl+O</b></td><td>Open Session</td></tr>
  <tr><td><b>Ctrl+S</b></td><td>Save Session</td></tr>
  <tr><td><b>Ctrl+W / Alt+F4</b></td><td>Exit</td></tr>
</table>

<h3>Interface tips</h3>
<ul>
  <li>Hover over any button to see a description of what it does.</li>
  <li>Double-click the <b>session name</b> in the top bar to rename it.</li>
  <li>Double-click an <b>Analysis name bar</b> to rename that workspace.</li>
  <li>Click the <b>☀ / 🌙</b> button in the header to toggle themes.</li>
  <li>The <b>＋</b> tab at the end of the tab bar adds a new Analysis.</li>
  <li>Right-click an article or object for a context menu with more 
      options.</li>
  <li>Status bar (bottom) shows live counts of Objects, Articles and 
      Citations across all open Analyses.</li>
</ul>
""",
    },
]


class UserGuideDialog(QDialog):
    """Full usage guide displayed from Help → User Guide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SLDM — User Guide")
        self.resize(820, 620)
        self.setMinimumSize(600, 400)
        self._build_ui()

    def _build_ui(self):
        from core.theme import COLORS

        self.setStyleSheet(
            f"QDialog {{ background: {COLORS['bg_primary']}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setFixedHeight(56)
        hdr.setStyleSheet(
            f"background: {COLORS['bg_secondary']};"
            f"border-bottom: 1px solid {COLORS['border']};"
        )
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(20, 0, 20, 0)
        icon = QLabel("📖")
        icon.setStyleSheet("font-size: 20px; background: transparent;")
        title = QLabel("User Guide")
        title.setStyleSheet(
            f"font-size: 14pt; font-weight: 700; color: {COLORS['text_primary']};"
            "background: transparent;"
        )
        sub = QLabel("SLDM — Scientific Literature Data Miner")
        sub.setStyleSheet(
            f"font-size: 9pt; color: {COLORS['text_secondary']}; background: transparent;"
        )
        stk = QWidget(); stk.setStyleSheet("background: transparent;")
        sl = QVBoxLayout(stk); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(1)
        sl.addWidget(title); sl.addWidget(sub)
        hl.addWidget(icon); hl.addSpacing(8); hl.addWidget(stk); hl.addStretch()
        root.addWidget(hdr)

        # ── Body: sidebar + content ────────────────────────────────────────────
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(200)
        sidebar.setStyleSheet(
            f"background: {COLORS['bg_secondary']};"
            f"border-right: 1px solid {COLORS['border']};"
        )
        sl2 = QVBoxLayout(sidebar)
        sl2.setContentsMargins(0, 8, 0, 8)
        sl2.setSpacing(0)

        # Content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {COLORS['bg_primary']}; border: none; }}"
        )
        content_wrap = QWidget()
        content_wrap.setStyleSheet(f"background: {COLORS['bg_primary']};")
        self._content_layout = QVBoxLayout(content_wrap)
        self._content_layout.setContentsMargins(32, 24, 32, 32)
        self._content_layout.setSpacing(0)
        scroll.setWidget(content_wrap)

        # Build nav buttons
        self._nav_buttons = []
        self._content_label = QLabel()
        self._content_label.setWordWrap(True)
        self._content_label.setTextFormat(Qt.RichText)
        self._content_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._content_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._content_label.setStyleSheet(
            f"color: {COLORS['text_primary']}; background: transparent;"
            "font-size: 10pt; line-height: 1.6;"
        )
        self._content_layout.addWidget(self._content_label)
        self._content_layout.addStretch()

        for i, sec in enumerate(_GUIDE_SECTIONS):
            btn = QPushButton(sec["title"])
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; "
                f"border-left: 3px solid transparent; text-align: left; "
                f"padding: 9px 16px; color: {COLORS['text_secondary']}; font-size: 9pt; }}"
                f"QPushButton:hover {{ background: {COLORS['bg_hover']}; "
                f"color: {COLORS['text_primary']}; }}"
                f"QPushButton:checked {{ background: {COLORS['selection_bg']}; "
                f"color: {COLORS['accent_blue']}; "
                f"border-left: 3px solid {COLORS['accent_blue']}; }}"
            )
            btn.clicked.connect(lambda _, idx=i: self._show_section(idx))
            sl2.addWidget(btn)
            self._nav_buttons.append(btn)

        sl2.addStretch()
        bl.addWidget(sidebar)
        bl.addWidget(scroll, 1)
        root.addWidget(body, 1)

        # ── Footer ────────────────────────────────────────────────────────────
        footer = QWidget()
        footer.setFixedHeight(48)
        footer.setStyleSheet(
            f"background: {COLORS['bg_secondary']};"
            f"border-top: 1px solid {COLORS['border']};"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 0, 20, 0)
        fl.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {COLORS['accent_blue']}; color: white; "
            "border: none; border-radius: 6px; padding: 7px 20px; font-size: 9pt; font-weight: 600; }}"
            "QPushButton:hover { opacity: 0.9; }"
        )
        fl.addWidget(close_btn)
        root.addWidget(footer)

        # Show first section by default
        self._show_section(0)

    def _show_section(self, idx: int):
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)
        sec = _GUIDE_SECTIONS[idx]
        self._content_label.setText(sec["content"])
