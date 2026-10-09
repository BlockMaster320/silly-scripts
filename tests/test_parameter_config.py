"""Last-run snapshots survive restarts without applying incompatible values."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app.models import ParameterValue, ScriptParameter
from app.parameter_config import ParameterConfigError, ParameterConfigStore


def parameter(name: str, kind: object = str, **kwargs: object) -> ScriptParameter:
    fields = dict(
        name=name, option_strings=["--" + name.replace("_", "-")],
        parameter_type=kind, default=None, required=False, choices=None,
        help=None, action_type="store",
    )
    fields.update(kwargs)
    return ScriptParameter(**fields)


class ParameterConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.script = Path(self.temp.name) / "example.py"
        self.store = ParameterConfigStore(Path(self.temp.name) / "appdata" / "script_parameters.json")

    def test_round_trip_preserves_types_repeats_paths_and_batch_values(self) -> None:
        parameters = [
            parameter("name"), parameter("count", int), parameter("scale", float),
            parameter("verbose", action_type="store_true"),
            parameter("cache", action_type="store_false"),
            parameter("file", Path), parameter("items", int, nargs="+"),
            parameter("format", choices=["PNG", "EXR"]),
            parameter("optional_number", int),
        ]
        raw_values = [
            ["First", "Second"], 42, 1.25, True, False,
            Path(self.temp.name) / "file with spaces.blend", ["1", "3"], "EXR", "7",
        ]
        values = {item.name: ParameterValue(value) for item, value in zip(parameters, raw_values)}
        values["count"].enabled = False
        batch_parameters = [parameter("target_directory", Path), parameter("include_shots")]
        batch_values = {"target_directory": ParameterValue(self.temp.name), "include_shots": ParameterValue("1,4-8")}
        path = self.store.save(self.script, parameters, values, batch_parameters, batch_values)
        self.assertEqual(path, self.store.path)
        restored, batch = ParameterConfigStore(path).load(self.script, parameters, batch_parameters)
        values["file"].value = str(raw_values[5])
        self.assertEqual(restored, values)
        self.assertEqual(batch, batch_values)

    def test_missing_config_uses_defaults_and_same_names_in_libraries_are_independent(self) -> None:
        self.assertEqual(self.store.load(self.script, [], []), ({}, {}))
        other = self.script.parent / "other_library" / self.script.name
        other.parent.mkdir()
        parameters = [parameter("name")]
        for script, value in ((self.script, "First"), (other, "Second")):
            self.store.save(script, parameters, {"name": ParameterValue(value)}, [], {})
        self.assertEqual(self.store.load(self.script, parameters, [])[0]["name"].value, "First")
        self.assertEqual(self.store.load(other, parameters, [])[0]["name"].value, "Second")
        document = json.loads(self.store.path.read_text())
        self.assertEqual(len(document["scripts"]), 2)
        self.store.save(self.script, parameters, {"name": ParameterValue("Updated")}, [], {})
        self.assertEqual(self.store.load(other, parameters, [])[0]["name"].value, "Second")

    def test_changed_or_removed_arguments_are_not_restored(self) -> None:
        parameters = [parameter("name"), parameter("removed"), parameter("format", choices=["PNG", "EXR"])]
        self.store.save(self.script, parameters, {p.name: ParameterValue("PNG") for p in parameters}, [], {})
        current = [replace(parameters[0], parameter_type=int), replace(parameters[2], choices=["JPEG"]), parameter("new")]
        self.assertEqual(self.store.load(self.script, current, []), ({}, {}))

    def test_corrupt_config_reports_error_and_malformed_values_are_ignored(self) -> None:
        path = self.store.path
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        with self.assertRaises(ParameterConfigError):
            self.store.load(self.script, [], [])
        parameters = [parameter("count", int)]
        with self.assertRaises(ParameterConfigError):
            self.store.save(self.script, parameters, {"count": ParameterValue(7)}, [], {})
        self.assertEqual(path.read_text(), "not json")
        path.unlink()
        self.store.save(self.script, parameters, {"count": ParameterValue(7)}, [], {})
        document = json.loads(path.read_text())
        document["scripts"][self.store.script_key(self.script)]["parameters"]["count"]["value"] = "not a number"
        path.write_text(json.dumps(document), encoding="utf-8")
        self.assertEqual(self.store.load(self.script, parameters, []), ({}, {}))

    def test_failed_replace_keeps_previous_config_and_removes_temporary_file(self) -> None:
        parameters = [parameter("name")]
        path = self.store.save(self.script, parameters, {"name": ParameterValue("Previous")}, [], {})
        previous = path.read_bytes()
        with patch("app.parameter_config.os.replace", side_effect=PermissionError("read only")):
            with self.assertRaises(PermissionError):
                self.store.save(self.script, parameters, {"name": ParameterValue("New")}, [], {})
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_independent_stores_merge_the_latest_file_on_each_save(self) -> None:
        other_store = ParameterConfigStore(self.store.path)
        other_script = self.script.with_name("other.py")
        parameters = [parameter("name")]
        self.store.save(self.script, parameters, {"name": ParameterValue("First")}, [], {})
        other_store.save(other_script, parameters, {"name": ParameterValue("Second")}, [], {})
        self.store.save(self.script, parameters, {"name": ParameterValue("Updated")}, [], {})
        self.assertEqual(other_store.load(other_script, parameters, [])[0]["name"].value, "Second")
