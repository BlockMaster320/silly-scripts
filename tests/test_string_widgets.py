import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import APP
from PySide6.QtWidgets import QPushButton

from app.arguments import ParameterValidationError
from app.parameter_widgets import ParameterForm
from app.script_inspector import ScriptInspector
from app.string_widgets import FolderPicker


class StringWidgetTests(unittest.TestCase):
    def form(self, parser: argparse.ArgumentParser, saved=None) -> ParameterForm:
        form = ParameterForm(ScriptInspector._parameters(parser), saved or {})
        self.addCleanup(form.deleteLater)
        return form

    def test_folder_picker_uses_native_dialog_and_cancel_retains_selection(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--target-directory", required=True)
        form = self.form(parser)
        picker = form.editors["target_directory"].control
        self.assertIsInstance(picker, FolderPicker)
        with self.assertRaisesRegex(ParameterValidationError, "Target Directory"):
            form.arguments()
        with tempfile.TemporaryDirectory(prefix="selected folder ") as temporary:
            expected = str(Path(temporary).resolve())
            with patch("app.string_widgets.QFileDialog.getExistingDirectory", return_value=temporary) as dialog:
                picker.browse_button.click()
                dialog.assert_called_once()
            self.assertEqual(picker.path(), expected)
            self.assertEqual(form.arguments(), ["--target-directory", expected])
            with patch("app.string_widgets.QFileDialog.getExistingDirectory", return_value=""):
                picker.browse_button.click()
            self.assertEqual(picker.path(), expected)

    def test_append_strings_round_trip_keep_spaces_and_restore_added_rows(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--tag", action="append")
        form = self.form(parser)
        editor = form.editors["tag"]
        editor.include.setChecked(True)
        editor.control.setText("first value & spaces")
        editor.string_inputs.add_button.click()
        editor.string_inputs.controls[1].setText("--second")
        self.assertEqual(parser.parse_args(form.arguments()).tag, ["first value & spaces", "--second"])
        restored = self.form(parser, form.values())
        self.assertEqual(len(restored.editors["tag"].string_inputs.controls), 2)
        self.assertEqual(restored.arguments(), form.arguments())
        row = editor.string_inputs.controls[1].parentWidget()
        row.findChild(QPushButton).click()
        self.assertEqual(len(editor.string_inputs.controls), 1)
        self.assertEqual(parser.parse_args(form.arguments()).tag, ["first value & spaces"])

    def test_append_script_defaults_are_not_duplicated_in_ui_arguments(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--tag", action="append", default=["base"])
        form = self.form(parser)
        editor = form.editors["tag"]
        self.assertEqual(parser.parse_args(form.arguments()).tag, ["base"])
        editor.control.setText("extra")
        self.assertEqual(parser.parse_args(form.arguments()).tag, ["base", "extra"])

    def test_scalar_strings_repeat_flags_and_explain_last_value_behavior(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--name", default="first")
        form = self.form(parser)
        editor = form.editors["name"]
        editor.string_inputs.add_button.click()
        editor.string_inputs.controls[1].setText("second")
        self.assertEqual(form.arguments(), ["--name", "first", "--name", "second"])
        self.assertEqual(parser.parse_args(form.arguments()).name, "second")
        self.assertIn("last filled value", editor.string_inputs.hint.text())

    def test_string_choices_have_add_button_numeric_and_bool_do_not(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--format", choices=["PNG", "EXR"], action="append")
        parser.add_argument("--count", type=int, default=2)
        parser.add_argument("--verbose", action="store_true")
        form = self.form(parser)
        editor = form.editors["format"]
        editor.include.setChecked(True)
        editor.control.setCurrentText("PNG")
        editor.string_inputs.add_button.click()
        editor.string_inputs.controls[1].setCurrentText("EXR")
        self.assertEqual(parser.parse_args(form.arguments()).format, ["PNG", "EXR"])
        self.assertIsNone(form.editors["count"].string_inputs)
        self.assertIsNone(form.editors["verbose"].string_inputs)

    def test_multivalue_strings_and_fixed_count_validation(self) -> None:
        for nargs in ("+", "*", 2):
            with self.subTest(nargs=nargs):
                parser = argparse.ArgumentParser()
                parser.add_argument("--names", nargs=nargs, required=True)
                form = self.form(parser)
                editor = form.editors["names"]
                editor.control.setText("first name")
                if nargs == 2:
                    with self.assertRaisesRegex(ParameterValidationError, "exactly 2"):
                        form.arguments()
                editor.string_inputs.add_button.click()
                editor.string_inputs.controls[1].setText("second name")
                self.assertEqual(parser.parse_args(form.arguments()).names, ["first name", "second name"])

    def test_folder_rows_can_be_selected_independently(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--exclude-folders", action="append")
        form = self.form(parser)
        editor = form.editors["exclude_folders"]
        editor.include.setChecked(True)
        editor.control.set_path("C:/folder one")
        editor.string_inputs.add_button.click()
        editor.string_inputs.controls[1].set_path("C:/folder two")
        self.assertEqual(parser.parse_args(form.arguments()).exclude_folders, ["C:/folder one", "C:/folder two"])

    def test_legacy_scalar_excluded_folders_and_multiple_shot_rows(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("--exclude-folders")
        parser.add_argument("--include-shots", action="append")
        form = self.form(parser)
        folders = form.editors["exclude_folders"]
        folders.include.setChecked(True)
        folders.control.set_path("C:/first")
        folders.string_inputs.add_value("C:/second")
        shots = form.editors["include_shots"]
        shots.include.setChecked(True)
        shots.control.setText("1,4-8")
        shots.string_inputs.add_value("12")
        shots.string_inputs.add_value("")
        parsed = parser.parse_args(form.arguments())
        self.assertEqual(parsed.exclude_folders, "C:/first,C:/second")
        self.assertEqual(parsed.include_shots, ["1", "4-8", "12"])

    def test_scalar_positional_extra_values_fail_before_execution(self) -> None:
        parser = argparse.ArgumentParser()
        parser.add_argument("name")
        form = self.form(parser)
        editor = form.editors["name"]
        editor.control.setText("first")
        editor.string_inputs.add_value("second")
        with self.assertRaisesRegex(ParameterValidationError, "one positional value"):
            form.arguments()
