import argparse
import unittest
from pathlib import Path

from tests.support import APP
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox

from app.arguments import ParameterValidationError, build_process_arguments, build_script_arguments
from app.models import ParameterValue, ScriptRuntimeState
from app.parameter_widgets import ParameterForm
from app.script_inspector import ScriptInspector
from app.string_widgets import FilePicker, FolderPicker

EXAMPLES = Path(__file__).resolve().parents[1] / "scripts" / "test_scripts"


class ParameterTests(unittest.TestCase):
    def form(self, name: str) -> ParameterForm:
        script = ScriptInspector().inspect(EXAMPLES / name)
        self.assertIsNone(script.inspection_error)
        form = ParameterForm(script.parameters, {})
        self.addCleanup(form.deleteLater)
        return form

    def test_widget_mapping_and_defaults(self) -> None:
        form = self.form("basic_types.py")
        for name, expected in {"name": QLineEdit, "count": QSpinBox, "scale": QDoubleSpinBox, "verbose": QCheckBox, "cache": QCheckBox}.items():
            self.assertIsInstance(form.editors[name].control, expected)
        self.assertEqual(form.values()["name"].value, "World")
        self.assertEqual(form.values()["count"].value, 3)
        choices = self.form("choices.py")
        self.assertIsInstance(choices.editors["format"].control, QComboBox)
        self.assertEqual(choices.arguments(), ["--format", "PNG"])

    def test_boolean_semantics_against_real_argparse(self) -> None:
        form = self.form("basic_types.py")
        parser = argparse.ArgumentParser()
        parser.add_argument("--name")
        parser.add_argument("--count", type=int)
        parser.add_argument("--scale", type=float)
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--no-cache", dest="cache", action="store_false")
        for verbose, cache in [(False, True), (True, False)]:
            form.editors["verbose"].control.setChecked(verbose)
            form.editors["cache"].control.setChecked(cache)
            parsed = parser.parse_args(form.arguments())
            self.assertEqual(parsed.verbose, verbose)
            self.assertEqual(parsed.cache, cache)

    def test_required_fields_and_explicit_numeric_zero(self) -> None:
        form = self.form("required_values.py")
        with self.assertRaisesRegex(ParameterValidationError, "Label"):
            form.arguments()
        form.editors["label"].control.setText("a label")
        with self.assertRaisesRegex(ParameterValidationError, "Frame End"):
            form.arguments()
        form.editors["frame_end"].include.setChecked(True)
        self.assertEqual(form.arguments(), ["--label", "a label", "--frame-end", "0"])

    def test_optional_values_and_shell_characters(self) -> None:
        form = self.form("basic_types.py")
        special = 'a path with spaces & | ; "quoted"'
        form.editors["name"].control.setText(special)
        self.assertEqual(form.arguments()[1], special)
        form.editors["count"].include.setChecked(False)
        self.assertNotIn("--count", form.arguments())
        form.editors["name"].control.clear()
        self.assertNotIn("--name", form.arguments())
        form.editors["name"].control.setText("--looks-like-an-option")
        self.assertIn("--name=--looks-like-an-option", form.arguments())

    def test_numeric_choices_take_precedence(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--quality", type=int, choices=[1, 2, 3], default=2)
        model = ScriptInspector._parameters(parser)
        form = ParameterForm(model, {})
        self.addCleanup(form.deleteLater)
        self.assertIsInstance(form.editors["quality"].control, QComboBox)
        self.assertEqual(parser.parse_args(form.arguments()).quality, 2)

    def test_path_picker_uses_folder_name_suffix(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--source-file", type=Path)
        parser.add_argument("--output-directory", type=Path)
        parser.add_argument("--cache-dir", type=Path)
        parser.add_argument("--assets-folder", type=Path)
        form = ParameterForm(ScriptInspector._parameters(parser), {})
        self.addCleanup(form.deleteLater)
        self.assertIsInstance(form.editors["source_file"].control, FilePicker)
        for name in ("output_directory", "cache_dir", "assets_folder"):
            with self.subTest(name=name):
                self.assertIsInstance(form.editors[name].control, FolderPicker)

    def test_multi_value_path_folder_can_be_read_for_preview(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--input-directory", type=Path, nargs="+")
        form = ParameterForm(ScriptInspector._parameters(parser), {})
        self.addCleanup(form.deleteLater)
        editor = form.editors["input_directory"]
        self.assertIsInstance(editor.multiple_inputs.controls[0], FolderPicker)
        # An empty row is valid while editing and must not break the live command preview.
        self.assertEqual(form.values()["input_directory"].value, [""])

    def test_positional_arguments_and_optional_nargs(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("file")
        parser.add_argument("--label", nargs="?")
        model = ScriptInspector._parameters(parser)
        argv = build_script_arguments(model, {"file": ParameterValue("--file"), "label": ParameterValue("title")})
        result = parser.parse_args(argv)
        self.assertEqual(result.file, "--file")
        self.assertEqual(result.label, "title")

    def test_process_argument_order(self) -> None:
        path = Path("C:/scripts with spaces/render.py")
        state = ScriptRuntimeState(runtime="Blender", blender_background=True, disable_override_resync=True)
        self.assertEqual(build_process_arguments(path, ["--name", "two words"], state), [
            "--background", "--disable-liboverride-auto-resync", "--python", str(path), "--", "--name", "two words"
        ])
        state.runtime = "Python"
        self.assertEqual(build_process_arguments(path, ["--count", "2"], state), [str(path), "--count", "2"])

    def test_out_of_range_defaults_are_reported_instead_of_silently_clamped(self) -> None:
        for parameter_type, default in [(int, 2**40), (float, 1e30), (float, 1e-10)]:
            with self.subTest(default=default):
                parser = argparse.ArgumentParser()
                parser.add_argument("--number", type=parameter_type, default=default)
                with self.assertRaises(ValueError):
                    ParameterForm(ScriptInspector._parameters(parser), {})
