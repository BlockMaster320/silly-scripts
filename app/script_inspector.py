"""The only module aware of argparse internals and dynamic script imports.

This synchronous adapter can later be replaced by a helper-process inspector
returning the same ScriptInfo. Import only trusted scripts: module-level code
and create_parser() run here, although a guarded main() does not.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import types
import uuid
from pathlib import Path

from .models import SHOT_SELECTION_OPTIONS, ScriptInfo, ScriptParameter


class InspectionError(Exception):
    pass


class _UnavailableBpyValue:
    """A lazy placeholder for bpy attributes referenced while defining code."""

    def __getattr__(self, name: str) -> "_UnavailableBpyValue":
        return self

    def __call__(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError(_BpyInspectionStub.UNAVAILABLE_MESSAGE)

    def __iter__(self):
        raise RuntimeError(_BpyInspectionStub.UNAVAILABLE_MESSAGE)


class _BpyInspectionStub(types.ModuleType):
    """Let scripts import bpy at module scope while inspecting argparse only.

    The stub intentionally implements no Blender API. Lazy values allow
    annotations and module constants to refer to bpy; operations requiring
    Blender still fail with a useful explanation during parser inspection.
    """

    UNAVAILABLE_MESSAGE = (
        "Blender's bpy API is unavailable during launcher inspection. "
        "Keep Blender API calls inside functions invoked by main()."
    )

    def __getattr__(self, name: str) -> _UnavailableBpyValue:
        if name.startswith("__"):
            raise AttributeError(name)
        return _UnavailableBpyValue()


class ScriptInspector:
    def inspect(self, path: Path) -> ScriptInfo:
        info = ScriptInfo(path=path, name=path.stem)
        module_name = f"_launcher_inspect_{uuid.uuid4().hex}"
        original_path = sys.path[:]
        original_bpy = sys.modules.get("bpy")
        injected_bpy = original_bpy is None
        try:
            # Most launcher installations use regular Python, where bpy is
            # absent. A temporary import-only stub supports the common and
            # Blender-friendly `import bpy` at the top of user scripts.
            if injected_bpy:
                sys.modules["bpy"] = _BpyInspectionStub("bpy")
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise InspectionError("Unable to load this Python file.")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            sys.path.insert(0, str(path.parent))
            # Read fresh source on Refresh, including same-size edits made within
            # a filesystem timestamp tick. The module name is never __main__.
            code = compile(path.read_bytes(), str(path), "exec")
            exec(code, module.__dict__)
            factory = getattr(module, "create_parser", None)
            if not callable(factory):
                raise InspectionError("This script must expose a create_parser() function.")
            parser = factory()
            if not isinstance(parser, argparse.ArgumentParser):
                raise InspectionError("create_parser() must return argparse.ArgumentParser.")
            info.parameters = self._parameters(parser)
        except (Exception, SystemExit, KeyboardInterrupt) as exc:
            info.inspection_error = f"{type(exc).__name__}: {exc}"
        finally:
            sys.path[:] = original_path
            sys.modules.pop(module_name, None)
            if injected_bpy:
                sys.modules.pop("bpy", None)
            elif original_bpy is not None:
                sys.modules["bpy"] = original_bpy
        return info

    @staticmethod
    def _parameters(parser: argparse.ArgumentParser) -> list[ScriptParameter]:
        if parser._mutually_exclusive_groups:
            raise InspectionError("Mutually exclusive argument groups are not supported yet.")
        parameters: list[ScriptParameter] = []
        names: set[str] = set()
        for action in parser._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            label = "/".join(action.option_strings) or action.dest
            action_types = {
                argparse._StoreAction: "store",
                argparse._StoreTrueAction: "store_true",
                argparse._StoreFalseAction: "store_false",
                argparse.BooleanOptionalAction: "boolean_optional",
                argparse._AppendAction: "append",
            }
            behavior = action_types.get(type(action))
            shot_selection = any(option in SHOT_SELECTION_OPTIONS for option in action.option_strings)
            if behavior is None:
                raise InspectionError(
                    f"{label}: action {type(action).__name__} is not supported yet. "
                    "Use single-value arguments, store_true, or store_false."
                )
            if behavior == "store" and action.nargs not in (None, "?", "+") and action.type not in (None, str):
                raise InspectionError(f"{label}: multi-value nargs={action.nargs!r} is not supported yet.")
            if behavior == "append" and (action.type not in (None, str) or action.nargs is not None):
                raise InspectionError(f"{label}: append is supported for single string values only.")
            if shot_selection and behavior in ("store", "append"):
                if action.type not in (None, str) or action.choices is not None or action.nargs not in (None, "?"):
                    raise InspectionError(f"{label}: shot selections must be single string values without choices.")
                if behavior == "append" and action.nargs is not None:
                    raise InspectionError(f"{label}: repeated shot flags must each take one value.")
            if behavior == "boolean_optional" and not any(
                option.startswith("--") and f"--no-{option[2:]}" in action.option_strings
                for option in action.option_strings
            ):
                raise InspectionError(f"{label}: two-sided booleans need a long option such as --recursive.")
            if action.type not in (None, str, int, float, Path):
                raise InspectionError(f"{label}: custom types are not supported; use str, int, float, or pathlib.Path.")
            if action.dest in names:
                raise InspectionError(f"{label}: multiple actions with destination {action.dest!r} are unsupported.")
            if action.option_strings and not all(option.startswith("-") for option in action.option_strings):
                raise InspectionError(f"{label}: only '-' option prefixes are supported.")
            names.add(action.dest)
            positional_required = not action.option_strings and action.nargs not in ("?", "*")
            parameters.append(
                ScriptParameter(
                    name=action.dest,
                    option_strings=list(action.option_strings),
                    parameter_type=action.type or str,
                    default=None if action.default == argparse.SUPPRESS else action.default,
                    required=bool(action.required) if action.option_strings else positional_required,
                    choices=list(action.choices) if action.choices is not None else None,
                    help=None if action.help == argparse.SUPPRESS else action.help,
                    action_type=behavior,
                    nargs=action.nargs,
                    const=action.const,
                )
            )
        return parameters
