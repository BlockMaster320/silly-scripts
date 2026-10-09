"""Coordinate navigation and composed panels; processes outlive selection changes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .arguments import ParameterValidationError
from .batch_support import BATCH_TEMPLATE, BatchSupport
from .executable_discovery import ExecutableDiscovery
from .log_panel import LogPanel
from .models import ScriptInfo
from .parameter_config import ParameterConfigError, ParameterConfigStore
from .parameters_panel import ParametersPanel
from .process_manager import ProcessManager
from .script_discovery import discover_script_libraries
from .script_inspector import ScriptInspector
from .script_templates import TemplateKind, create_script
from .settings import AppSettings
from .settings_panel import SettingsPanel
from .ui.theme import PAGE, SECTION, SMALL, TINY, icon, set_variant, style_button


class MainWindow(QMainWindow):
    def __init__(
        self, project_dir: Path, settings: AppSettings | None = None,
        auto_discover: bool = True, *, parameter_configs: ParameterConfigStore | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings if settings is not None else AppSettings(project_dir)
        self.inspector = ScriptInspector()
        self.parameter_configs = parameter_configs if parameter_configs is not None else ParameterConfigStore()
        self._loaded_parameter_configs: set[Path] = set()
        self.batch_support = BatchSupport()
        batch_info = self.inspector.inspect(BATCH_TEMPLATE)
        self.processes = ProcessManager(project_dir / "logs", self)
        self.discovery = ExecutableDiscovery(self)
        self.scripts: dict[Path, ScriptInfo] = {}
        self.items: dict[Path, QTreeWidgetItem] = {}
        self.script_libraries: dict[Path, Path] = {}
        self.active_path: Path | None = None
        self._closing = False
        self.setWindowTitle("SillyScripts")
        self.resize(1100, 780)
        self.setMinimumSize(760, 540)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(TINY)
        self.sidebar = QTreeWidget()
        self.sidebar.setObjectName("scriptTree")
        self.sidebar.setHeaderHidden(True)
        self.sidebar.setAccessibleName("Script libraries")
        self.sidebar.setIndentation(SECTION)
        self.sidebar.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sidebar.setIconSize(QSize(SECTION, SECTION))
        # Expanding a library should only change the tree's visibility state.
        # Keep the tree from doing expensive layout/scroll work before handling
        # the next click, especially when a library contains many scripts.
        self.sidebar.setAnimated(False)
        self.sidebar.setUniformRowHeights(True)
        self.sidebar.setExpandsOnDoubleClick(False)
        self.sidebar.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.sidebar.currentItemChanged.connect(self._selection_changed)
        sidebar_panel = QWidget()
        sidebar_panel.setObjectName("sidebarPanel")
        sidebar_panel.setMinimumWidth(220)
        sidebar_panel.setMaximumWidth(360)
        sidebar_layout = QVBoxLayout(sidebar_panel)
        sidebar_layout.setContentsMargins(SECTION, PAGE, SECTION, SECTION)
        sidebar_layout.setSpacing(SMALL)
        brand = QLabel("SillyScripts")
        brand.setProperty("role", "brand")
        sidebar_layout.addWidget(brand)
        subtitle = QLabel("Blender & Python tools")
        subtitle.setProperty("role", "help")
        sidebar_layout.addWidget(subtitle)
        sidebar_layout.addSpacing(PAGE)
        libraries_label = QLabel("Script libraries")
        libraries_label.setProperty("role", "muted")
        sidebar_layout.addWidget(libraries_label)
        sidebar_layout.addWidget(self.sidebar, 1)
        self.create_script_button = QPushButton("Create blank script")
        self.create_batch_button = QPushButton("Create blank batch script")
        style_button(self.create_script_button, "plus")
        style_button(self.create_batch_button, "plus")
        self.create_script_button.clicked.connect(lambda: self._create_script("blank"))
        self.create_batch_button.clicked.connect(lambda: self._create_script("batch"))
        sidebar_layout.addWidget(self.create_script_button)
        sidebar_layout.addWidget(self.create_batch_button)
        sidebar_layout.addSpacing(SMALL)
        self.settings_shortcut = QPushButton("Settings")
        style_button(self.settings_shortcut, "settings", "quiet")
        sidebar_layout.addWidget(self.settings_shortcut)
        splitter.addWidget(sidebar_panel)
        main_content = QWidget()
        main_content.setObjectName("mainContent")
        content_layout = QVBoxLayout(main_content)
        content_layout.setContentsMargins(PAGE, PAGE, PAGE, SECTION)
        content_layout.setSpacing(SECTION)
        header = QHBoxLayout()
        heading_layout = QVBoxLayout()
        heading_layout.setSpacing(TINY)
        self.script_heading = QLabel("Select a script")
        self.script_heading.setTextFormat(Qt.TextFormat.PlainText)
        self.script_heading.setProperty("role", "pageHeading")
        self.script_heading.setWordWrap(True)
        self.script_subtitle = QLabel("Choose a script library to get started")
        self.script_subtitle.setTextFormat(Qt.TextFormat.PlainText)
        self.script_subtitle.setProperty("role", "muted")
        self.script_subtitle.setWordWrap(True)
        heading_layout.addWidget(self.script_heading)
        heading_layout.addWidget(self.script_subtitle)
        header.addLayout(heading_layout, 1)
        self.script_badge = QLabel("Idle")
        self.script_badge.setProperty("role", "badge")
        header.addWidget(self.script_badge, 0, Qt.AlignmentFlag.AlignTop)
        content_layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.parameters = ParametersPanel(
            batch_parameters=batch_info.parameters if not batch_info.inspection_error else None,
            batch_error=batch_info.inspection_error,
        )
        self.log = LogPanel()
        self.settings_panel = SettingsPanel(self.settings)
        self.tabs.addTab(self.parameters, icon("file-code"), "Script")
        self.tabs.addTab(self.log, icon("terminal"), "Log")
        self.tabs.addTab(self.settings_panel, icon("settings"), "Settings")
        self.settings_shortcut.clicked.connect(lambda: self.tabs.setCurrentWidget(self.settings_panel))
        content_layout.addWidget(self.tabs, 1)
        splitter.addWidget(main_content)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([244, 856])
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
                    self._loaded_parameter_configs.discard(path)
                scripts[path] = info
                if not info.inspection_error and path not in self._loaded_parameter_configs:
                    try:
                        saved, batch_saved = self.parameter_configs.load(
                            path, info.parameters, self.parameters.batch_parameters or [],
                        )
                        state.parameter_values.update(saved)
                        state.batch_parameter_values.update(batch_saved)
                    except (OSError, ParameterConfigError) as exc:
                        message += f" Could not restore parameters for {path.name}: {exc}"
                    self._loaded_parameter_configs.add(path)
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
                group.setIcon(0, icon("folder"))
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
        self._update_header()
        if path:
            self._update_item(path)

    def _update_item(self, path: Path) -> None:
        script = self.scripts[path]
        state = self.processes.state_for(path)
        suffix = "  [Running]" if state.is_running else "  [Unavailable]" if script.inspection_error else ""
        self.items[path].setText(0, script.name + suffix)
        self.items[path].setIcon(0, icon("play" if state.is_running else "file-code"))
        self.items[path].setToolTip(0, f"{path}\n{script.inspection_error or state.status}")

    def _update_header(self) -> None:
        """Presentation only; the process manager remains the state owner."""
        script = self.scripts.get(self.active_path)
        if script is None:
            self.script_heading.setText("Select a script")
            self.script_subtitle.setText("Choose a script from a library in the sidebar")
            self.script_badge.setText("Idle")
            set_variant(self.script_badge, "status", "idle")
            return
        state = self.processes.state_for(script.path)
        self.script_heading.setText(script.name.replace("_", " ").replace("-", " ").title())
        self.script_heading.setToolTip(str(script.path))
        self.script_subtitle.setText(f"{state.runtime} · {script.path.name}")
        self.script_subtitle.setToolTip(str(script.path))
        self.script_badge.setText("Unavailable" if script.inspection_error else "Finished" if state.status.startswith("Finished") else state.status)
        self.script_badge.setToolTip(script.inspection_error or state.status)
        status = "stopping" if state.status.startswith("Stopping") else "running" if state.is_running else "error" if script.inspection_error or state.status.startswith(("Failed", "Error", "Crashed")) else "idle"
        set_variant(self.script_badge, "status", status)

    def _run_active(self) -> None:
        if not self.active_path or not self.parameters.form:
            return
        self.parameters.save_values()
        self.parameters.show_error("")
        state = self.processes.state_for(self.active_path)
        executable = self.settings_panel.executable(state.runtime)
        try:
            arguments = self.parameters.form.arguments()
            payload = None
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
            # arguments() commits pending spinbox edits; snapshot afterwards so
            # the config represents the values actually passed to this run.
            self.parameters.save_values()
            config_warning = ""
            try:
                self.parameter_configs.save(
                    self.active_path, self.scripts[self.active_path].parameters,
                    state.parameter_values, self.parameters.batch_parameters or [],
                    state.batch_parameter_values,
                )
            except (OSError, ValueError, TypeError) as exc:
                config_warning = f"Could not save parameter config: {exc}"
                self.parameters.show_error(config_warning)
            started = self.processes.start(
                self.scripts[self.active_path], executable,
                [] if payload is not None else arguments, batch_payload=payload,
            )
            if config_warning:
                self.statusBar().showMessage(config_warning)
            elif started and payload is not None:
                self.statusBar().showMessage(f"Started batch run for {len(selection.files)} blend file(s).")
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
        self._update_header()

    def _stop_active(self) -> None:
        if self.active_path:
            self.processes.stop(self.active_path)

    def _state_changed(self, path: Path) -> None:
        if path in self.items:
            self._update_item(path)
        if path == self.active_path:
            self.parameters.update_state()
            self.log.update_state(self.scripts[path], self.processes.state_for(path))
            self._update_header()

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
