"""Application models; argparse objects never cross the inspector boundary."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PySide6.QtCore import QProcess


MAX_VISIBLE_LINES = 10_000
SHOT_SELECTION_OPTIONS = frozenset({"--include-shots", "--exclude-shots", "--include_shots", "--exclude_shots"})


@dataclass(frozen=True)
class ExecutableInfo:
    path: Path
    kind: str
    version: str | None = None

    @property
    def label(self) -> str:
        version = f" {self.version}" if self.version else ""
        return f"{self.kind}{version} — {self.path}"


@dataclass(frozen=True)
class ScriptParameter:
    name: str
    option_strings: list[str]
    parameter_type: object | None
    default: Any
    required: bool
    choices: list[Any] | None
    help: str | None
    action_type: str
    nargs: str | int | None = None
    const: Any = None

    @property
    def is_shot_selection(self) -> bool:
        return any(option in SHOT_SELECTION_OPTIONS for option in self.option_strings)

    @property
    def is_string(self) -> bool:
        return self.action_type in ("store", "append") and self.parameter_type in (None, str)

    @property
    def is_path_selection(self) -> bool:
        return self.action_type in ("store", "append") and self.parameter_type is Path

    @property
    def is_folder_selection(self) -> bool:
        """Whether this parameter's name convention requests a folder picker."""
        name = self.name.lower().replace("-", "_")
        return (
            self.choices is None
            and self.parameter_type in (None, str, Path)
            and name.endswith(("directory", "dir", "folder"))
        )

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").replace("-", " ").title()

    @property
    def option(self) -> str | None:
        return next(
            (option for option in self.option_strings if option.startswith("--")),
            self.option_strings[0] if self.option_strings else None,
        )


@dataclass
class ScriptInfo:
    path: Path
    name: str
    parameters: list[ScriptParameter] = field(default_factory=list)
    inspection_error: str | None = None
    category: str = "Scripts"


@dataclass
class ParameterValue:
    value: Any = None
    enabled: bool = True


@dataclass
class ScriptRuntimeState:
    is_running: bool = False
    process: QProcess | None = None
    current_log_path: Path | None = None
    runtime: str = "Blender"
    batch_mode: bool = False
    blender_background: bool = True
    disable_override_resync: bool = True
    output_filter: str = "[SCRIPT]"
    filter_enabled: bool = True
    filter_log_enabled: bool = True
    parameter_values: dict[str, ParameterValue] = field(default_factory=dict)
    batch_parameter_values: dict[str, ParameterValue] = field(default_factory=dict)
    visible_log: deque[str] = field(
        default_factory=lambda: deque(maxlen=MAX_VISIBLE_LINES)
    )
    status: str = "Idle"
