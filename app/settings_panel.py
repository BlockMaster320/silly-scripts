"""Global settings UI and executable selection."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .models import ExecutableInfo
from .settings import AppSettings
from .ui.components import Section
from .ui.theme import CONTROL_HEIGHT, PAGE, SECTION, SMALL, style_button


class ExecutableSelector(QWidget):
    selected = Signal(str)

    def __init__(self, kind: str, selected: str) -> None:
        super().__init__()
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SMALL)
        row = QHBoxLayout()
        row.setSpacing(SMALL)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setMinimumContentsLength(20)
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.setPlaceholderText(f"Select or browse for {kind}")
        self.combo.lineEdit().setPlaceholderText(f"Select or browse for {kind}")
        self.combo.setAccessibleName(f"{kind} executable")
        if selected:
            self.combo.addItem(f"{kind} · {Path(selected).name}", selected)
            self.combo.setCurrentIndex(0)
        browse = QPushButton("Browse…")
        style_button(browse, "folder")
        browse.clicked.connect(self._browse)
        row.addWidget(self.combo, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        self.path_label = QLabel(selected or "No executable selected")
        self.path_label.setProperty("role", "help")
        self.path_label.setTextFormat(Qt.TextFormat.PlainText)
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.path_label)
        self.combo.currentIndexChanged.connect(self._changed)
        self.combo.lineEdit().editingFinished.connect(self._changed)

    def path(self) -> str:
        index = self.combo.currentIndex()
        if index >= 0 and self.combo.currentText() == self.combo.itemText(index):
            return str(self.combo.itemData(index))
        return self.combo.currentText().strip().strip('"')

    def _changed(self) -> None:
        self.combo.setToolTip(self.path())
        self.path_label.setText(self.path() or "No executable selected")
        self.selected.emit(self.path())

    def add_executable(self, info: ExecutableInfo, select: bool = False) -> None:
        previous_path = self.path()
        self.combo.blockSignals(True)
        key = os.path.normcase(str(info.path))
        index = next(
            (i for i in range(self.combo.count()) if os.path.normcase(str(self.combo.itemData(i))) == key), -1
        )
        if index < 0:
            self.combo.addItem(f"{info.kind} {info.version}" if info.version else f"{info.kind} · {info.path.name}", str(info.path))
            index = self.combo.count() - 1
        else:
            self.combo.setItemText(index, f"{info.kind} {info.version}" if info.version else f"{info.kind} · {info.path.name}")
        self.combo.setItemData(index, str(info.path), Qt.ItemDataRole.ToolTipRole)
        if select or not previous_path or os.path.normcase(previous_path) == key:
            self.combo.setCurrentIndex(index)
        elif self.path() != previous_path:
            self.combo.setEditText(previous_path)
        self.combo.blockSignals(False)
        self._changed()

    def _browse(self) -> None:
        file_filter = "Executables (*.exe);;All files (*)" if os.name == "nt" else "All files (*)"
        path, _ = QFileDialog.getOpenFileName(self, f"Select {self.kind} executable", self.path(), file_filter)
        if path:
            self.add_executable(ExecutableInfo(Path(path).resolve(), self.kind), select=True)


class ScriptLibraryRow(QWidget):
    """One read-only library path with native browse and remove controls."""

    folder_selected = Signal(object, str)
    remove_requested = Signal(object)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SMALL)
        self.folder_edit = QLineEdit(str(folder))
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setAccessibleName("Scripts folder")
        browse = QPushButton("Browse…")
        style_button(browse, "folder")
        browse.clicked.connect(self._browse)
        self.remove_button = QPushButton()
        style_button(self.remove_button, "minus", "icon")
        self.remove_button.setFixedWidth(CONTROL_HEIGHT)
        self.remove_button.setToolTip("Remove script library")
        self.remove_button.setAccessibleName("Remove script library")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        self.folder_edit.editingFinished.connect(
            lambda: self.folder_selected.emit(self, self.folder_edit.text())
        )
        layout.addWidget(self.folder_edit, 1)
        layout.addWidget(browse)
        layout.addWidget(self.remove_button)

    @property
    def folder(self) -> Path:
        return Path(self.folder_edit.text()).expanduser().resolve()

    def _browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose scripts folder", self.folder_edit.text())
        if selected:
            self.folder_selected.emit(self, str(Path(selected).resolve()))


class SettingsPanel(QWidget):
    folder_changed = Signal()
    refresh_requested = Signal()
    executable_changed = Signal(str, str)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.folder_rows: list[ScriptLibraryRow] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, SECTION, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("pageContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, SMALL, SECTION)
        layout.setSpacing(PAGE)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        folder_group = Section("Script libraries")
        folder_layout = QVBoxLayout(folder_group.body)
        folder_layout.setContentsMargins(0, SMALL, 0, 0)
        folder_layout.setSpacing(SMALL)
        self.libraries_layout = QVBoxLayout()
        self.libraries_layout.setContentsMargins(0, 0, 0, 0)
        self.libraries_layout.setSpacing(SMALL)
        folder_layout.addLayout(self.libraries_layout)
        for folder in settings.scripts_folders:
            self._append_library_row(folder)
        library_actions = QHBoxLayout()
        self.add_library_button = QPushButton("Add library")
        style_button(self.add_library_button, "plus")
        self.add_library_button.clicked.connect(self._add_library)
        library_actions.addWidget(self.add_library_button)
        refresh = QPushButton("Refresh Scripts")
        style_button(refresh, "refresh")
        refresh.clicked.connect(self._refresh)
        library_actions.addWidget(refresh)
        library_actions.addStretch(1)
        folder_layout.addLayout(library_actions)
        note = QLabel("Only direct .py files in selected folders are scanned. __init__.py is ignored.\n"
                      "Use trusted scripts: inspection imports each script and calls create_parser().")
        note.setWordWrap(True)
        note.setProperty("role", "help")
        folder_layout.addWidget(note)
        layout.addWidget(folder_group)
        self.selectors: dict[str, ExecutableSelector] = {}
        for kind in ("Blender", "Python"):
            group = Section(kind)
            executable_layout = QVBoxLayout(group.body)
            executable_layout.setContentsMargins(0, SMALL, 0, 0)
            executable_layout.setSpacing(SMALL)
            selector = ExecutableSelector(kind, settings.executable(kind))
            selector.selected.connect(lambda path, kind=kind: self._executable_selected(kind, path))
            self.selectors[kind] = selector
            executable_layout.addWidget(selector)
            layout.addWidget(group)
        self.message = QLabel()
        self.message.setProperty("role", "help")
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch(1)

    @property
    def folder_edit(self) -> QLineEdit:
        """The primary path display, retained as a convenience for callers."""
        return self.folder_rows[0].folder_edit

    def selected_folders(self) -> list[Path]:
        return [row.folder for row in self.folder_rows]

    def add_executable(self, info: ExecutableInfo) -> None:
        self.selectors[info.kind].add_executable(info)

    def executable(self, kind: str) -> str:
        return self.selectors[kind].path()

    def _executable_selected(self, kind: str, path: str) -> None:
        self.settings.set_executable(kind, path)
        self.executable_changed.emit(kind, path)

    def _append_library_row(self, folder: Path) -> ScriptLibraryRow:
        row = ScriptLibraryRow(folder.expanduser().resolve())
        row.folder_selected.connect(self._folder_selected)
        row.remove_requested.connect(self._remove_library)
        self.folder_rows.append(row)
        self.libraries_layout.addWidget(row)
        self._update_remove_buttons()
        return row

    def _browse_folder(self) -> None:
        self.folder_rows[0]._browse()

    def _commit_folder(self) -> bool:
        return self._commit_folders()

    def _commit_folders(self) -> bool:
        folders = self.selected_folders()
        if not folders:
            self.message.setText("At least one script library must remain selected.")
            return False
        previous = self.settings.scripts_folders
        if folders == previous:
            return False
        keys = [os.path.normcase(str(path)) for path in folders]
        if len(keys) != len(set(keys)):
            self.message.setText("Each script library can only be selected once.")
            return False
        self.settings.set_scripts_folders(folders)
        self.folder_changed.emit()
        return True

    def _folder_selected(self, row: ScriptLibraryRow, text: str) -> None:
        selected = Path(text).expanduser().resolve()
        if any(other is not row and os.path.normcase(str(other.folder)) == os.path.normcase(str(selected)) for other in self.folder_rows):
            self.message.setText("That script library is already selected.")
            return
        row.folder_edit.setText(str(selected))
        self._commit_folders()

    def _add_library(self) -> None:
        initial = self.folder_rows[-1].folder_edit.text() if self.folder_rows else ""
        selected = QFileDialog.getExistingDirectory(self, "Add scripts folder", initial)
        if not selected:
            return
        folder = Path(selected).expanduser().resolve()
        if any(os.path.normcase(str(row.folder)) == os.path.normcase(str(folder)) for row in self.folder_rows):
            self.message.setText("That script library is already selected.")
            return
        row = self._append_library_row(folder)
        if not self._commit_folders():
            self.folder_rows.remove(row)
            self.libraries_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
            self._update_remove_buttons()

    def _remove_library(self, row: ScriptLibraryRow) -> None:
        if len(self.folder_rows) <= 1:
            return
        self.folder_rows.remove(row)
        self.libraries_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        self._update_remove_buttons()
        self._commit_folders()

    def _update_remove_buttons(self) -> None:
        for row in self.folder_rows:
            row.remove_button.setEnabled(len(self.folder_rows) > 1)

    def _refresh(self) -> None:
        if not self._commit_folders():
            self.refresh_requested.emit()
