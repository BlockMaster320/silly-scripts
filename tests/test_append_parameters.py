import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import APP
from app.arguments import ParameterValidationError, build_script_arguments
from app.models import ParameterValue
from app.parameter_config import ParameterConfigStore
from app.parameter_widgets import ParameterForm
from app.script_inspector import InspectionError, ScriptInspector
from app.string_widgets import FilePicker, FolderPicker


class AppendParameterTests(unittest.TestCase):
    def form(self, parser, saved=None):
        parameters = ScriptInspector._parameters(parser)
        form = ParameterForm(parameters, saved or {})
        self.addCleanup(form.deleteLater)
        return form

    def test_supported_types_round_trip_with_defaults_and_saved_rows(self):
        for kind, entries, default in (
            (str, ["one", "-two"], ["base"]),
            (int, [0, -2], [7]),
            (float, [0.0, -2.5], [7.5]),
            (Path, [Path("file one.blend"), Path("-two.blend")], [Path("base.blend")]),
        ):
            with self.subTest(kind=kind):
                if kind is Path:
                    entries = [entries[0].resolve(), entries[1]]
                parser = argparse.ArgumentParser()
                parser.add_argument("--value", type=kind, action="append", default=default)
                form = self.form(parser)
                self.assertEqual(form.arguments(), [])
                editor = form.editors["value"]
                inputs = editor.string_inputs or editor.multiple_inputs
                first = inputs.first_control
                if isinstance(first, FilePicker):
                    with patch("app.string_widgets.QFileDialog.getOpenFileName", return_value=(str(entries[0]), "")):
                        first.browse_button.click()
                else:
                    first.setText(str(entries[0]))
                inputs.add_value(entries[1])
                inputs.add_value("")
                self.assertEqual(parser.parse_args(form.arguments()).value, default + entries)
                restored = self.form(parser, form.values())
                self.assertEqual(restored.arguments(), form.arguments())
                with tempfile.TemporaryDirectory() as tmp:
                    store = ParameterConfigStore(Path(tmp) / "config.json")
                    script = Path(tmp) / "script.py"
                    store.save(script, form.parameters, form.values(), [], {})
                    saved, _ = store.load(script, form.parameters, [])
                    self.assertEqual(self.form(parser, saved).arguments(), form.arguments())

    def test_typed_choices_repeat_and_validate_each_value(self):
        for kind, choices in ((int, [1, 2]), (float, [1.5, 2.5]), (Path, [Path("a"), Path("b")])):
            with self.subTest(kind=kind):
                parser = argparse.ArgumentParser()
                parser.add_argument("--value", type=kind, action="append", choices=choices)
                form = self.form(parser)
                inputs = form.editors["value"].multiple_inputs
                inputs.first_control.setCurrentIndex(0)
                inputs.add_value(choices[1])
                self.assertEqual(parser.parse_args(form.arguments()).value, choices)
                with self.assertRaises(ParameterValidationError):
                    build_script_arguments(form.parameters, {"value": ParameterValue(["99"])})

    def test_required_and_invalid_numbers(self):
        for kind, bad in ((int, "abc"), (float, "nan"), (float, "inf")):
            with self.subTest(kind=kind, bad=bad):
                parser = argparse.ArgumentParser()
                parser.add_argument("--value", type=kind, action="append", required=True)
                form = self.form(parser)
                self.assertIsNone(form.editors["value"].include)
                with self.assertRaises(ParameterValidationError):
                    form.arguments()
                form.editors["value"].control.setText(bad)
                with self.assertRaises(ParameterValidationError):
                    form.arguments()

    def test_path_folders_use_repeatable_folder_pickers(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--target-directory", type=Path, action="append")
        form = self.form(parser)
        inputs = form.editors["target_directory"].multiple_inputs
        self.assertIsInstance(inputs.first_control, FolderPicker)
        inputs.first_control.set_path("folder one")
        inputs.add_value("folder two")
        self.assertEqual(parser.parse_args(form.arguments()).target_directory,
                         [Path("folder one"), Path("folder two")])

    def test_grouped_append_still_reports_clear_error(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--value", type=int, action="append", nargs=2)
        with self.assertRaisesRegex(InspectionError, "omit nargs"):
            ScriptInspector._parameters(parser)
