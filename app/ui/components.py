"""Small composed widgets shared by the parameter and settings pages."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import NORMAL, SMALL


class SingleLineTitle(QLabel):
    """Use the full title's natural width, eliding only when space runs out."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._full_text = text
        self.setWordWrap(False)
        self.setAccessibleName(text)

    def text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setAccessibleName(text)
        self._update_display()
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setWidth(self.fontMetrics().horizontalAdvance(self._full_text))
        return hint

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_display()

    def _update_display(self) -> None:
        super().setText(self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.contentsRect().width(),
        ))


class Section(QWidget):
    """A heading and trailing rule above a body with a caller-owned layout."""

    def __init__(self, title: str, *, subdued: bool = False) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SMALL)
        header = QHBoxLayout()
        header.setSpacing(NORMAL)
        self.heading = QLabel(title)
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setProperty("role", "sectionHeading")
        header.addWidget(self.heading)
        rule = QFrame()
        rule.setProperty("role", "sectionDivider")
        rule.setFixedHeight(1)
        if subdued:
            rule.setProperty("variant", "script")
            holder = QWidget()
            rule_layout = QVBoxLayout(holder)
            rule_layout.setContentsMargins(0, SMALL, 0, 0)
            rule_layout.setSpacing(0)
            rule_layout.addWidget(rule)
            holder.setFixedHeight(SMALL + 1)
            header.addWidget(holder, 1, Qt.AlignmentFlag.AlignVCenter)
        else:
            header.addWidget(rule, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)
        self.body = QWidget()
        layout.addWidget(self.body)
