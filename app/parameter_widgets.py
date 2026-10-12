"""Generate Qt controls from neutral parameter models."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
    QLabel, QLayout, QLineEdit, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from .arguments import build_script_arguments
from .models import ParameterValue, ScriptParameter
from .string_widgets import FilePicker, FolderPicker, MultiValueInputs, StringInputs
from .ui.theme import CONTROL_HEIGHT, LABEL_WIDTH, SECTION, SMALL, TINY


class ParameterEditor(QWidget):
    changed = Signal()

    def __init__(self, parameter: ScriptParameter, saved: ParameterValue | None = None) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.parameter = parameter
        self.include: QCheckBox | None = None
        self.string_inputs: StringInputs | None = None
        self.multiple_inputs: MultiValueInputs | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SMALL)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        boolean = parameter.action_type in ("store_true", "store_false", "boolean_optional")
        default = parameter.default
        initial = saved.value if saved else None if parameter.action_type == "append" else default
        self.control: QWidget

        if boolean:
            control = QCheckBox()
            if default is None:
                control.setTristate(True)
            control.setCheckState(
                Qt.CheckState.PartiallyChecked if initial is None
                else Qt.CheckState.Checked if bool(initial) else Qt.CheckState.Unchecked
            )
            control.setText("True (uncheck to pass the flag)" if parameter.action_type == "store_false" else "Enabled")
            if parameter.action_type != "boolean_optional" and default is (parameter.action_type == "store_true") and not parameter.required:
                # No opposite flag exists, so the other value cannot be encoded.
                control.setEnabled(False)
                control.setText(f"Fixed by script default: {default}")
            control.stateChanged.connect(self.changed)
            self.control = control
        elif parameter.is_string:
            self.string_inputs = StringInputs(parameter, initial)
            self.string_inputs.changed.connect(self.changed)
            self.control = self.string_inputs.first_control
        elif parameter.nargs == "+" or parameter.action_type == "append":
            self.multiple_inputs = MultiValueInputs(parameter, initial)
            self.multiple_inputs.changed.connect(self.changed)
            self.control = self.multiple_inputs.first_control
        elif parameter.is_path_selection and parameter.is_folder_selection:
            control = FolderPicker(parameter.label, "" if initial is None else str(initial))
            control.changed.connect(self.changed)
            self.control = control
        elif parameter.is_path_selection and parameter.choices is None:
            control = FilePicker(parameter.label, "" if initial is None else str(initial))
            control.changed.connect(self.changed)
            self.control = control
        elif parameter.choices is not None:
            control = QComboBox()
            control.setPlaceholderText("Select a value…")
            for choice in parameter.choices:
                control.addItem(str(choice), choice)
            index = next((i for i, choice in enumerate(parameter.choices) if str(choice) == str(initial)), -1)
            control.setCurrentIndex(index)
            control.currentIndexChanged.connect(self.changed)
            self.control = control
        elif parameter.parameter_type is int:
            if not parameter.required and default is None:
                control = QLineEdit("" if initial is None else str(initial))
                control.setPlaceholderText("Optional")
                control.textChanged.connect(self.changed)
            else:
                control = QSpinBox()
                control.setRange(-2_147_483_648, 2_147_483_647)
                initial_number = int(initial) if initial is not None else 0
                if not control.minimum() <= initial_number <= control.maximum():
                    raise ValueError(f"{parameter.label}: default exceeds the 32-bit integer widget range.")
                control.setValue(initial_number)
                control.valueChanged.connect(self.changed)
            self.control = control
        elif parameter.parameter_type is float:
            if not parameter.required and default is None:
                control = QLineEdit("" if initial is None else str(initial))
                control.setPlaceholderText("Optional")
                control.textChanged.connect(self.changed)
            else:
                control = QDoubleSpinBox()
                control.setDecimals(8)
                control.setRange(-1_000_000_000_000.0, 1_000_000_000_000.0)
                initial_number = float(initial) if initial is not None else 0.0
                if not math.isfinite(initial_number) or not control.minimum() <= initial_number <= control.maximum():
                    raise ValueError(f"{parameter.label}: default must be finite and within ±1 trillion.")
                control.setValue(initial_number)
                if not math.isclose(control.value(), initial_number, rel_tol=1e-12, abs_tol=0.0):
                    raise ValueError(f"{parameter.label}: default needs more than eight decimal places.")
                control.valueChanged.connect(self.changed)
            self.control = control
        else:
            control = QLineEdit("" if initial is None else str(initial))
            control.setPlaceholderText("Required" if parameter.required else "Optional")
            control.textChanged.connect(self.changed)
            self.control = control

        needs_numeric_presence = (
            parameter.required
            and parameter.action_type != "append"
            and parameter.nargs != "+"
            and parameter.parameter_type in (int, float)
            and parameter.choices is None
            and default is None
        )
        if not boolean and needs_numeric_presence:
            self.include = QCheckBox("Provide value" if parameter.required else "Include")
            enabled = saved.enabled if saved else (default is not None)
            self.include.setChecked(enabled)
            self.include.setToolTip("Unchecked: omit this argument and let the script use its own default.")
            control_widget = self.string_inputs or self.multiple_inputs or self.control
            control_widget.setEnabled(enabled)
            self.include.toggled.connect(control_widget.setEnabled)
            self.include.toggled.connect(self.changed)
            layout.addWidget(self.include)
        self.control.setAccessibleName(parameter.label)
        layout.addWidget(self.string_inputs or self.multiple_inputs or self.control, 1, Qt.AlignmentFlag.AlignTop)
        cli_name = ", ".join(parameter.option_strings) or f"{parameter.name} (positional)"
        self.setProperty("tooltipKind", "parameter")
        self.setToolTip(f"{cli_name}\n{parameter.help or ''}")

    def value(self) -> ParameterValue:
        control = self.control
        if self.string_inputs is not None:
            values = self.string_inputs.values()
            result = values[0] if len(values) == 1 else values
        elif self.multiple_inputs is not None:
            result = self.multiple_inputs.values()
        elif isinstance(control, FilePicker):
            result = control.path()
        elif isinstance(control, FolderPicker):
            result = control.path()
        elif isinstance(control, QCheckBox):
            result = None if control.checkState() == Qt.CheckState.PartiallyChecked else control.isChecked()
        elif isinstance(control, QComboBox):
            result = control.currentData() if control.currentIndex() >= 0 else None
        elif isinstance(control, (QSpinBox, QDoubleSpinBox)):
            result = control.value()
        else:
            result = control.text()
        return ParameterValue(result, self.include.isChecked() if self.include else True)


class ParameterForm(QWidget):
    changed = Signal()

    def __init__(self, parameters: list[ScriptParameter], saved: dict[str, ParameterValue]) -> None:
        super().__init__()
        self.parameters = parameters
        self.editors: dict[str, ParameterEditor] = {}
        self.labels: dict[str, QLabel] = {}
        self.fields: dict[str, QWidget] = {}
        # Keep the complete field (repeatable inputs and help) in a single grid
        # cell. QFormLayout's wrapping/height-for-width cache can reposition the
        # next field before the preceding field has finished shrinking.
        layout = QGridLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(SECTION)
        layout.setVerticalSpacing(SECTION)
        layout.setColumnStretch(1, 1)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        if not parameters:
            layout.addWidget(QLabel("This script does not define any parameters."), 0, 0, 1, 2)
        for row, parameter in enumerate(parameters):
            editor = ParameterEditor(parameter, saved.get(parameter.name))
            self.editors[parameter.name] = editor
            label = QLabel(parameter.label + (" *" if parameter.required else ""))
            label.setMinimumHeight(CONTROL_HEIGHT)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
            label.setMinimumWidth(LABEL_WIDTH)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if parameter.required:
                label.setProperty("role", "required")
            label.setBuddy(editor.control)
            wrapper = QWidget()
            wrapper.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            field_layout = QVBoxLayout(wrapper)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(TINY)
            field_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
            field_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            field_layout.addWidget(editor, 0, Qt.AlignmentFlag.AlignTop)
            if parameter.help and len(parameter.help) <= 160:
                help_label = QLabel(parameter.help)
                help_label.setProperty("role", "help")
                help_label.setWordWrap(True)
                help_label.setTextFormat(Qt.TextFormat.PlainText)
                field_layout.addWidget(help_label)
            self.labels[parameter.name] = label
            self.fields[parameter.name] = wrapper
            layout.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(wrapper, row, 1)
            editor.changed.connect(lambda editor=editor, wrapper=wrapper: self._refresh_row(editor, wrapper))

    def _refresh_row(self, editor: ParameterEditor, wrapper: QWidget) -> None:
        """Propagate repeatable-control height changes through the entire row.

        Invalidate from the inside out so the grid measures the complete field,
        including wrapped help, after a repeatable input is added or removed.
        """
        for widget in (editor, wrapper, self):
            widget.layout().invalidate()
            widget.layout().activate()
            widget.updateGeometry()
        self.changed.emit()

    def values(self) -> dict[str, ParameterValue]:
        return {name: editor.value() for name, editor in self.editors.items()}

    def arguments(self) -> list[str]:
        # Commit pending edits only at launch, never while handling valueChanged:
        # reformatting on each keystroke would disrupt decimal/negative input.
        for editor in self.editors.values():
            if isinstance(editor.control, (QSpinBox, QDoubleSpinBox)):
                editor.control.interpretText()
        return build_script_arguments(self.parameters, self.values())
