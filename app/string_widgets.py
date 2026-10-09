"""Repeatable string controls and native folder selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from .models import ScriptParameter


class FolderPicker(QWidget):
    changed = Signal()

    def __init__(self, label: str, path: str = "") -> None:
        super().__init__()
        self._path = path
        self.label = label
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.path_label = QLabel()
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.browse_button = QPushButton("Select folder…")
        self.browse_button.setAccessibleName(f"Select {label} folder")
        self.browse_button.clicked.connect(self._browse)
        layout.addWidget(self.path_label, 1)
        layout.addWidget(self.browse_button)
        self._update_label()

    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        if path != self._path:
            self._path = path
            self._update_label()
            self.changed.emit()

    def _update_label(self) -> None:
        self.path_label.setText(self._path or "No folder selected")
        self.path_label.setToolTip(self._path)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, f"Choose {self.label}", self._path)
        if path:
            self.set_path(str(Path(path).resolve()))


class FilePicker(QWidget):
    """Read-only path display with a native file chooser."""

    changed = Signal()

    def __init__(self, label: str, path: str = "") -> None:
        super().__init__()
        self._path = path
        self.label = label
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.path_label = QLabel()
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.browse_button = QPushButton("Select file…")
        self.browse_button.setAccessibleName(f"Select {label} file")
        self.browse_button.clicked.connect(self._browse)
        layout.addWidget(self.path_label, 1)
        layout.addWidget(self.browse_button)
        self._update_label()

    def path(self) -> str:
        return self._path

    def _update_label(self) -> None:
        self.path_label.setText(self._path or "No file selected")
        self.path_label.setToolTip(self._path)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, f"Choose {self.label}", self._path)
        if path:
            self._path = str(Path(path).expanduser().resolve())
            self._update_label()
            self.changed.emit()


class MultiValueInputs(QWidget):
    """Repeatable controls for non-string values using argparse nargs='+'."""

    changed = Signal()

    def __init__(self, parameter: ScriptParameter, initial: Any) -> None:
        super().__init__()
        self.parameter = parameter
        self.controls: list[QWidget] = []
        self.rows: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.rows_layout)
        self.add_button = QPushButton("+")
        self.add_button.setFixedWidth(30)
        self.add_button.setAccessibleName(f"Add {parameter.label} value")
        self.add_button.clicked.connect(lambda: self.add_value())
        values = initial if isinstance(initial, (list, tuple)) else [initial]
        for value in values or [None]:
            self.add_value(value)

    @property
    def first_control(self) -> QWidget:
        return self.controls[0]

    def add_value(self, value: Any = None) -> None:
        parameter = self.parameter
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        if parameter.choices is not None:
            control = QComboBox()
            control.setPlaceholderText("Select a value…")
            for choice in parameter.choices:
                control.addItem(str(choice), choice)
            control.setCurrentIndex(next((i for i, choice in enumerate(parameter.choices) if str(choice) == str(value)), -1))
            control.currentIndexChanged.connect(self.changed)
        elif parameter.is_path_selection and parameter.is_folder_selection:
            control = FolderPicker(parameter.label, "" if value is None else str(value))
            control.changed.connect(self.changed)
        elif parameter.is_path_selection:
            control = FilePicker(parameter.label, "" if value is None else str(value))
            control.changed.connect(self.changed)
        elif parameter.parameter_type is int:
            # A text editor lets an empty row remain empty instead of silently
            # turning it into zero; conversion and errors are handled at Run.
            control = QLineEdit("" if value is None else str(value))
            control.setPlaceholderText("Required value")
            control.textChanged.connect(self.changed)
        elif parameter.parameter_type is float:
            control = QLineEdit("" if value is None else str(value))
            control.setPlaceholderText("Required value")
            control.textChanged.connect(self.changed)
        else:
            control = QLineEdit("" if value is None else str(value))
            control.setPlaceholderText("Required value")
            control.textChanged.connect(self.changed)
        control.setAccessibleName(parameter.label)
        row_layout.addWidget(control, 1)
        if not self.controls:
            row_layout.addWidget(self.add_button)
        else:
            remove = QPushButton("−")
            remove.setFixedWidth(30)
            remove.setAccessibleName(f"Remove {parameter.label} value")
            remove.clicked.connect(lambda: self._remove(row, control))
            row_layout.addWidget(remove)
        self.controls.append(control)
        self.rows.append(row)
        self.rows_layout.addWidget(row)
        self.changed.emit()

    def _remove(self, row: QWidget, control: QWidget) -> None:
        self.controls.remove(control)
        self.rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self.rows_layout.invalidate()
        self.layout().invalidate()
        self.updateGeometry()
        self.changed.emit()

    def values(self) -> list[Any]:
        result: list[Any] = []
        for control in self.controls:
            if isinstance(control, (FilePicker, FolderPicker)):
                result.append(control.path())
            elif isinstance(control, QComboBox):
                result.append(control.currentData() if control.currentIndex() >= 0 else None)
            else:
                result.append(control.text())
        return result


class StringInputs(QWidget):
    """One row per value. Keep the first control accessible to ParameterEditor."""

    changed = Signal()

    def __init__(self, parameter: ScriptParameter, initial: Any) -> None:
        super().__init__()
        self.parameter = parameter
        self.controls: list[QWidget] = []
        self._rows: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.rows_layout)
        self.add_button = QPushButton("+")
        self.add_button.setFixedWidth(30)
        self.add_button.setToolTip(f"Add another {parameter.label} value")
        self.add_button.setAccessibleName(f"Add {parameter.label} value")
        self.add_button.clicked.connect(lambda: self.add_value())
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        values = initial if isinstance(initial, (list, tuple)) else [initial]
        for value in values or [None]:
            self.add_value(value)

    @property
    def first_control(self) -> QWidget:
        return self.controls[0]

    def add_value(self, value: Any = None) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        parameter = self.parameter
        if parameter.choices is not None:
            control = QComboBox()
            control.setPlaceholderText("Select a value…")
            for choice in parameter.choices:
                control.addItem(str(choice), choice)
            control.setCurrentIndex(next((i for i, choice in enumerate(parameter.choices) if str(choice) == str(value)), -1))
            control.currentIndexChanged.connect(self.changed)
        elif parameter.is_folder_selection:
            control = FolderPicker(parameter.label, "" if value is None else str(value))
            control.changed.connect(self.changed)
        else:
            control = QLineEdit("" if value is None else str(value))
            control.setPlaceholderText("For example: 1,4-8,12" if parameter.is_shot_selection else "Required" if parameter.required else "Optional")
            control.textChanged.connect(self.changed)
        control.setAccessibleName(parameter.label)
        layout.addWidget(control, 1)
        if not self.controls:
            layout.addWidget(self.add_button)
        else:
            remove = QPushButton("−")
            remove.setFixedWidth(30)
            remove.setAccessibleName(f"Remove {parameter.label} value")
            remove.clicked.connect(lambda: self._remove(row, control))
            layout.addWidget(remove)
        self.controls.append(control)
        self._rows.append(row)
        self.rows_layout.addWidget(row)
        self._update_hint()
        self.changed.emit()

    def _remove(self, row: QWidget, control: QWidget) -> None:
        self.controls.remove(control)
        self._rows.remove(row)
        self.rows_layout.removeWidget(row)
        # removeWidget() only detaches a widget from its layout; it remains
        # visible until deleteLater() runs. Hide it now so Qt cannot keep its
        # old geometry over the remaining row during the current event turn.
        row.hide()
        row.deleteLater()
        self._update_hint()
        self.rows_layout.invalidate()
        self.layout().invalidate()
        self.updateGeometry()
        self.changed.emit()

    def _update_hint(self) -> None:
        parameter = self.parameter
        scalar = parameter.action_type == "store" and parameter.nargs in (None, "?")
        joins_folders = parameter.name == "exclude_folders" and parameter.is_folder_selection
        text = ""
        if len(self.controls) > 1 and scalar and not parameter.is_shot_selection and not joins_folders:
            text = "This script accepts one value; the last filled value will be used." if parameter.option else "This positional argument accepts only one value."
        if parameter.action_type == "append" and parameter.default:
            text += f" Script defaults are retained: {parameter.default}"
        self.hint.setText(text.strip())
        self.hint.setVisible(bool(text))

    def values(self) -> list[Any]:
        values: list[Any] = []
        for control in self.controls:
            if isinstance(control, FolderPicker):
                values.append(control.path())
            elif isinstance(control, QComboBox):
                values.append(control.currentData() if control.currentIndex() >= 0 else None)
            else:
                values.append(control.text())
        return values
