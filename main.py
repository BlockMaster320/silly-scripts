"""Entry point for SillyScripts."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.ui.theme import apply_theme


def main() -> int:
    application = QApplication(sys.argv)
    application.setOrganizationName("SillyScripts")
    application.setApplicationName("SillyScripts")
    application.setApplicationDisplayName("SillyScripts")
    apply_theme(application)
    window = MainWindow(Path(__file__).resolve().parent)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
