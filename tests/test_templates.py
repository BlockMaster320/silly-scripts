import argparse
import contextlib
import io
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.support import APP
from PySide6.QtWidgets import QCheckBox, QLineEdit

from app.arguments import ParameterValidationError, build_script_arguments
from app.models import ParameterValue
from app.parameter_widgets import ParameterForm
from app.script_inspector import ScriptInspector
from app.script_templates import create_script
from app.shot_selection import parse_shot_selection


class TemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="batch template ")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.script = create_script(self.root, "batch.py", "batch")
        # Generated scripts run independently of the launcher's app package.
        with patch.dict(sys.modules, {"app": None}):
            self.module = runpy.run_path(str(self.script), run_name="template_test")

    def file(self, relative: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path.resolve()

    def args(self, *extra: str) -> argparse.Namespace:
        return self.module["create_parser"]().parse_args([
            "--target-directory", str(self.root), "--ignore-hidden-folders", "--recursive", *extra,
        ])

    def discovered(self, *extra: str) -> set[Path]:
        return set(self.module["discover_blend_files"](self.args(*extra)))

    def test_generated_scripts_inspect_without_blender_and_blank_prints(self) -> None:
        blank = create_script(self.root, "blank", "blank")
        for path in (blank, self.script):
            self.assertIsNone(ScriptInspector().inspect(path).inspection_error)
        output = io.StringIO()
        with patch.object(sys, "argv", ["blender", "--python", str(blank), "--", "--message", "Template works"]), contextlib.redirect_stdout(output):
            runpy.run_path(str(blank), run_name="__main__")
        self.assertEqual(output.getvalue().strip(), "Template works")

    def test_shot_number_suffix_and_include_then_exclude(self) -> None:
        wanted = self.file("nested/shot_0004.blend")
        self.file("shot_001.blend")
        self.file("nested/shot_0005.BLEND")
        self.file("shot_004_edit.blend")
        self.file("shot_004.blend1")
        self.file("no_number.blend")
        self.assertEqual(self.discovered("--include-shots", "1,4-5", "--exclude-shots", "1,5"), {wanted})
        self.assertIn(self.root / "no_number.blend", self.discovered("--exclude-shots", "1-100"))
        self.assertEqual(self.discovered("--include_shots", "4", "--include_shots", "5", "--exclude_shots", "5"), {wanted})

    def test_excluded_folders_are_pruned_before_shot_filters(self) -> None:
        wanted = self.file("keep/shot_007.blend")
        self.file("cache/shot_007.blend")
        self.file("nested/cache/deeper/shot_007.blend")
        self.file("nested/omit/shot_007.blend")
        self.assertEqual(self.discovered("--exclude-folders", "cache,nested/omit", "--include-shots", "7"), {wanted})
        self.assertEqual(self.discovered("--exclude-folders", str(self.root)), set())

    def test_hidden_files_and_folders_and_nonrecursive_mode(self) -> None:
        visible = self.file("shot_001.blend")
        nested = self.file("nested/shot_002.blend")
        hidden_folder = self.file(".hidden/shot_003.blend")
        hidden_file = self.file(".shot_004.blend")
        self.assertEqual(self.discovered(), {visible, nested})
        self.assertEqual(self.discovered("--no-ignore-hidden-folders"), {visible, nested, hidden_folder, hidden_file})
        self.assertEqual(self.discovered("--no-recursive"), {visible})
        fake_path = Mock()
        fake_path.name = "visible.blend"
        fake_path.stat.return_value = SimpleNamespace(st_file_attributes=2)
        with patch.dict(self.module["is_hidden"].__globals__, {"stat": SimpleNamespace(FILE_ATTRIBUTE_HIDDEN=2)}):
            self.assertTrue(self.module["is_hidden"](fake_path))

    def test_invalid_ranges_and_missing_directory_fail_before_processing(self) -> None:
        for text in ("", "4-1", "1,,2", "one", "-1", "1-2-3", "1.5"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_shot_selection(text)
        with self.assertRaises(ValueError):
            self.discovered("--include-shots", "9-2")
        with self.assertRaises(ValueError):
            self.module["discover_blend_files"](self.args("--target-directory", str(self.root / "missing")))
        self.assertEqual(parse_shot_selection(" 001 , 4 - 8,12 "), [(1, 1), (4, 8), (12, 12)])

    def test_template_only_opens_and_saves_same_path(self) -> None:
        path = self.file("shot_001.blend")
        operators = Mock()
        operators.open_mainfile.return_value = {"FINISHED"}
        operators.save_as_mainfile.return_value = {"FINISHED"}
        fake_bpy = SimpleNamespace(ops=SimpleNamespace(wm=operators))
        with patch.dict(sys.modules, {"bpy": fake_bpy}), contextlib.redirect_stdout(io.StringIO()):
            self.module["process_file"](path)
        self.assertEqual([call[0] for call in operators.mock_calls], ["open_mainfile", "save_as_mainfile"])
        operators.open_mainfile.assert_called_once_with(filepath=str(path), load_ui=True)
        operators.save_as_mainfile.assert_called_once_with(filepath=str(path), check_existing=False)
        operators.reset_mock()
        operators.open_mainfile.return_value = {"CANCELLED"}
        with patch.dict(sys.modules, {"bpy": fake_bpy}), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
            self.module["process_file"](path)
        operators.save_as_mainfile.assert_not_called()

    def test_main_continues_after_one_file_failure_and_returns_error(self) -> None:
        paths = [self.file("shot_001.blend"), self.file("shot_002.blend")]
        process = Mock(side_effect=[RuntimeError("test failure"), None])
        argv = [str(self.script), "--target-directory", str(self.root), "--recursive", "--ignore-hidden-folders"]
        with patch.object(sys, "argv", argv), patch.dict(self.module["main"].__globals__, {"process_file": process}), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            self.module["main"]()
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual([call.args[0] for call in process.call_args_list], paths)

    def test_creation_never_overwrites_or_escapes_folder(self) -> None:
        original = self.script.read_bytes()
        with self.assertRaises(FileExistsError):
            create_script(self.root, "batch.py", "blank")
        self.assertEqual(self.script.read_bytes(), original)
        for name in ("../escape.py", "nested/script.py", "bad\\script.py", "__init__.py", "bad.txt", "CON.py", "bad?.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                create_script(self.root, name, "blank")

    def test_ui_ranges_build_repeated_flags_and_required_booleans(self) -> None:
        info = ScriptInspector().inspect(self.script)
        form = ParameterForm(info.parameters, {})
        self.addCleanup(form.deleteLater)
        self.assertIsInstance(form.editors["include_shots"].control, QLineEdit)
        self.assertIsInstance(form.editors["recursive"].control, QCheckBox)
        self.assertTrue(form.editors["recursive"].control.isChecked())
        form.editors["target_directory"].control.set_path(str(self.root))
        for name, text in (("include_shots", "1,4-8,12"), ("exclude_shots", "5-6")):
            form.editors[name].include.setChecked(True)
            form.editors[name].control.setText(text)
        argv = form.arguments()
        self.assertEqual(argv.count("--include-shots"), 3)
        parsed = self.module["create_parser"]().parse_args(argv)
        self.assertEqual(parsed.include_shots, ["1", "4-8", "12"])
        self.assertEqual(parsed.exclude_shots, ["5-6"])
        self.assertTrue(parsed.recursive)
        self.assertTrue(parsed.ignore_hidden_folders)
        form.editors["recursive"].control.setChecked(False)
        form.editors["ignore_hidden_folders"].control.setChecked(False)
        parsed = self.module["create_parser"]().parse_args(form.arguments())
        self.assertFalse(parsed.recursive)
        self.assertFalse(parsed.ignore_hidden_folders)
        form.editors["include_shots"].control.setText("9-1")
        with self.assertRaisesRegex(ParameterValidationError, "Include Shots"):
            form.arguments()

    def test_existing_scalar_shot_arguments_and_underscore_options(self) -> None:
        for option in ("--include-shots", "--include_shots", "--exclude-shots", "--exclude_shots"):
            parser = argparse.ArgumentParser()
            parser.add_argument(option)
            parameters = ScriptInspector._parameters(parser)
            argv = build_script_arguments(parameters, {parameters[0].name: ParameterValue("001,4-8")})
            self.assertEqual(argv, [option, "1,4-8"])
            self.assertEqual(getattr(parser.parse_args(argv), parameters[0].name), "1,4-8")

    def test_multiple_targets_overlap_and_folder_paths_with_commas(self) -> None:
        wanted = self.file("nested/shot_001.blend")
        self.file("skip, this/shot_002.blend")
        self.file("other_skip/shot_003.blend")
        args = self.args(
            "--target-directory", str(self.root), str(self.root / "nested"),
            "--exclude-folders", str(self.root / "skip, this"),
            "--exclude-folders", str(self.root / "other_skip"),
        )
        self.assertEqual(self.module["discover_blend_files"](args), [wanted])

    def test_new_blank_template_prints_each_added_message(self) -> None:
        blank = create_script(self.root, "multi_message.py", "blank")
        output = io.StringIO()
        with patch.object(sys, "argv", [str(blank), "--message", "first message", "second message"]), contextlib.redirect_stdout(output):
            runpy.run_path(str(blank), run_name="__main__")
        self.assertEqual(output.getvalue().splitlines(), ["first message", "second message"])
