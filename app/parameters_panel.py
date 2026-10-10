"""Script parameter page, composed separately from window/navigation logic."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .arguments import ParameterValidationError, build_process_arguments, build_script_arguments
from .batch_support import BATCH_RUNNER
from .models import ScriptInfo, ScriptParameter, ScriptRuntimeState
from .parameter_widgets import ParameterForm
from .ui.components import Section
from .ui.theme import LABEL_WIDTH, PAGE, SECTION, SMALL, TINY, monospace_font, style_button


class ParametersPanel(QWidget):
    run_requested = Signal()
    stop_requested = Signal()
    runtime_changed = Signal(str)

    def __init__(self, batch_parameters: list[ScriptParameter] | None = None, batch_error: str | None = None) -> None:
        super().__init__()
        self.batch_parameters = batch_parameters
        self.batch_error = batch_error
        self.script: ScriptInfo | None = None
        self.state: ScriptRuntimeState | None = None
        self.form: ParameterForm | None = None
        self.batch_form: ParameterForm | None = None
        self.batch_error_label: QLabel | None = None
        self.executable = ""
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0, SECTION, 0, 0)
        self.layout().setSpacing(SECTION)
        self.set_script(None, None)

    def set_script(self, script: ScriptInfo | None, state: ScriptRuntimeState | None) -> None:
        while self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.script, self.state, self.form = script, state, None
        content = QWidget()
        layout = QVBoxLayout(content)
        content.setObjectName("pageContent")
        layout.setContentsMargins(0, 0, SMALL, SECTION)
        layout.setSpacing(PAGE)
        scroll = QScrollArea()
        self.scroll = scroll
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.layout().addWidget(scroll)
        if not script or not state:
            label = QLabel("Select a script from the sidebar.\nChoose a script folder in Settings to load your own scripts.")
            label.setWordWrap(True)
            label.setProperty("role", "muted")
            layout.addWidget(label)
            layout.addStretch(1)
            return

        if state.batch_mode:
            state.runtime = "Blender"

        self.execution_group = Section("Execution")
        execution_layout = QFormLayout(self.execution_group.body)
        execution_layout.setContentsMargins(0, SMALL, 0, 0)
        execution_layout.setHorizontalSpacing(SECTION)
        execution_layout.setVerticalSpacing(SMALL)
        execution_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        execution_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.runtime = QComboBox()
        self.runtime.addItems(["Blender", "Python"])
        self.runtime.setAccessibleName("Runtime")
        self.runtime.setCurrentText(state.runtime)
        self.runtime.currentTextChanged.connect(self._runtime_changed)
        runtime_label = QLabel("Runtime")
        runtime_label.setMinimumWidth(LABEL_WIDTH)
        runtime_label.setBuddy(self.runtime)
        execution_layout.addRow(runtime_label, self.runtime)
        self.run_mode = QComboBox()
        self.run_mode.addItems(["Single run", "Batch mode"])
        self.run_mode.setAccessibleName("Run mode")
        self.run_mode.setCurrentIndex(1 if state.batch_mode else 0)
        self.run_mode.currentIndexChanged.connect(self._run_mode_changed)
        if self.batch_parameters is None:
            self.run_mode.setItemText(1, "Batch mode (unavailable)")
            self.run_mode.setEnabled(False)
        mode_label = QLabel("Run mode")
        mode_label.setMinimumWidth(LABEL_WIDTH)
        mode_label.setBuddy(self.run_mode)
        execution_layout.addRow(mode_label, self.run_mode)
        layout.addWidget(self.execution_group)
        self.blender_group = Section("Blender options")
        blender_layout = QVBoxLayout(self.blender_group.body)
        blender_layout.setContentsMargins(0, SMALL, 0, 0)
        blender_layout.setSpacing(TINY)
        self.background = QCheckBox("Run Blender in background")
        self.background.setChecked(state.blender_background)
        self.background.toggled.connect(self._background_changed)
        blender_layout.addWidget(self.background)
        self.resync = QCheckBox("Disable library override auto resync")
        self.resync.setChecked(state.disable_override_resync)
        self.resync.toggled.connect(self._resync_changed)
        blender_layout.addWidget(self.resync)
        layout.addWidget(self.blender_group)

        self.parameter_group = Section("Script parameters", subdued=True)
        parameter_layout = QVBoxLayout(self.parameter_group.body)
        parameter_layout.setContentsMargins(0, SMALL, 0, 0)
        parameter_layout.setSpacing(SMALL)
        required_note = QLabel("Fields marked * are required")
        required_note.setProperty("role", "help")
        parameter_layout.addWidget(required_note)
        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setProperty("role", "error")
        if not script.inspection_error:
            try:
                self.form = ParameterForm(script.parameters, state.parameter_values)
                parameter_layout.addWidget(self.form)
                self.form.changed.connect(self._values_changed)
            except (ValueError, TypeError, OverflowError) as exc:
                script.inspection_error = f"Cannot build parameter controls: {exc}"
        self.error_label.setText(script.inspection_error or "")
        self.error_label.setVisible(bool(script.inspection_error))
        parameter_layout.addWidget(self.error_label)
        layout.addWidget(self.parameter_group)

        self.batch_group = Section("Batch file selection")
        batch_layout = QVBoxLayout(self.batch_group.body)
        batch_layout.setContentsMargins(0, SMALL, 0, 0)
        if self.batch_parameters is not None:
            self.batch_form = ParameterForm(self.batch_parameters, state.batch_parameter_values)
            self.batch_form.changed.connect(self._values_changed)
            batch_layout.addWidget(self.batch_form)
            self.batch_error_label = QLabel()
            self.batch_error_label.setTextFormat(Qt.TextFormat.PlainText)
            self.batch_error_label.setWordWrap(True)
            self.batch_error_label.setProperty("role", "error")
            self.batch_error_label.hide()
            batch_layout.addWidget(self.batch_error_label)
        else:
            error = QLabel(f"Batch mode is unavailable: {self.batch_error or 'could not load the batch selection options.'}")
            error.setWordWrap(True)
            batch_layout.addWidget(error)
        self.batch_group.setVisible(state.batch_mode)
        layout.addWidget(self.batch_group)

        self.filter_group = Section("Output filtering")
        filter_layout = QFormLayout(self.filter_group.body)
        filter_layout.setContentsMargins(0, SMALL, 0, 0)
        filter_layout.setHorizontalSpacing(SECTION)
        filter_layout.setVerticalSpacing(SMALL)
        filter_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        filter_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.output_filter = QLineEdit(state.output_filter)
        self.output_filter.setPlaceholderText("For example: [SCRIPT]")
        self.output_filter.textChanged.connect(lambda text: setattr(state, "output_filter", text))
        output_label = QLabel("Output filter")
        output_label.setMinimumWidth(LABEL_WIDTH)
        output_label.setBuddy(self.output_filter)
        filter_layout.addRow(output_label, self.output_filter)
        self.filter_enabled = QCheckBox("Filter displayed output")
        self.filter_enabled.setChecked(state.filter_enabled)
        self.filter_enabled.toggled.connect(lambda value: setattr(state, "filter_enabled", value))
        filter_layout.addRow(self.filter_enabled)
        self.filter_log_enabled = QCheckBox("Also filter output saved to the log file")
        self.filter_log_enabled.setChecked(state.filter_log_enabled)
        self.filter_log_enabled.toggled.connect(lambda value: setattr(state, "filter_log_enabled", value))
        filter_layout.addRow(self.filter_log_enabled)
        filter_note = QLabel("Log filtering applies to output received during the next run.")
        filter_note.setWordWrap(True)
        filter_note.setProperty("role", "help")
        filter_layout.addRow(filter_note)
        layout.addWidget(self.filter_group)

        command_group = Section("Command preview")
        command_layout = QVBoxLayout(command_group.body)
        command_layout.setContentsMargins(0, SMALL, 0, 0)
        command_layout.setSpacing(SMALL)
        command_note = QLabel("PowerShell syntax · updates as you edit")
        command_note.setProperty("role", "help")
        command_layout.addWidget(command_note)
        self.command_preview = QPlainTextEdit()
        self.command_preview.setProperty("role", "console")
        self.command_preview.setFont(monospace_font())
        self.command_preview.setAccessibleName("Command preview")
        self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumBlockCount(200)
        self.command_preview.setMinimumHeight(144)
        self.command_preview.setMaximumHeight(192)
        self.command_preview.setPlaceholderText("The command preview will appear here.")
        command_layout.addWidget(self.command_preview)
        layout.addWidget(command_group)
        footer = QWidget()
        footer.setObjectName("actionFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(0, SECTION, 0, 0)
        buttons.setSpacing(SMALL)
        self.run_button = QPushButton("Run Script")
        style_button(self.run_button, "play", "primary")
        self.run_button.clicked.connect(self.run_requested)
        self.stop_button = QPushButton("Stop")
        style_button(self.stop_button, "stop", "danger")
        self.stop_button.clicked.connect(self.stop_requested)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.run_button)
        self.layout().addWidget(footer)
        layout.addStretch(1)
        self.update_state()
        self.refresh_command_preview()

    def save_values(self) -> None:
        if self.state and self.form:
            self.state.parameter_values = self.form.values()
        if self.state and self.batch_form:
            self.state.batch_parameter_values = self.batch_form.values()

    def _runtime_changed(self, runtime: str) -> None:
        if self.state:
            self.state.runtime = runtime
            self.update_state()
            self.runtime_changed.emit(runtime)

    def _run_mode_changed(self, index: int) -> None:
        if not self.state:
            return
        self.state.batch_mode = index == 1
        if self.state.batch_mode and self.runtime.currentText() != "Blender":
            self.runtime.setCurrentText("Blender")
        self.runtime.setEnabled(not self.state.batch_mode)
        self.batch_group.setVisible(self.state.batch_mode)
        self.update_state()
        self.refresh_command_preview()

    def _values_changed(self) -> None:
        self.save_values()
        self.refresh_command_preview()

    def _background_changed(self, value: bool) -> None:
        if self.state:
            self.state.blender_background = value
            self.refresh_command_preview()

    def _resync_changed(self, value: bool) -> None:
        if self.state:
            self.state.disable_override_resync = value
            self.refresh_command_preview()

    def set_executable(self, executable: str) -> None:
        self.executable = executable
        self.refresh_command_preview()

    @staticmethod
    def _powershell_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    def refresh_command_preview(self) -> None:
        if not self.script or not self.state or not self.form:
            return
        try:
            script_arguments = build_script_arguments(self.script.parameters, self.form.values())
            if self.state.batch_mode:
                process_arguments = build_process_arguments(
                    BATCH_RUNNER,
                    ["--manifest", "<launcher batch manifest created at run>"],
                    self.state,
                )
            else:
                process_arguments = build_process_arguments(self.script.path, script_arguments, self.state)
            prefix_count = len(process_arguments) - len(script_arguments)
            if self.state.batch_mode:
                prefix_count = len(process_arguments)
            display_groups = [[token] for token in process_arguments[:prefix_count]]
            if not self.state.batch_mode:
                display_groups.extend(self._group_script_arguments(script_arguments))
            lines = [f"& {self._powershell_quote(self.executable)} `"]
            for index, group in enumerate(display_groups):
                continuation = " `" if index < len(display_groups) - 1 else ""
                quoted = " ".join(self._powershell_quote(token) for token in group)
                lines.append(f"    {quoted}{continuation}")
            if self.state.batch_mode:
                lines.extend(["", f"# Target script: {self.script.path}"])
                lines.append("# Target script arguments passed once for each file:")
                lines.extend(
                    "#   " + " ".join(self._powershell_quote(token) for token in group)
                    for group in self._group_script_arguments(script_arguments)
                )
                if self.batch_form:
                    selection_arguments = self.batch_form.arguments()
                    lines.append("# Batch selection arguments stored in the manifest:")
                    lines.extend(
                        "#   " + " ".join(self._powershell_quote(token) for token in group)
                        for group in self._group_script_arguments(selection_arguments, self.batch_form.parameters)
                    )
            preview = "\n".join(lines)
        except (ParameterValidationError, ValueError, TypeError) as exc:
            preview = f"Command preview unavailable: {exc}"
        self.command_preview.setPlainText(preview)

    def _group_script_arguments(
        self,
        arguments: list[str],
        parameters: list[ScriptParameter] | None = None,
    ) -> list[list[str]]:
        """Keep each option and its argparse-defined values together for display."""
        parameters = parameters if parameters is not None else self.script.parameters
        parameters_by_option = {
            option: parameter
            for parameter in parameters
            for option in parameter.option_strings
        }
        groups: list[list[str]] = []
        index = 0
        while index < len(arguments):
            token = arguments[index]
            if token == "--":
                groups.append(arguments[index:])
                break
            option = token.split("=", 1)[0]
            parameter = parameters_by_option.get(option)
            if parameter is None or "=" in token:
                groups.append([token])
                index += 1
                continue
            action = parameter.action_type
            nargs = parameter.nargs
            if action in ("store_true", "store_false", "boolean_optional"):
                count = 0
            elif nargs is None:
                count = 1
            elif isinstance(nargs, int):
                count = nargs
            elif nargs == "?":
                count = 1 if index + 1 < len(arguments) else 0
            else:
                count = 0
                for candidate in arguments[index + 1:]:
                    if candidate.split("=", 1)[0] in parameters_by_option:
                        break
                    count += 1
            group = arguments[index:index + 1 + count]
            groups.append(group)
            index += len(group)
        return groups

    def update_state(self) -> None:
        if not self.script or not self.state:
            return
        running = self.state.is_running
        self.execution_group.setEnabled(not running)
        self.blender_group.setEnabled(not running and self.state.runtime == "Blender")
        self.run_mode.setEnabled(not running and self.batch_parameters is not None)
        self.runtime.setEnabled(not running and not self.state.batch_mode)
        self.parameter_group.setEnabled(not running)
        self.batch_group.setEnabled(not running)
        self.filter_group.setEnabled(not running)
        self.background.setEnabled(self.state.runtime == "Blender")
        self.resync.setEnabled(self.state.runtime == "Blender")
        batch_ready = not self.state.batch_mode or self.batch_form is not None
        self.run_button.setEnabled(not running and not self.script.inspection_error and self.form is not None and batch_ready)
        self.stop_button.setEnabled(running)
        self.stop_button.setText("Force Stop" if self.state.status == "Stopping…" else "Stop")
        self.status.setText(self.state.status)

    def show_error(self, message: str) -> None:
        if self.script:
            if self.state and self.state.batch_mode and self.batch_error_label:
                self.batch_error_label.setText(message)
                self.batch_error_label.setVisible(bool(message))
            else:
                self.error_label.setText(message)
                self.error_label.setVisible(bool(message))
