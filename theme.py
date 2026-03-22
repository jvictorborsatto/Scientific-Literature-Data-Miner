"""
SLDM Theme System — Dark & Light themes with toggle support.
"""

# ── DARK THEME ─────────────────────────────────────────────────────────────────
DARK_COLORS = {
    "bg_primary":     "#0d1117",
    "bg_secondary":   "#161b22",
    "bg_tertiary":    "#1c2128",
    "bg_card":        "#21262d",
    "bg_hover":       "#2d333b",
    "border":         "#30363d",
    "text_primary":   "#e6edf3",
    "text_secondary": "#8b949e",
    "text_muted":     "#484f58",
    "accent_blue":    "#3d8bfd",
    "accent_teal":    "#2dd4bf",
    "accent_amber":   "#f59e0b",
    "accent_rose":    "#f43f5e",
    "accent_violet":  "#a78bfa",
    "accent_green":   "#34d399",
    "input_bg":       "#161b22",
    "selection_bg":   "#1c2a3e",
}

# ── LIGHT THEME ────────────────────────────────────────────────────────────────
LIGHT_COLORS = {
    "bg_primary":     "#ffffff",
    "bg_secondary":   "#f6f8fa",
    "bg_tertiary":    "#eaeef2",
    "bg_card":        "#f6f8fa",
    "bg_hover":       "#eaeef2",
    "border":         "#d0d7de",
    "text_primary":   "#1f2328",
    "text_secondary": "#636c76",
    "text_muted":     "#9198a1",
    "accent_blue":    "#0969da",
    "accent_teal":    "#0d969a",
    "accent_amber":   "#bf8700",
    "accent_rose":    "#cf222e",
    "accent_violet":  "#8250df",
    "accent_green":   "#1a7f37",
    "input_bg":       "#ffffff",
    "selection_bg":   "#dbeafe",
}

# Active theme (starts light)
_current_theme = "light"
COLORS = dict(LIGHT_COLORS)


def set_theme(theme: str):
    """Switch active theme: 'dark' or 'light'. Updates COLORS in place."""
    global _current_theme
    _current_theme = theme
    src = LIGHT_COLORS if theme == "light" else DARK_COLORS
    COLORS.update(src)


def get_theme() -> str:
    return _current_theme


def _build_stylesheet(c: dict) -> str:
    return f"""
/* ── GLOBAL ─────────────────────────────────────────────── */
QWidget {{
    background-color: {c["bg_primary"]};
    color: {c["text_primary"]};
    font-family: "Segoe UI", "SF Pro Display", Arial, sans-serif;
    font-size: 9pt;
    border: none;
    outline: none;
}}
QMainWindow {{ background-color: {c["bg_primary"]}; }}

/* ── MENU BAR ────────────────────────────────────────────── */
QMenuBar {{
    background-color: {c["bg_secondary"]};
    color: {c["text_primary"]};
    border-bottom: 1px solid {c["border"]};
    padding: 2px 4px;
}}
QMenuBar::item:selected {{
    background-color: {c["bg_hover"]};
    border-radius: 4px;
}}
QMenu {{
    background-color: {c["bg_secondary"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{ padding: 6px 24px 6px 14px; color: {c["text_primary"]}; }}
QMenu::item:selected {{ background-color: {c["bg_hover"]}; color: {c["accent_blue"]}; }}
QMenu::separator {{ height: 1px; background: {c["border"]}; margin: 4px 0; }}

/* ── TOOLBAR ─────────────────────────────────────────────── */
QToolBar {{
    background-color: {c["bg_secondary"]};
    border-bottom: 1px solid {c["border"]};
    padding: 4px 8px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    background: transparent;
    color: {c["text_secondary"]};
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 5px 10px;
    font-size: 9pt;
}}
QToolBar QToolButton:hover {{
    background: {c["bg_hover"]};
    color: {c["text_primary"]};
    border-color: {c["border"]};
}}
QToolBar QToolButton:pressed {{
    background: {c["selection_bg"]};
    color: {c["accent_blue"]};
    border-color: {c["accent_blue"]};
}}

/* ── TABS ────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {c["border"]};
    background: {c["bg_primary"]};
}}
QTabBar {{ background: {c["bg_secondary"]}; }}
QTabBar::tab {{
    background: transparent;
    color: {c["text_secondary"]};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 9px 20px;
    font-size: 9pt;
    font-weight: 500;
    min-width: 100px;
}}
QTabBar::tab:hover {{ color: {c["text_primary"]}; background: {c["bg_hover"]}; }}
QTabBar::tab:selected {{
    color: {c["accent_blue"]};
    border-bottom: 2px solid {c["accent_blue"]};
    background: {c["bg_primary"]};
}}

/* ── SPLITTER ────────────────────────────────────────────── */
QSplitter::handle {{ background: {c["border"]}; width: 1px; height: 1px; }}
QSplitter::handle:hover {{ background: {c["accent_blue"]}; }}

/* ── SCROLLBARS ──────────────────────────────────────────── */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{
    background: {c["bg_secondary"]};
    width: 8px; border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {c["border"]};
    border-radius: 4px; min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{ background: {c["text_muted"]}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {c["bg_secondary"]};
    height: 8px; border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {c["border"]};
    border-radius: 4px; min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c["text_muted"]}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ── TABLE ───────────────────────────────────────────────── */
QTableWidget, QTableView {{
    background: {c["bg_primary"]};
    gridline-color: {c["bg_tertiary"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    selection-background-color: {c["selection_bg"]};
    selection-color: {c["text_primary"]};
    alternate-background-color: {c["bg_secondary"]};
}}
QTableWidget::item, QTableView::item {{ padding: 5px 10px; border: none; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {c["selection_bg"]}; color: {c["text_primary"]};
}}
QHeaderView::section {{
    background: {c["bg_secondary"]};
    color: {c["text_secondary"]};
    border: none;
    border-bottom: 1px solid {c["border"]};
    border-right: 1px solid {c["bg_tertiary"]};
    padding: 6px 10px;
    font-size: 8pt; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px;
}}
QHeaderView::section:hover {{ background: {c["bg_hover"]}; color: {c["text_primary"]}; }}
QHeaderView::section:last {{ border-right: none; }}

/* ── LIST WIDGET ─────────────────────────────────────────── */
QListWidget {{
    background: {c["bg_primary"]};
    border: 1px solid {c["border"]};
    border-radius: 6px; outline: none;
}}
QListWidget::item {{ padding: 0; border-bottom: 1px solid {c["bg_tertiary"]}; }}
QListWidget::item:selected {{ background: {c["selection_bg"]}; color: {c["text_primary"]}; }}
QListWidget::item:hover {{ background: {c["bg_hover"]}; }}

/* ── TREE WIDGET ─────────────────────────────────────────── */
QTreeWidget {{
    background: {c["bg_primary"]};
    border: 1px solid {c["border"]};
    border-radius: 6px; outline: none;
}}
QTreeWidget::item {{ padding: 4px 6px; }}
QTreeWidget::item:selected {{ background: {c["selection_bg"]}; }}
QTreeWidget::item:hover {{ background: {c["bg_hover"]}; }}
QTreeWidget::branch {{ background: transparent; }}

/* ── BUTTONS ─────────────────────────────────────────────── */
QPushButton {{
    background: {c["bg_card"]};
    color: {c["text_primary"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 9pt; font-weight: 500;
}}
QPushButton:hover {{ background: {c["bg_hover"]}; border-color: {c["text_muted"]}; }}
QPushButton:pressed {{ background: {c["bg_tertiary"]}; }}
QPushButton:disabled {{ color: {c["text_muted"]}; border-color: {c["bg_tertiary"]}; }}
QPushButton[primary="true"] {{
    background: {c["accent_blue"]}; color: white; border-color: {c["accent_blue"]};
}}
QPushButton[primary="true"]:hover {{ opacity: 0.9; }}
QPushButton[danger="true"] {{
    background: transparent;
    color: {c["accent_rose"]};
    border-color: {c["accent_rose"]}44;
}}
QPushButton[danger="true"]:hover {{ background: {c["accent_rose"]}18; border-color: {c["accent_rose"]}; }}
QPushButton[flat="true"] {{
    background: transparent; border-color: transparent; color: {c["text_secondary"]};
}}
QPushButton[flat="true"]:hover {{ background: {c["bg_hover"]}; color: {c["text_primary"]}; }}

/* ── INPUTS ──────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {c["input_bg"]};
    color: {c["text_primary"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {c["selection_bg"]};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {c["accent_blue"]}; }}
QLineEdit::placeholder {{ color: {c["text_muted"]}; }}

QComboBox {{
    background: {c["input_bg"]}; color: {c["text_primary"]};
    border: 1px solid {c["border"]}; border-radius: 6px;
    padding: 5px 10px; min-width: 100px;
}}
QComboBox:hover {{ border-color: {c["text_muted"]}; }}
QComboBox:focus {{ border-color: {c["accent_blue"]}; }}
QComboBox::drop-down {{ border: none; padding-right: 8px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {c["text_secondary"]};
    width: 0; height: 0;
}}
QComboBox QAbstractItemView {{
    background: {c["bg_secondary"]}; border: 1px solid {c["border"]};
    border-radius: 6px; selection-background-color: {c["bg_hover"]}; outline: none;
}}

QSpinBox, QDoubleSpinBox {{
    background: {c["input_bg"]}; color: {c["text_primary"]};
    border: 1px solid {c["border"]}; border-radius: 6px; padding: 5px 8px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {c["accent_blue"]}; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {c["bg_hover"]}; border: none; width: 16px;
}}

/* ── CHECKBOX / RADIO ────────────────────────────────────── */
QCheckBox, QRadioButton {{ color: {c["text_secondary"]}; spacing: 8px; }}
QCheckBox:hover, QRadioButton:hover {{ color: {c["text_primary"]}; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px;
    background: {c["input_bg"]};
    border: 1px solid {c["border"]}; border-radius: 3px;
}}
QCheckBox::indicator:checked {{ background: {c["accent_blue"]}; border-color: {c["accent_blue"]}; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QRadioButton::indicator:checked {{ background: {c["accent_blue"]}; border-color: {c["accent_blue"]}; }}

/* ── LABELS ──────────────────────────────────────────────── */
QLabel {{ background: transparent; }}
QLabel[heading="true"] {{ font-size: 13pt; font-weight: 700; color: {c["text_primary"]}; }}
QLabel[subheading="true"] {{ font-size: 10pt; font-weight: 600; color: {c["text_secondary"]}; }}
QLabel[muted="true"] {{ color: {c["text_muted"]}; font-size: 8pt; }}
QLabel[badge="true"] {{
    background: {c["selection_bg"]}; color: {c["accent_blue"]};
    border: 1px solid {c["accent_blue"]}44; border-radius: 10px;
    padding: 1px 8px; font-size: 8pt; font-weight: 600;
}}
QLabel[badge_green="true"] {{
    background: {c["accent_green"]}22; color: {c["accent_green"]};
    border: 1px solid {c["accent_green"]}44; border-radius: 10px; padding: 1px 8px; font-size: 8pt;
}}
QLabel[badge_amber="true"] {{
    background: {c["accent_amber"]}22; color: {c["accent_amber"]};
    border: 1px solid {c["accent_amber"]}44; border-radius: 10px; padding: 1px 8px; font-size: 8pt;
}}

/* ── GROUP BOX ───────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {c["border"]}; border-radius: 8px;
    margin-top: 12px; padding-top: 8px;
    font-weight: 600; color: {c["text_secondary"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: {c["text_secondary"]}; font-size: 8pt;
    letter-spacing: 0.5px; text-transform: uppercase;
}}

/* ── PROGRESS BAR ────────────────────────────────────────── */
QProgressBar {{
    background: {c["bg_card"]}; border: none; border-radius: 3px;
    height: 4px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c["accent_blue"]}, stop:1 {c["accent_teal"]});
    border-radius: 3px;
}}

/* ── STATUS BAR ──────────────────────────────────────────── */
QStatusBar {{
    background: {c["bg_secondary"]}; color: {c["text_secondary"]};
    border-top: 1px solid {c["border"]}; font-size: 8pt; padding: 2px 8px;
}}
QStatusBar::item {{ border: none; }}

/* ── DIALOG ──────────────────────────────────────────────── */
QDialog {{ background: {c["bg_secondary"]}; border: 1px solid {c["border"]}; border-radius: 10px; }}

/* ── FRAME / CARD ────────────────────────────────────────── */
QFrame[card="true"] {{ background: {c["bg_card"]}; border: 1px solid {c["border"]}; border-radius: 8px; }}
QFrame[panel_header="true"] {{
    background: {c["bg_secondary"]}; border-bottom: 1px solid {c["border"]}; border-radius: 0;
}}

/* ── TOOLTIP ─────────────────────────────────────────────── */
QToolTip {{
    background: {c["bg_card"]}; color: {c["text_primary"]};
    border: 1px solid {c["border"]}; border-radius: 4px;
    padding: 4px 8px; font-size: 8pt;
}}

/* ── SIDEBAR ─────────────────────────────────────────────── */
QWidget#sidebar {{
    background: {c["bg_secondary"]}; border-right: 1px solid {c["border"]};
    max-width: 220px; min-width: 200px;
}}
QWidget#sidebar QPushButton {{
    background: transparent; border: none;
    border-left: 2px solid transparent; border-radius: 0;
    text-align: left; padding: 8px 16px;
    color: {c["text_secondary"]}; font-size: 9pt;
}}
QWidget#sidebar QPushButton:hover {{
    background: {c["bg_hover"]}; color: {c["text_primary"]};
}}
QWidget#sidebar QPushButton[active="true"] {{
    background: {c["selection_bg"]}; color: {c["accent_blue"]};
    border-left: 2px solid {c["accent_blue"]};
}}

/* ── MATPLOTLIB EMBED ────────────────────────────────────── */
QWidget#chart_area {{
    background: {c["bg_primary"]}; border: 1px solid {c["border"]}; border-radius: 8px;
}}
"""


def get_stylesheet() -> str:
    """Return the stylesheet for the currently active theme."""
    c = LIGHT_COLORS if _current_theme == "light" else DARK_COLORS
    return _build_stylesheet(c)


# Backwards-compat alias
DARK_STYLESHEET = _build_stylesheet(DARK_COLORS)
