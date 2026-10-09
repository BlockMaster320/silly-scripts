"""Small composed widgets shared by the parameter and settings pages."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import NORMAL, SMALL


class Section(QWidget):
    """A heading and trailing rule above a body with a caller-owned layout."""

    def __init__(self, title: str) -> None:
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
        holder = QWidget()
        rule_layout = QVBoxLayout(holder)
        rule_layout.setContentsMargins(0, SMALL, 0, 0)
        rule_layout.setSpacing(0)
        rule_layout.addWidget(rule)
        holder.setFixedHeight(SMALL + 1)
        header.addWidget(holder, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)
        self.body = QWidget()
        layout.addWidget(self.body)
