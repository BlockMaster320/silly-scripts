"""Entry point for SillyScripts."""

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.ui.loading_screen import LoadingScreen
from app.ui.theme import apply_theme


def main() -> int:
    application = QApplication(sys.argv)
    application.setOrganizationName("SillyScripts")
    application.setApplicationName("SillyScripts")
    application.setApplicationDisplayName("SillyScripts")
    apply_theme(application)
    loading = LoadingScreen()
    loading.show()
    window: MainWindow | None = None

    def open_window() -> None:
        nonlocal window
        try:
            window = MainWindow(Path(__file__).resolve().parent)
        except Exception:
            # Qt timer callbacks cannot propagate initialization errors back to
            # main(); report them and exit instead of leaving the splash open.
            traceback.print_exc()
            application.exit(1)
            loading.close()
            return
        window.show()
        loading.close()

    # Let Qt paint both frames before synchronous script inspection starts.
    QTimer.singleShot(650, open_window)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
