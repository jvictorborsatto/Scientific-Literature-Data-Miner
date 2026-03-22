"""
SLDM — Shared UI widgets.
All widgets reference core.theme.COLORS at paint time so they respond
automatically when the theme is changed and the app stylesheet is refreshed.
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy, QLineEdit, QDialog, QDialogButtonBox,
    QFormLayout, QComboBox, QTextEdit, QSpinBox, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont
from core.theme import COLORS


# ── STAT CARD ─────────────────────────────────────────────────────────────────
class StatCard(QFrame):
    def __init__(self, label: str, value: str = "0", color: str = None, icon: str = ""):
        super().__init__()
        self._color = color or COLORS["accent_blue"]
        self._label_text = label
        self._icon = icon
        self.setObjectName("statCard")
        self._build()

    def _build(self):
        self.setStyleSheet(f"""
            QFrame#statCard {{
                background: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-top: 2px solid {self._color};
                border-radius: 8px;
                padding: 4px;
            }}
        """)
        self.setMinimumWidth(120)

        if self.layout():
            # Clear existing layout on rebuild
            while self.layout().count():
                item = self.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self.val_lbl = QLabel("0")
        self.val_lbl.setStyleSheet(
            f"font-size: 22pt; font-weight: 700; color: {COLORS['text_primary']}; "
            "background: transparent; border: none;"
        )
        top.addWidget(self.val_lbl)
        top.addStretch()
        if self._icon:
            ico = QLabel(self._icon)
            ico.setStyleSheet(
                f"font-size: 18pt; background: transparent; border: none; color: {self._color};"
            )
            top.addWidget(ico)
        layout.addLayout(top)

        self.lbl = QLabel(self._label_text)
        self.lbl.setStyleSheet(
            f"font-size: 8pt; color: {COLORS['text_secondary']}; "
            "background: transparent; border: none;"
        )
        layout.addWidget(self.lbl)

    def set_value(self, v):
        self.val_lbl.setText(str(v))


# ── PANEL (card with header) ──────────────────────────────────────────────────
class Panel(QFrame):
    def __init__(self, title: str, icon: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background: {COLORS['bg_card']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
            }}
        """)
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        hdr = QWidget()
        hdr.setStyleSheet(f"""
            background: {COLORS['bg_secondary']};
            border-bottom: 1px solid {COLORS['border']};
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
        """)
        hdr.setFixedHeight(40)
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(14, 0, 10, 0)

        if icon:
            ico = QLabel(icon)
            ico.setStyleSheet("background: transparent; font-size: 11pt;")
            hdr_lay.addWidget(ico)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(
            f"font-weight: 600; font-size: 9pt; color: {COLORS['text_primary']}; background: transparent;"
        )
        hdr_lay.addWidget(self.title_lbl)
        hdr_lay.addStretch()

        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(4)
        hdr_lay.addLayout(self.header_actions)

        self._outer.addWidget(hdr)

        self.body = QWidget()
        self.body.setStyleSheet("background: transparent; border: none;")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(14, 12, 14, 12)
        self.body_layout.setSpacing(8)
        self._outer.addWidget(self.body)

    def add_header_button(self, text: str, primary=False, danger=False, flat=False) -> QPushButton:
        btn = QPushButton(text)
        if primary:
            style = (f"QPushButton {{ background: {COLORS['accent_blue']}; color: white; "
                     f"border: 1px solid {COLORS['accent_blue']}; border-radius: 5px; "
                     "padding: 4px 12px; font-size: 8pt; font-weight: 500; }}"
                     f"QPushButton:hover {{ opacity: 0.85; }}")
        elif danger:
            style = (f"QPushButton {{ background: transparent; color: {COLORS['accent_rose']}; "
                     f"border: 1px solid {COLORS['accent_rose']}44; border-radius: 5px; "
                     "padding: 4px 12px; font-size: 8pt; }}"
                     f"QPushButton:hover {{ background: {COLORS['accent_rose']}18; }}")
        elif flat:
            style = (f"QPushButton {{ background: transparent; color: {COLORS['text_secondary']}; "
                     "border: 1px solid transparent; border-radius: 5px; "
                     "padding: 4px 12px; font-size: 8pt; }}"
                     f"QPushButton:hover {{ background: {COLORS['bg_hover']}; color: {COLORS['text_primary']}; }}")
        else:
            style = (f"QPushButton {{ background: {COLORS['bg_tertiary']}; color: {COLORS['text_secondary']}; "
                     f"border: 1px solid {COLORS['border']}; border-radius: 5px; "
                     "padding: 4px 12px; font-size: 8pt; font-weight: 500; }}"
                     f"QPushButton:hover {{ background: {COLORS['bg_hover']}; color: {COLORS['text_primary']}; }}")
        btn.setStyleSheet(style)
        self.header_actions.addWidget(btn)
        return btn

    def add_body_widget(self, w: QWidget):
        self.body_layout.addWidget(w)

    def set_body_margins(self, *args):
        self.body_layout.setContentsMargins(*args)


# ── SEARCH BAR ────────────────────────────────────────────────────────────────
class SearchBar(QLineEdit):
    def __init__(self, placeholder="Search…", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setStyleSheet(f"""
            QLineEdit {{
                background: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 6px 10px 6px 30px;
                color: {COLORS['text_primary']};
                font-size: 9pt;
            }}
            QLineEdit:focus {{ border-color: {COLORS['accent_blue']}; }}
        """)


# ── BUTTON FACTORY ────────────────────────────────────────────────────────────
def make_btn(text: str, primary=False, danger=False, flat=False, small=False) -> QPushButton:
    btn = QPushButton(text)
    pad = "4px 10px" if small else "6px 16px"
    fsize = "8pt" if small else "9pt"
    if primary:
        btn.setStyleSheet(f"""
            QPushButton {{ background:{COLORS['accent_blue']}; color:white; border:1px solid {COLORS['accent_blue']};
                border-radius:6px; padding:{pad}; font-size:{fsize}; font-weight:500; }}
            QPushButton:hover {{ opacity:0.9; }}
            QPushButton:pressed {{ opacity:0.8; }}
            QPushButton:disabled {{ background:{COLORS['bg_card']}; color:{COLORS['text_muted']}; border-color:{COLORS['bg_tertiary']}; }}
        """)
    elif danger:
        btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{COLORS['accent_rose']}; border:1px solid {COLORS['accent_rose']}44;
                border-radius:6px; padding:{pad}; font-size:{fsize}; font-weight:500; }}
            QPushButton:hover {{ background:{COLORS['accent_rose']}18; border-color:{COLORS['accent_rose']}; }}
        """)
    elif flat:
        btn.setStyleSheet(f"""
            QPushButton {{ background:transparent; color:{COLORS['text_secondary']}; border:1px solid transparent;
                border-radius:6px; padding:{pad}; font-size:{fsize}; }}
            QPushButton:hover {{ background:{COLORS['bg_hover']}; color:{COLORS['text_primary']}; }}
        """)
    else:
        btn.setStyleSheet(f"""
            QPushButton {{ background:{COLORS['bg_card']}; color:{COLORS['text_primary']}; border:1px solid {COLORS['border']};
                border-radius:6px; padding:{pad}; font-size:{fsize}; font-weight:500; }}
            QPushButton:hover {{ background:{COLORS['bg_hover']}; border-color:{COLORS['text_muted']}; }}
            QPushButton:pressed {{ background:{COLORS['bg_secondary']}; }}
        """)
    return btn


# ── EMPTY STATE ───────────────────────────────────────────────────────────────
class EmptyState(QWidget):
    def __init__(self, icon="📭", title="No data", subtitle="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(6)

        ico = QLabel(icon)
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet(f"font-size: 32pt; color: {COLORS['text_muted']}; background: transparent; border: none;")
        lay.addWidget(ico)

        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(f"font-size: 11pt; font-weight: 600; color: {COLORS['text_secondary']}; background: transparent; border: none;")
        lay.addWidget(t)

        if subtitle:
            s = QLabel(subtitle)
            s.setAlignment(Qt.AlignCenter)
            s.setStyleSheet(f"font-size: 9pt; color: {COLORS['text_muted']}; background: transparent; border: none;")
            lay.addWidget(s)


# ── SEPARATOR ─────────────────────────────────────────────────────────────────
class HSep(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setStyleSheet(
            f"color: {COLORS['border']}; background: {COLORS['border']}; border: none; max-height: 1px;"
        )


# ── TOAST NOTIFICATION ────────────────────────────────────────────────────────
class Toast(QLabel):
    def __init__(self, msg: str, kind: str = "info", parent=None):
        super().__init__(msg, parent)
        colors = {
            "info":    COLORS["accent_blue"],
            "success": COLORS["accent_green"],
            "error":   COLORS["accent_rose"],
            "warning": COLORS["accent_amber"],
        }
        c = colors.get(kind, COLORS["accent_blue"])
        self.setStyleSheet(f"""
            background: {COLORS['bg_card']};
            color: {COLORS['text_primary']};
            border: 1px solid {COLORS['border']};
            border-left: 3px solid {c};
            border-radius: 8px;
            padding: 10px 16px;
            font-size: 9pt;
        """)
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.adjustSize()
        QTimer.singleShot(2800, self.hide)

    @staticmethod
    def show_toast(parent, msg, kind="info"):
        t = Toast(msg, kind, parent)
        if parent:
            pos = parent.mapToGlobal(parent.rect().bottomRight())
            t.move(pos.x() - t.width() - 20, pos.y() - t.height() - 20)
        t.show()
