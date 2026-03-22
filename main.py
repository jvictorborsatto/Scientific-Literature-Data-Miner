"""
SLDM — Scientific Literature Data Miner
Entry point — run this file to launch the application.

Requirements:
    pip install PyQt5 PyMuPDF matplotlib pandas
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("SLDM")
    app.setApplicationDisplayName("Scientific Literature Data Miner")
    app.setOrganizationName("SLDM Project")

    font = QFont("Segoe UI", 9)
    app.setFont(font)

    from core.theme import get_stylesheet
    app.setStyleSheet(get_stylesheet())

    from core.main_window import MainWindow
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
