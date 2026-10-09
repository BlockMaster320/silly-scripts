"""Turn neutral form values into argv, without a shell or argparse actions."""

from __future__ import annotations

import math
from pathlib import Path

from .models import ParameterValue, ScriptParameter, ScriptRuntimeState
from .shot_selection import format_shot_selection, parse_shot_selection


class ParameterValidationError(ValueError):
    pass


def build_script_arguments(
    parameters: list[ScriptParameter], values: dict[str, ParameterValue]
) -> list[str]:
    options: list[str] = []
    positionals: list[str] = []
    omitted_positional = False
    for parameter in parameters:
        supplied = values.get(parameter.name, ParameterValue(enabled=False))
        label = parameter.label
        if parameter.action_type == "boolean_optional":
            if supplied.value is None:
                if parameter.required:
                    raise ParameterValidationError(f"Please choose a value for {label}.")
                continue
            option = parameter.option
            if not supplied.value and option:
                option = f"--no-{option[2:]}"
            if option:
                options.append(option)
            continue
        if parameter.action_type in ("store_true", "store_false"):
            # The checkbox represents the resulting boolean value. For
            # store_false, an unchecked box emits the flag that sets False.
            include = supplied.value is (parameter.action_type == "store_true")
            if parameter.required and not include:
                target = "checked" if parameter.action_type == "store_true" else "unchecked"
                raise ParameterValidationError(f"{label} must be {target} to pass its required flag.")
            if include and parameter.option:
                options.append(parameter.option)
            continue

        value = supplied.value
        items = list(value) if isinstance(value, (list, tuple)) else [value]
        items = [item for item in items if item is not None and item != ""]
        empty = not items
        if not supplied.enabled or empty:
            if parameter.required:
                raise ParameterValidationError(f"Please provide {label}.")
            if not parameter.option:
                omitted_positional = True
            continue

        if parameter.is_shot_selection:
            try:
                entries = format_shot_selection([
                    interval for item in items for interval in parse_shot_selection(str(item))
                ])
            except ValueError as exc:
                raise ParameterValidationError(f"{label}: {exc}") from exc
            if parameter.action_type == "append":
                for entry in entries:
                    options.extend([parameter.option, entry])
            else:
                options.extend([parameter.option, ",".join(entries)])
            continue

        if parameter.is_string:
            text_values = [str(item) for item in items]
            if parameter.choices is not None and any(item not in parameter.choices for item in text_values):
                raise ParameterValidationError(f"Choose one of the listed values for {label}.")
            scalar = parameter.nargs in (None, "?")
            if parameter.name == "exclude_folders" and parameter.is_folder_selection and parameter.action_type == "store" and scalar:
                # Older generated batch scripts accept a comma-separated scalar.
                text_values = [",".join(text_values)]
            multiple = parameter.nargs not in (None, "?")
            if multiple:
                if isinstance(parameter.nargs, int) and len(text_values) != parameter.nargs:
                    raise ParameterValidationError(f"{label} needs exactly {parameter.nargs} values.")
                if parameter.option:
                    if any(item.startswith("-") for item in text_values[1:]):
                        raise ParameterValidationError(f"{label}: only the first value may begin with '-'.")
                    if text_values[0].startswith("-"):
                        options.append(f"{parameter.option}={text_values[0]}")
                        options.extend(text_values[1:])
                    else:
                        options.extend([parameter.option, *text_values])
                else:
                    if omitted_positional:
                        raise ParameterValidationError("Fill earlier positional arguments before later ones.")
                    positionals.extend(text_values)
            elif parameter.option:
                for item in text_values:
                    if item.startswith("-"):
                        options.append(f"{parameter.option}={item}")
                    else:
                        options.extend([parameter.option, item])
            else:
                if len(text_values) != 1:
                    raise ParameterValidationError(f"{label} accepts one positional value. Remove the extra rows.")
                if omitted_positional:
                    raise ParameterValidationError("Fill earlier positional arguments before later ones.")
                positionals.extend(text_values)
            continue

        if parameter.nargs == "+":
            converted_values: list[str] = []
            converter = parameter.parameter_type or str
            for item in items:
                try:
                    converted = converter(item)
                    if isinstance(converted, float) and not math.isfinite(converted):
                        raise ValueError("Use a finite number.")
                except (ValueError, TypeError, OverflowError) as exc:
                    raise ParameterValidationError(f"{label}: {exc}") from exc
                if parameter.choices is not None and converted not in parameter.choices:
                    raise ParameterValidationError(f"Choose one of the listed values for {label}.")
                converted_values.append(str(converted))
            if parameter.option:
                if parameter.parameter_type not in (int, float) and any(value.startswith("-") for value in converted_values[1:]):
                    raise ParameterValidationError(f"{label}: only the first value may begin with '-'.")
                if parameter.parameter_type not in (int, float) and converted_values[0].startswith("-"):
                    options.append(f"{parameter.option}={converted_values[0]}")
                    options.extend(converted_values[1:])
                    continue
                options.extend([parameter.option, *converted_values])
            else:
                if omitted_positional:
                    raise ParameterValidationError("Fill earlier positional arguments before later ones.")
                positionals.extend(converted_values)
            continue

        try:
            converter = parameter.parameter_type or str
            converted = converter(value)
            if isinstance(converted, float) and not math.isfinite(converted):
                raise ValueError("Use a finite number.")
        except (ValueError, TypeError, OverflowError) as exc:
            raise ParameterValidationError(f"{label}: {exc}") from exc
        if parameter.choices is not None and converted not in parameter.choices:
            raise ParameterValidationError(f"Choose one of the listed values for {label}.")

        text = str(value)
        if parameter.option:
            # Equals form preserves a string beginning with '-' as a value.
            if text.startswith("-"):
                options.append(f"{parameter.option}={text}")
            else:
                options.extend([parameter.option, text])
        else:
            if omitted_positional:
                raise ParameterValidationError("Fill earlier positional arguments before later ones.")
            positionals.append(text)
    if positionals:
        options.extend(["--", *positionals])
    return options


def build_process_arguments(
    script_path: Path, script_arguments: list[str], state: ScriptRuntimeState
) -> list[str]:
    if state.runtime == "Python":
        return [str(script_path), *script_arguments]
    if state.runtime != "Blender":
        raise ValueError(f"Unknown runtime: {state.runtime}")
    options: list[str] = []
    if state.blender_background:
        options.append("--background")
    if state.disable_override_resync:
        options.append("--disable-liboverride-auto-resync")
    return [*options, "--python", str(script_path), "--", *script_arguments]
