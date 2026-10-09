"""Console syntax colors without changing its text or captured output."""

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from .theme import PALETTE


class ConsoleHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:
        color = "danger" if text.startswith("[stderr]") else "muted" if text.startswith("[Launcher]") else None
        if color:
            style = QTextCharFormat()
            style.setForeground(QColor(PALETTE[color]))
            self.setFormat(0, len(text), style)
