"""View only: the manager owns logs, buffers, and Clear Log behavior."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .models import MAX_VISIBLE_LINES, ScriptInfo, ScriptRuntimeState
from .ui.console import ConsoleHighlighter
from .ui.theme import SECTION, SMALL, monospace_font, style_button


class LogPanel(QWidget):
    clear_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.log_path: Path | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SECTION, 0, 0)
        layout.setSpacing(SMALL)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(SMALL)
        self.title = QLabel("No script selected")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        self.title.setProperty("role", "heading")
        toolbar.addWidget(self.title, 1)
        self.clear_button = QPushButton("Clear Log")
        style_button(self.clear_button, "clear")
        self.clear_button.clicked.connect(self.clear_requested)
        self.open_button = QPushButton("Open Log Folder")
        style_button(self.open_button, "folder")
        self.open_button.clicked.connect(self._open_folder)
        self.open_button.setEnabled(False)
        toolbar.addWidget(self.clear_button)
        toolbar.addWidget(self.open_button)
        layout.addLayout(toolbar)
        self.path_label = QLabel()
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        self.path_label.setProperty("role", "help")
        layout.addWidget(self.path_label)
        self.output = QPlainTextEdit()
        self.output.setProperty("role", "console")
        self.output.setAccessibleName("Script output")
        self.output.setPlaceholderText("Run a script to see live output here.")
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.output.setMaximumBlockCount(MAX_VISIBLE_LINES)
        self.output.setFont(monospace_font())
        self.highlighter = ConsoleHighlighter(self.output.document())
        layout.addWidget(self.output, 1)

    def set_script(self, script: ScriptInfo | None, state: ScriptRuntimeState | None) -> None:
        self.update_state(script, state)
        self.output.setPlainText("\n".join(state.visible_log) if state else "")
        self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())

    def update_state(self, script: ScriptInfo | None, state: ScriptRuntimeState | None) -> None:
        self.title.setText(f"{script.name} · {state.status}" if script and state else "No script selected")
        self.log_path = state.current_log_path if state else None
        self.path_label.setText(str(self.log_path) if self.log_path else "No runs yet.")
        self.clear_button.setEnabled(state is not None)
        self.open_button.setEnabled(self.log_path is not None)

    def append(self, line: str) -> None:
        scrollbar = self.output.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        previous = scrollbar.value()
        self.output.appendPlainText(line)
        scrollbar.setValue(scrollbar.maximum() if at_bottom else previous)

    def _open_folder(self) -> None:
        if self.log_path and not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_path.parent))):
            self.path_label.setText(f"Could not open folder: {self.log_path.parent}")
