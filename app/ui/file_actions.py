"""Open script source using the user's default file association."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_script_file(path: Path) -> bool:
    if not path.is_file():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
