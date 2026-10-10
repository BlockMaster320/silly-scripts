"""Central last-run parameter storage, independent of Qt/global preferences."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from .models import ParameterValue, ScriptParameter


class ParameterConfigError(ValueError):
    """A config could not be decoded safely; the parser defaults remain usable."""


class ParameterConfigStore:
    """Save all scripts' last-run snapshots atomically in one user config file.

    Parameter signatures prevent old values from being applied after a script
    changes an argument's type, action, choices, or number of values.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else self.default_path()

    @staticmethod
    def default_path() -> Path:
        if os.name == "nt":
            root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        elif sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support"
        else:
            root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return root / "SillyScripts" / "script_parameters.json"

    @staticmethod
    def script_key(script_path: Path) -> str:
        return os.path.normcase(str(script_path.resolve()))

    def _read_document(self) -> dict[str, Any]:
        path = self.path
        try:
            with path.open(encoding="utf-8") as handle:
                document = json.load(handle)
        except FileNotFoundError:
            return {"version": 1, "scripts": {}}
        except (ValueError, UnicodeError) as exc:
            raise ParameterConfigError(f"Invalid parameter config {path}: {exc}") from exc
        if not isinstance(document, dict) or document.get("version") != 1:
            raise ParameterConfigError(f"Unsupported parameter config format: {path}")
        if not isinstance(document.get("scripts"), dict):
            raise ParameterConfigError(f"Parameter config must contain a scripts object: {self.path}")
        return document

    def load(
        self,
        script_path: Path,
        parameters: list[ScriptParameter],
        batch_parameters: list[ScriptParameter],
    ) -> tuple[dict[str, ParameterValue], dict[str, ParameterValue]]:
        document = self._read_document()
        key = self.script_key(script_path)
        snapshot = document["scripts"].get(key)
        if key not in document["scripts"]:
            return {}, {}
        if not isinstance(snapshot, dict):
            raise ParameterConfigError(f"Invalid saved entry for {script_path} in {self.path}")
        return (
            self._restore(snapshot.get("parameters", {}), parameters),
            self._restore(snapshot.get("batch_parameters", {}), batch_parameters),
        )

    def save(
        self,
        script_path: Path,
        parameters: list[ScriptParameter],
        values: dict[str, ParameterValue],
        batch_parameters: list[ScriptParameter],
        batch_values: dict[str, ParameterValue],
    ) -> Path:
        # Read before every save to preserve other scripts' latest snapshots.
        # A corrupt file is reported rather than overwriting unrelated settings.
        document = self._read_document()
        document["scripts"][self.script_key(script_path)] = {
            "parameters": self._snapshot(parameters, values),
            "batch_parameters": self._snapshot(batch_parameters, batch_values),
        }
        self._write_document(document)
        return self.path

    def _write_document(self, document: dict[str, Any]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                prefix=f".{path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(document, handle, indent=2, ensure_ascii=False, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _signature(parameter: ScriptParameter) -> dict[str, Any]:
        kind = parameter.parameter_type
        type_name = f"{getattr(kind, '__module__', '')}.{getattr(kind, '__qualname__', str(kind))}"
        return {
            "type": type_name,
            "action": parameter.action_type,
            "nargs": parameter.nargs,
            "choices": None if parameter.choices is None else [str(item) for item in parameter.choices],
        }

    @classmethod
    def _json_value(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, (list, tuple)):
            return [cls._json_value(item) for item in value]
        # File pickers display paths as strings. Custom argparse choices also
        # have a CLI string representation; restore those from current choices.
        return str(value)

    @classmethod
    def _snapshot(
        cls, parameters: list[ScriptParameter], values: dict[str, ParameterValue],
    ) -> dict[str, Any]:
        return {
            parameter.name: {
                "signature": cls._signature(parameter),
                "value": cls._json_value(values[parameter.name].value),
                "enabled": values[parameter.name].enabled,
            }
            for parameter in parameters if parameter.name in values
        }

    @classmethod
    def _restore(
        cls, entries: Any, parameters: list[ScriptParameter],
    ) -> dict[str, ParameterValue]:
        if not isinstance(entries, dict):
            raise ParameterConfigError("Parameter config entries must be a JSON object.")
        restored: dict[str, ParameterValue] = {}
        for parameter in parameters:
            entry = entries.get(parameter.name)
            if not isinstance(entry, dict) or entry.get("signature") != cls._signature(parameter):
                continue
            enabled, value = entry.get("enabled"), entry.get("value")
            if not isinstance(enabled, bool) or not cls._valid_value(value):
                continue
            items = value if isinstance(value, list) else [value]
            if isinstance(value, list) and not (parameter.is_string or parameter.nargs == "+" or parameter.action_type == "append"):
                continue
            if parameter.action_type in ("store_true", "store_false", "boolean_optional"):
                if value is not None and not isinstance(value, bool):
                    continue
            elif parameter.choices is not None:
                choices = {str(choice): choice for choice in parameter.choices}
                if any(item is not None and str(item) not in choices for item in items):
                    continue
                selected = [None if item is None else choices[str(item)] for item in items]
                value = selected if isinstance(value, list) else selected[0]
            elif parameter.parameter_type in (int, float) and parameter.nargs != "+" and parameter.action_type != "append":
                if value is not None and value != "":
                    try:
                        number = parameter.parameter_type(value)
                    except (ValueError, TypeError, OverflowError):
                        continue
                    if isinstance(value, bool):
                        continue
                    if parameter.parameter_type is int and isinstance(value, float) and value != number:
                        continue
                    if parameter.parameter_type is float and not math.isfinite(number):
                        continue
                    uses_spinbox = parameter.required or parameter.default is not None
                    if uses_spinbox:
                        if parameter.parameter_type is int and not -2_147_483_648 <= number <= 2_147_483_647:
                            continue
                        if parameter.parameter_type is float and (
                            abs(number) > 1e12 or not math.isclose(round(number, 8), number, rel_tol=1e-12, abs_tol=0.0)
                        ):
                            continue
                elif value == "" and (parameter.required or parameter.default is not None):
                    continue
            restored[parameter.name] = ParameterValue(value, enabled)
        return restored

    @classmethod
    def _valid_value(cls, value: Any) -> bool:
        if isinstance(value, list):
            return all(not isinstance(item, list) and cls._valid_value(item) for item in value)
        if isinstance(value, float):
            return math.isfinite(value)
        return value is None or isinstance(value, (str, bool, int))
