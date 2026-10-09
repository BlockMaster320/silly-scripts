"""Coordinate navigation and composed panels; processes outlive selection changes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QInputDialog, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .arguments import ParameterValidationError
from .batch_support import BATCH_TEMPLATE, BatchSupport
from .executable_discovery import ExecutableDiscovery
from .log_panel import LogPanel
from .models import ScriptInfo
from .parameters_panel import ParametersPanel
from .process_manager import ProcessManager
from .script_discovery import discover_script_libraries
from .script_inspector import ScriptInspector
from .script_templates import TemplateKind, create_script
from .settings import AppSettings
from .settings_panel import SettingsPanel


class MainWindow(QMainWindow):
    def __init__(self, project_dir: Path, settings: AppSettings | None = None, auto_discover: bool = True) -> None:
        super().__init__()
        self.settings = settings if settings is not None else AppSettings(project_dir)
        self.inspector = ScriptInspector()
        self.batch_support = BatchSupport()
        batch_info = self.inspector.inspect(BATCH_TEMPLATE)
        self.processes = ProcessManager(project_dir / "logs", self)
        self.discovery = ExecutableDiscovery(self)
        self.scripts: dict[Path, ScriptInfo] = {}
        self.items: dict[Path, QTreeWidgetItem] = {}
        self.script_libraries: dict[Path, Path] = {}
        self.active_path: Path | None = None
        self._closing = False
        self.setWindowTitle("Blender Script Launcher")
        self.resize(1100, 780)
        self.setMinimumSize(760, 540)

        splitter = QSplitter()
        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderLabel("Script libraries")
        self.sidebar.setMinimumWidth(170)
        # Expanding a library should only change the tree's visibility state.
        # Keep the tree from doing expensive layout/scroll work before handling
        # the next click, especially when a library contains many scripts.
        self.sidebar.setAnimated(False)
        self.sidebar.setUniformRowHeights(True)
        self.sidebar.setExpandsOnDoubleClick(False)
        self.sidebar.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.sidebar.currentItemChanged.connect(self._selection_changed)
        sidebar_panel = QWidget()
        sidebar_layout = QVBoxLayout(sidebar_panel)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(self.sidebar, 1)
        self.create_script_button = QPushButton("Create blank script")
        self.create_batch_button = QPushButton("Create blank batch script")
        self.create_script_button.clicked.connect(lambda: self._create_script("blank"))
        self.create_batch_button.clicked.connect(lambda: self._create_script("batch"))
        sidebar_layout.addWidget(self.create_script_button)
        sidebar_layout.addWidget(self.create_batch_button)
        splitter.addWidget(sidebar_panel)
        self.tabs = QTabWidget()
        self.parameters = ParametersPanel(
            batch_parameters=batch_info.parameters if not batch_info.inspection_error else None,
            batch_error=batch_info.inspection_error,
        )
        self.log = LogPanel()
        self.settings_panel = SettingsPanel(self.settings)
        self.tabs.addTab(self.parameters, "Script")
        self.tabs.addTab(self.log, "Log")
        self.tabs.addTab(self.settings_panel, "Settings")
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 870])
        self.setCentralWidget(splitter)
        self.parameters.run_requested.connect(self._run_active)
        self.parameters.stop_requested.connect(self._stop_active)
        self.parameters.runtime_changed.connect(self._runtime_changed)
        self.log.clear_requested.connect(self._clear_view)
        self.settings_panel.folder_changed.connect(self.refresh_scripts)
        self.settings_panel.refresh_requested.connect(self.refresh_scripts)
        self.settings_panel.executable_changed.connect(self._executable_changed)
        self.discovery.found.connect(self.settings_panel.add_executable)
        self.processes.state_changed.connect(self._state_changed)
        self.processes.output_received.connect(self._output_received)
        self.processes.view_cleared.connect(self._view_cleared)
        self.processes.execution_error.connect(self._execution_error)
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(50)
        self._close_timer.timeout.connect(self._check_close)
        geometry = self.settings.geometry()
        if geometry:
            self.restoreGeometry(geometry)
        self.refresh_scripts()
        if auto_discover:
            QTimer.singleShot(0, self.discovery.discover)

    def _create_script(self, kind: TemplateKind) -> None:
        title = "Create blank batch script" if kind == "batch" else "Create blank script"
        default_name = "new_batch_script.py" if kind == "batch" else "new_blender_script.py"
        name, accepted = QInputDialog.getText(self, title, "Script filename:", text=default_name)
        if not accepted:
            return
        try:
            library = self.script_libraries.get(self.active_path) if self.active_path else None
            if library is None:
                library = self.settings.scripts_folders[0]
            path = create_script(library, name, kind)
        except FileExistsError:
            QMessageBox.warning(self, title, "A file with that name already exists. Choose another filename.")
            return
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, title, str(exc))
            return
        state = self.processes.state_for(path)
        state.runtime = "Blender"
        self.refresh_scripts()
        self.sidebar.setCurrentItem(self.items[path])
        self.tabs.setCurrentWidget(self.parameters)
        self.statusBar().showMessage(f"Created {path}. Edit the file to add your Blender code.")

    def refresh_scripts(self) -> None:
        self.parameters.save_values()
        previous = self.active_path
        discovered, errors = discover_script_libraries(self.settings.scripts_folders)
        library_for_path = {path: library for path, library in discovered}
        paths = list(library_for_path)
        message = f"Found {len(paths)} script(s) in {len(self.settings.scripts_folders)} library/libraries"
        if errors:
            message += ". " + " ".join(errors)
        scripts: dict[Path, ScriptInfo] = {}
        for path in paths:
            state = self.processes.state_for(path)
            if state.is_running and path in self.scripts:
                scripts[path] = self.scripts[path]
            else:
                info = self.inspector.inspect(path)
                old = self.scripts.get(path)
                if old and old.parameters != info.parameters:
                    state.parameter_values.clear()
                scripts[path] = info
            scripts[path].category = library_for_path[path].name
        # Keep active processes and their Stop controls reachable when the
        # folder changes, is deleted, or a running script is removed from disk.
        for path, script in self.scripts.items():
            if path not in scripts and self.processes.state_for(path).is_running:
                library = self.script_libraries.get(path)
                if library:
                    library_for_path[path] = library
                    script.category = library.name
                scripts[path] = script
        self.scripts = scripts
        self.script_libraries = {
            path: library_for_path[path] for path in scripts if path in library_for_path
        }
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        self.items.clear()
        groups: dict[Path, QTreeWidgetItem] = {}
        for path, script in scripts.items():
            library = self.script_libraries.get(path)
            if library is None:
                library = path.parent
                self.script_libraries[path] = library
            group = groups.get(library)
            if group is None:
                group = QTreeWidgetItem(self.sidebar, [library.name])
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                group.setExpanded(True)
                groups[library] = group
            else:
                group = groups[library]
            item = QTreeWidgetItem(group)
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            self.items[path] = item
            self._update_item(path)
        selected = previous if previous in scripts else next(iter(scripts), None)
        if selected:
            self.sidebar.setCurrentItem(self.items[selected])
        self.sidebar.blockSignals(False)
        self._activate(selected)
        self.settings_panel.message.setText(message)
        self.statusBar().showMessage(message)

    def _selection_changed(self, item: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        if item and (path := item.data(0, Qt.ItemDataRole.UserRole)):
            self.parameters.save_values()
            self._activate(path)

    def _activate(self, path: Path | None) -> None:
        self.active_path = path
        script = self.scripts.get(path) if path else None
        state = self.processes.state_for(path) if path else None
        self.parameters.set_script(script, state)
        if state:
            self.parameters.set_executable(self.settings_panel.executable(state.runtime))
        self.log.set_script(script, state)
        if path:
            self._update_item(path)

    def _update_item(self, path: Path) -> None:
        script = self.scripts[path]
        state = self.processes.state_for(path)
        prefix = "● " if state.is_running else "! " if script.inspection_error else ""
        self.items[path].setText(0, prefix + script.name)
        self.items[path].setToolTip(0, f"{path}\n{script.inspection_error or state.status}")

    def _run_active(self) -> None:
        if not self.active_path or not self.parameters.form:
            return
        self.parameters.save_values()
        self.parameters.show_error("")
        state = self.processes.state_for(self.active_path)
        executable = self.settings_panel.executable(state.runtime)
        try:
            arguments = self.parameters.form.arguments()
            if state.batch_mode:
                if not self.parameters.batch_form:
                    raise ValueError(self.parameters.batch_error or "Batch file selection is unavailable.")
                batch_arguments = self.parameters.batch_form.arguments()
                selection = self.batch_support.discover(batch_arguments)
                if not selection.files:
                    raise ValueError("No .blend files match the selected batch filters.")
                payload = {
                    "script_path": str(self.active_path),
                    "script_arguments": arguments,
                    "batch_selection_arguments": batch_arguments,
                    "files": [str(path) for path in selection.files],
                    "purge_unused_data": selection.purge_unused_data,
                }
                started = self.processes.start(
                    self.scripts[self.active_path], executable, [], batch_payload=payload
                )
                if started:
                    self.statusBar().showMessage(f"Started batch run for {len(selection.files)} blend file(s).")
            else:
                self.processes.start(self.scripts[self.active_path], executable, arguments)
        except (ParameterValidationError, ValueError, OSError, RuntimeError) as exc:
            self.parameters.show_error(str(exc))
            return
        self.tabs.setCurrentWidget(self.log)

    def _executable_changed(self, kind: str, path: str) -> None:
        if self.active_path:
            state = self.processes.state_for(self.active_path)
            if state.runtime == kind:
                self.parameters.set_executable(path)

    def _runtime_changed(self, runtime: str) -> None:
        self.parameters.set_executable(self.settings_panel.executable(runtime))

    def _stop_active(self) -> None:
        if self.active_path:
            self.processes.stop(self.active_path)

    def _state_changed(self, path: Path) -> None:
        if path in self.items:
            self._update_item(path)
        if path == self.active_path:
            self.parameters.update_state()
            self.log.update_state(self.scripts[path], self.processes.state_for(path))

    def _output_received(self, path: Path, line: str) -> None:
        if path == self.active_path:
            self.log.append(line)

    def _execution_error(self, path: Path, message: str) -> None:
        self.statusBar().showMessage(f"{path.name}: {message}")
        if path == self.active_path:
            self.parameters.show_error(message)

    def _clear_view(self) -> None:
        if self.active_path:
            self.processes.clear_view(self.active_path)

    def _view_cleared(self, path: Path) -> None:
        if path == self.active_path:
            self.log.output.clear()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closing:
            self._closing = True
            self.parameters.save_values()
            for kind in ("Blender", "Python"):
                self.settings.set_executable(kind, self.settings_panel.executable(kind))
            self.settings.save_geometry(self.saveGeometry())
            self.discovery.shutdown()
            self.processes.stop_all()
        if self.processes.has_running or self.discovery.is_busy:
            event.ignore()
            self.centralWidget().setEnabled(False)
            self.statusBar().showMessage("Stopping active processes before closing…")
            self._close_timer.start()
        else:
            self._close_timer.stop()
            event.accept()

    def _check_close(self) -> None:
        if not self.processes.has_running and not self.discovery.is_busy:
            self.close()
