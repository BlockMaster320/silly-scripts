"""Console syntax colors without changing its text or captured output."""

from math import ceil

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QResizeEvent, QShowEvent, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy

from .theme import PALETTE


class CommandPreview(QPlainTextEdit):
    """Fit all rendered command lines; the enclosing page handles scrolling."""

    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_height)
        self.textChanged.connect(self._queue_fit)
        self.document().documentLayout().documentSizeChanged.connect(self._queue_fit)

    def _queue_fit(self, *args: object) -> None:
        self._fit_timer.start(0)

    def _fit_height(self) -> None:
        document = self.document()
        document_layout = document.documentLayout()
        height = 0.0
        block = document.begin()
        while block.isValid():
            height += document_layout.blockBoundingRect(block).height()
            block = block.next()
        # Include stylesheet padding/frame and document margins, not just font
        # metrics: wrapped lines and platform font sizes must also fit.
        chrome = self.height() - self.viewport().height()
        target = ceil(height + 2 * document.documentMargin()) + chrome
        if self.height() != target or self.minimumHeight() != target:
            self.setFixedHeight(target)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._queue_fit()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._queue_fit()


class ConsoleHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text: str) -> None:
        color = "danger" if text.startswith("[stderr]") else "muted" if text.startswith("[Launcher]") else None
        if color:
            style = QTextCharFormat()
            style.setForeground(QColor(PALETTE[color]))
            self.setFormat(0, len(text), style)


class CommandPreviewHighlighter(QSyntaxHighlighter):
    """Color generated option lines without interpreting strings as options.

    Preview values are already quoted by the panel. Coloring the value portion
    as one span keeps option-looking text inside a value in the value color.
    """

    def __init__(self, document: QTextDocument, options: set[str]) -> None:
        super().__init__(document)
        self.options = options
        self.styles = {}
        for role, color in {
            "text": "command_text", "parameter": "accent", "value": "success",
        }.items():
            style = QTextCharFormat()
            style.setForeground(QColor(PALETTE[color]))
            self.styles[role] = style

    @staticmethod
    def _qt_length(text: str) -> int:
        return len(text.encode("utf-16-le")) // 2

    def highlightBlock(self, text: str) -> None:
        self.setFormat(0, self._qt_length(text), self.styles["text"])
        content = text.lstrip()
        if content.startswith("#   "):
            content = content[4:].lstrip()
        if not content:
            return
        first = content.split(None, 1)[0]
        name = first.split("=", 1)[0]
        if name not in self.options or name == "--":
            return
        start = len(text) - len(content)
        self.setFormat(self._qt_length(text[:start]), self._qt_length(name), self.styles["parameter"])
        value_start = start + len(name)
        if text[value_start:value_start + 1] == "=":
            value_start += 1
        while value_start < len(text) and text[value_start].isspace():
            value_start += 1
        end = len(text.rstrip())
        if text[:end].endswith("`"):
            end = len(text[:end - 1].rstrip())
        if value_start < end:
            self.setFormat(
                self._qt_length(text[:value_start]),
                self._qt_length(text[value_start:end]), self.styles["value"],
            )
