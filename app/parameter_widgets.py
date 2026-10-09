"""Generate Qt controls from neutral parameter models."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QSpinBox, QVBoxLayout, QWidget,
)

from .arguments import build_script_arguments
from .models import ParameterValue, ScriptParameter
from .string_widgets import FilePicker, FolderPicker, MultiValueInputs, StringInputs


class ParameterEditor(QWidget):
    changed = Signal()

    def __init__(self, parameter: ScriptParameter, saved: ParameterValue | None = None) -> None:
        super().__init__()
        self.parameter = parameter
        self.include: QCheckBox | None = None
        self.string_inputs: StringInputs | None = None
        self.multiple_inputs: MultiValueInputs | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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
        elif parameter.nargs == "+":
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
                control = QLineEdit()
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
                control = QLineEdit()
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
        layout.addWidget(self.string_inputs or self.multiple_inputs or self.control, 1)
        cli_name = ", ".join(parameter.option_strings) or f"{parameter.name} (positional)"
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
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        if not parameters:
            layout.addRow(QLabel("This script does not define any parameters."))
        for parameter in parameters:
            editor = ParameterEditor(parameter, saved.get(parameter.name))
            editor.changed.connect(self.changed)
            self.editors[parameter.name] = editor
            label = QLabel(parameter.label + (" *" if parameter.required else ""))
            if parameter.required:
                label.setStyleSheet("font-weight: 600;")
            label.setBuddy(editor.control)
            wrapper = QWidget()
            field_layout = QVBoxLayout(wrapper)
            field_layout.setContentsMargins(0, 0, 0, 8)
            field_layout.addWidget(editor)
            if parameter.help:
                help_label = QLabel(parameter.help)
                help_label.setWordWrap(True)
                help_label.setTextFormat(Qt.TextFormat.PlainText)
                field_layout.addWidget(help_label)
            layout.addRow(label, wrapper)

    def values(self) -> dict[str, ParameterValue]:
        return {name: editor.value() for name, editor in self.editors.items()}

    def arguments(self) -> list[str]:
        # Commit pending edits only at launch, never while handling valueChanged:
        # reformatting on each keystroke would disrupt decimal/negative input.
        for editor in self.editors.values():
            if isinstance(editor.control, (QSpinBox, QDoubleSpinBox)):
                editor.control.interpretText()
        return build_script_arguments(self.parameters, self.values())
