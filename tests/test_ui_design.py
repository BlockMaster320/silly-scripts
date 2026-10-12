"""UI regression checks using real widgets and asynchronous Python processes."""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import APP, wait_until
from PySide6.QtCore import QPoint, QPointF, QSettings, QEvent, Qt
from PySide6.QtGui import QFontDatabase, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QLineEdit, QSpinBox, QStyle, QStyleOptionFrame, QPushButton

from app.arguments import build_process_arguments
from app.main_window import MainWindow
from app.models import ExecutableInfo
from app.parameter_config import ParameterConfigStore
from app.settings import AppSettings
from app.ui.theme import CONTROL_HEIGHT, PALETTE, SMALL, apply_theme

PROJECT = Path(__file__).resolve().parents[1]


class RedesignedUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not QFontDatabase.families():
            for name in ("segoeui.ttf", "consola.ttf"):
                font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
                if font_path.is_file():
                    QFontDatabase.addApplicationFont(str(font_path))
        apply_theme(APP)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ui regression ")
        self.root = Path(self.temp.name)
        self.library = self.root / "scripts"
        self.library.mkdir()
        for name in ("basic_types.py", "choices.py", "output_test.py", "missing_parser.py"):
            shutil.copyfile(PROJECT / "scripts" / "test_scripts" / name, self.library / name)
        self.settings = AppSettings(self.root, QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat))
        self.settings.set_scripts_folders([self.library])
        self.settings.set_executable("Python", sys.executable)
        self.window = MainWindow(self.root, self.settings, auto_discover=False,
                                 parameter_configs=ParameterConfigStore(self.root / "script_parameters.json"))
        self.window.processes.stop_timeout_ms = 100
        self.window.show()
        APP.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        wait_until(lambda: not self.window.isVisible())
        self.window.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def select(self, name: str) -> Path:
        path = (self.library / name).resolve()
        self.window.sidebar.setCurrentItem(self.window.items[path])
        APP.processEvents()
        self.assertEqual(self.window.active_path, path)
        return path

    def test_parserless_script_has_no_parameters_and_remains_runnable(self) -> None:
        path = self.library / "parserless.py"
        path.write_text('"""Parserless tool."""\ndef main():\n    print("[SCRIPT] Hello")\n', encoding="utf-8")
        self.window.refresh_scripts()
        self.select(path.name)
        panel = self.window.parameters
        self.assertEqual(panel.description_label.text(), "Parserless tool.")
        self.assertEqual(panel.form.editors, {})
        self.assertTrue(panel.run_button.isEnabled())
        self.assertIn("main_runner.py", panel.command_preview.toPlainText())
        panel.run_mode.setCurrentIndex(1)
        panel.batch_form.editors["target_directory"].control.set_path(str(self.library))
        APP.processEvents()
        self.assertTrue(panel.batch_group.isVisible())
        self.assertTrue(panel.run_button.isEnabled())
        self.assertIn("batch_runner.py", panel.command_preview.toPlainText())

    def test_last_library_can_be_removed_and_empty_selection_persists(self) -> None:
        self.select("basic_types.py")
        panel = self.window.settings_panel
        self.assertTrue(panel.folder_rows[0].remove_button.isEnabled())
        panel.folder_rows[0].remove_button.click()
        APP.processEvents()
        self.assertEqual(panel.selected_folders(), [])
        self.assertEqual(self.settings.scripts_folders, [])
        self.assertIsNone(self.settings.scripts_folder)
        self.assertIsNone(self.window.active_path)
        self.assertEqual(self.window.sidebar.topLevelItemCount(), 0)
        self.settings.store.sync()
        restored = AppSettings(self.root, QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat))
        self.assertEqual(restored.scripts_folders, [])
        with patch("app.settings_panel.QFileDialog.getExistingDirectory", return_value=str(self.library)):
            panel._add_library()
        APP.processEvents()
        self.assertEqual(self.settings.scripts_folders, [self.library])
        self.assertEqual(len(self.window.items), 4)
        self.assertTrue(panel.folder_rows[0].remove_button.isEnabled())

    def test_navigation_and_controls_keep_values_and_argparse_mapping(self) -> None:
        self.assertEqual([self.window.tabs.tabText(i) for i in range(3)], ["Script", "Log", "Settings"])
        self.assertEqual(self.window.sidebar.topLevelItem(0).text(0), "scripts")
        self.select("basic_types.py")
        panel = self.window.parameters
        for name, widget_type in {"name": QLineEdit, "count": QSpinBox, "scale": QDoubleSpinBox, "verbose": QCheckBox}.items():
            self.assertIsInstance(panel.form.editors[name].control, widget_type)
        self.assertEqual(panel.run_button.property("role"), "primary")
        self.assertEqual(panel.stop_button.property("role"), "danger")
        panel.form.editors["name"].control.setText("First & value")
        strings = panel.form.editors["name"].string_inputs
        strings.add_button.click()
        strings.controls[1].setText("Second value")
        before = panel.form.arguments()
        self.assertIn("Second value", panel.command_preview.toPlainText())
        self.select("choices.py")
        self.assertIsInstance(panel.form.editors["format"].control, QComboBox)
        self.select("basic_types.py")
        self.assertEqual(panel.form.arguments(), before)
        self.assertEqual(self.window.script_heading.text(), "Basic Types")
        self.assertIn("basic_types.py", self.window.script_subtitle.text())

    def test_batch_controls_and_blender_launch_arguments_are_preserved(self) -> None:
        script = self.select("choices.py")
        panel = self.window.parameters
        panel.run_mode.setCurrentIndex(1)
        self.assertTrue(panel.batch_group.isVisible())
        self.assertFalse(panel.runtime.isEnabled())
        panel.batch_form.editors["target_directory"].control.set_path(str(self.root))
        panel.batch_form.editors["include_shots"].control.setText("1,4-8,12")
        panel.batch_form.editors["exclude_shots"].control.setText("6")
        arguments = panel.batch_form.arguments()
        self.assertEqual(arguments.count("--include-shots"), 3)
        self.assertIn("--exclude-shots", arguments)
        state = self.window.processes.state_for(script)
        self.assertEqual(build_process_arguments(script, ["--format", "PNG"], state), [
            "--background", "--disable-liboverride-auto-resync", "--python", str(script), "--", "--format", "PNG"
        ])
        panel.run_mode.setCurrentIndex(0)
        self.assertFalse(panel.batch_group.isVisible())

    def test_description_is_first_and_run_mode_defaults_preserve_session_choices(self) -> None:
        sample = self.library / "metadata_batch.py"
        sample.write_text(
            "import argparse\ndef create_parser():\n"
            "    parser = argparse.ArgumentParser(description='Modify each selected scene.\\nKeep existing materials.')\n"
            "    parser.script_metadata = {'default_run_mode': 'batch'}\n"
            "    return parser\n", encoding="utf-8",
        )
        self.window.refresh_scripts()
        self.select(sample.name)
        panel = self.window.parameters
        self.assertIs(panel.scroll.widget().layout().itemAt(0).widget(), panel.description_group)
        self.assertEqual(panel.description_label.text(), "Modify each selected scene.\nKeep existing materials.")
        self.assertEqual(panel.description_label.textFormat(), Qt.TextFormat.PlainText)
        self.assertEqual(panel.run_mode.currentIndex(), 1)
        self.assertTrue(panel.run_mode.isEnabled())
        self.assertTrue(panel.batch_group.isVisible())
        self.assertEqual(panel.runtime.currentText(), "Blender")
        panel.run_mode.setCurrentIndex(0)
        self.select("choices.py")
        self.select(sample.name)
        self.assertEqual(panel.run_mode.currentIndex(), 0)
        self.window.refresh_scripts()
        self.assertEqual(panel.run_mode.currentIndex(), 0)

    def test_forced_run_modes_remain_locked_after_updates_and_switching(self) -> None:
        for mode, index in (("single", 0), ("batch", 1)):
            sample = self.library / f"forced_{mode}.py"
            sample.write_text(
                "import argparse\ndef create_parser():\n"
                "    parser = argparse.ArgumentParser()\n"
                f"    parser.script_metadata = {{'default_run_mode': '{mode}', 'force_default_run_mode': True}}\n"
                "    return parser\n", encoding="utf-8",
            )
            self.window.refresh_scripts()
            path = self.select(sample.name)
            panel = self.window.parameters
            self.assertEqual(panel.run_mode.currentIndex(), index)
            self.assertFalse(panel.run_mode.isEnabled())
            self.assertEqual(panel.description_label.text(), "No description provided.")
            panel.run_mode.setCurrentIndex(1 - index)
            self.assertEqual(panel.run_mode.currentIndex(), index)
            self.assertEqual(self.window.processes.state_for(path).batch_mode, bool(index))
            panel.update_state()
            self.assertFalse(panel.run_mode.isEnabled())
            self.select("choices.py")
            self.select(sample.name)
            self.assertEqual(panel.run_mode.currentIndex(), index)
            self.assertFalse(panel.run_mode.isEnabled())

    def test_forced_batch_does_not_fall_back_to_single_if_batch_support_is_missing(self) -> None:
        sample = self.library / "requires_batch.py"
        sample.write_text(
            "import argparse\ndef create_parser():\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.script_metadata = {'default_run_mode': 'batch', 'force_default_run_mode': True}\n"
            "    return parser\n", encoding="utf-8",
        )
        self.window.parameters.batch_parameters = None
        self.window.parameters.batch_error = "Missing batch helper"
        self.window.refresh_scripts()
        self.select(sample.name)
        panel = self.window.parameters
        self.assertEqual(panel.run_mode.currentIndex(), 1)
        self.assertFalse(panel.run_mode.isEnabled())
        self.assertFalse(panel.run_button.isEnabled())
        self.assertTrue(panel.batch_group.isVisible())
        self.assertTrue(any("Missing batch helper" in label.text() for label in panel.batch_group.findChildren(QLabel)))

    def test_command_preview_colors_and_copy_preserve_literal_text(self) -> None:
        self.select("basic_types.py")
        panel = self.window.parameters
        panel.form.editors["name"].control.setText("A '--count' value")
        preview = panel.command_preview.toPlainText()
        self.assertIn("--name 'A ''--count'' value'", preview)
        panel.command_highlighter.rehighlight()
        document = panel.command_preview.document()
        block = document.begin()
        while block.isValid() and not block.text().lstrip().startswith("--name "):
            block = block.next()
        self.assertTrue(block.isValid())

        def color_at(position: int) -> str:
            for item in block.layout().formats():
                if item.start <= position < item.start + item.length:
                    return item.format.foreground().color().name()
            self.fail(f"No format at {position}")

        text = block.text()
        self.assertEqual(color_at(text.index("--name")), PALETTE["accent"])
        self.assertEqual(color_at(text.index("--count")), PALETTE["success"])
        self.assertEqual(color_at(text.rindex("`")), PALETTE["command_text"])
        first = document.begin()
        self.assertTrue(all(item.format.foreground().color().name() == PALETTE["command_text"] for item in first.layout().formats()))
        original_clipboard = APP.clipboard().text()
        try:
            panel.copy_command_button.click()
            self.assertEqual(APP.clipboard().text(), preview)
            self.assertEqual(panel.command_preview.toPlainText(), preview)
        finally:
            APP.clipboard().setText(original_clipboard)

    def test_checkbox_pointer_is_limited_to_its_clickable_label_and_indicator(self) -> None:
        self.select("basic_types.py")
        checkbox = self.window.parameters.form.editors["verbose"].control

        def hover(point: QPoint) -> None:
            APP.sendEvent(checkbox, QMouseEvent(
                QEvent.Type.MouseMove, QPointF(point), QPointF(checkbox.mapToGlobal(point)),
                Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            ))

        for x in (8, 40):
            hover(QPoint(x, checkbox.height() // 2))
            self.assertEqual(checkbox.cursor().shape(), Qt.CursorShape.PointingHandCursor)
        hover(QPoint(checkbox.width() - 8, checkbox.height() // 2))
        self.assertEqual(checkbox.cursor().shape(), Qt.CursorShape.ArrowCursor)
        checkbox.setEnabled(False)
        hover(QPoint(8, checkbox.height() // 2))
        self.assertEqual(checkbox.cursor().shape(), Qt.CursorShape.ArrowCursor)

    def test_command_preview_fits_long_and_wrapped_commands_then_shrinks(self) -> None:
        self.select("basic_types.py")
        panel = self.window.parameters
        preview = panel.command_preview
        QTest.qWait(30)
        original_height = preview.height()
        panel.form.editors["name"].control.setText("Long command value " * 100)
        QTest.qWait(30)
        wide_height = preview.height()
        self.assertGreater(wide_height, original_height)
        self.assertEqual(preview.verticalScrollBar().maximum(), 0)
        self.window.resize(820, 620)
        QTest.qWait(30)
        self.assertGreaterEqual(preview.height(), wide_height)
        self.assertEqual(preview.verticalScrollBar().maximum(), 0)
        self.window.resize(1100, 780)
        panel.form.editors["name"].control.setText("World")
        QTest.qWait(30)
        self.assertEqual(preview.height(), original_height)
        many_lines = "\n".join(f"--argument-{index} 'value'" for index in range(250))
        preview.setPlainText(many_lines)
        QTest.qWait(30)
        self.assertEqual(preview.toPlainText(), many_lines)
        self.assertEqual(preview.document().blockCount(), 250)
        self.assertEqual(preview.verticalScrollBar().maximum(), 0)

    def test_last_run_values_reload_after_restart_and_unsaved_edits_stay_in_session(self) -> None:
        sample = self.library / "saved_parameters.py"
        sample.write_text(
            "import argparse\nfrom pathlib import Path\ndef create_parser():\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('--name', default='Default')\n"
            "    parser.add_argument('--count', type=int)\n"
            "    parser.add_argument('--scale', type=float)\n"
            "    parser.add_argument('--items', type=int, nargs='+')\n"
            "    parser.add_argument('--file', type=Path)\n"
            "    parser.add_argument('--verbose', action='store_true')\n"
            "    return parser\n", encoding="utf-8",
        )
        self.window.refresh_scripts()
        self.select(sample.name)
        panel = self.window.parameters
        panel.runtime.setCurrentText("Python")
        editors = panel.form.editors
        editors["name"].control.setText("First")
        editors["name"].string_inputs.add_value("Last saved")
        editors["count"].control.setText("8")
        editors["scale"].control.setText("1.25")
        editors["items"].control.setText("1")
        editors["items"].multiple_inputs.add_value("3")
        editors["verbose"].control.setChecked(True)
        with patch("app.string_widgets.QFileDialog.getOpenFileName", return_value=(str(sample), "")):
            editors["file"].control.browse_button.click()
        panel.batch_form.editors["target_directory"].control.set_path(str(self.root))
        panel.batch_form.editors["include_shots"].control.setText("1,4-8")
        self.assertFalse(self.window.parameter_configs.path.exists())
        expected = panel.form.arguments()
        panel.run_button.click()
        wait_until(lambda: not self.window.processes.state_for(sample.resolve()).is_running)
        config = self.window.parameter_configs.path
        self.assertTrue(config.is_file())
        previous = config.read_bytes()
        editors["name"].control.setText("Unsaved edit")
        self.select("choices.py")
        self.select(sample.name)
        self.assertEqual(self.window.parameters.form.editors["name"].control.text(), "Unsaved edit")
        self.assertEqual(config.read_bytes(), previous)
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.window = MainWindow(self.root, self.settings, auto_discover=False,
                                 parameter_configs=ParameterConfigStore(self.root / "script_parameters.json"))
        self.window.show()
        self.select(sample.name)
        self.assertEqual(self.window.parameters.form.arguments(), expected)
        self.assertEqual(len(self.window.parameters.form.editors["name"].string_inputs.controls), 2)
        self.assertEqual(self.window.parameters.batch_form.editors["include_shots"].control.text(), "1,4-8")

    def test_config_errors_do_not_break_loading_or_execution(self) -> None:
        path = self.library / "choices.py"
        self.window.parameter_configs.path.write_text("invalid json", encoding="utf-8")
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.window = MainWindow(self.root, self.settings, auto_discover=False,
                                 parameter_configs=ParameterConfigStore(self.root / "script_parameters.json"))
        self.window.show()
        self.assertIn("Could not restore parameters", self.window.statusBar().currentMessage())
        self.select(path.name)
        self.assertEqual(self.window.parameters.form.editors["format"].control.currentText(), "PNG")
        self.window.parameters.runtime.setCurrentText("Python")
        self.window.parameters.filter_enabled.setChecked(False)
        self.window.parameters.filter_log_enabled.setChecked(False)
        with patch.object(self.window.parameter_configs, "save", side_effect=PermissionError("read only")):
            self.window.parameters.run_button.click()
        wait_until(lambda: not self.window.processes.state_for(path.resolve()).is_running)
        self.assertIn("Could not save parameter config", self.window.parameters.error_label.text())
        self.assertIn("Selected format: PNG", self.window.log.output.toPlainText() + self.window.processes.state_for(path.resolve()).current_log_path.read_text())

    def test_batch_launch_saves_both_script_and_selection_values(self) -> None:
        script = self.select("choices.py")
        panel = self.window.parameters
        target = self.root / "blend files"
        target.mkdir()
        blend = target / "shot0002.blend"
        blend.write_bytes(b"batch discovery fixture")
        panel.run_mode.setCurrentIndex(1)
        panel.form.editors["format"].control.setCurrentText("EXR")
        panel.batch_form.editors["target_directory"].control.set_path(str(target))
        panel.batch_form.editors["include_shots"].control.setText("1-3")
        panel.batch_form.editors["purge_unused_data"].control.setChecked(True)
        with patch.object(self.window.processes, "start", return_value=True) as start:
            panel.run_button.click()
        payload = start.call_args.kwargs["batch_payload"]
        self.assertEqual(payload["files"], [str(blend.resolve())])
        self.assertTrue(payload["purge_unused_data"])
        saved, batch = self.window.parameter_configs.load(script, panel.form.parameters, panel.batch_form.parameters)
        self.assertEqual(saved["format"].value, "EXR")
        self.assertEqual(batch["target_directory"].value, str(target))
        self.assertEqual(batch["include_shots"].value, "1-3")
        self.assertTrue(batch["purge_unused_data"].value)

    def test_repeated_fields_keep_height_spacing_and_label_alignment(self) -> None:
        self.select("basic_types.py")
        form = self.window.parameters.form
        inputs = form.editors["name"].string_inputs
        for value in ("Second value", "Third value"):
            inputs.add_button.click()
            inputs.controls[-1].setText(value)
        for width, height in ((1100, 780), (820, 620)):
            self.window.resize(width, height)
            APP.processEvents()
            for index, (name, editor) in enumerate(form.editors.items()):
                label = form.labels[name]
                self.assertEqual(label.height(), CONTROL_HEIGHT)
                self.assertEqual(label.mapTo(form, QPoint()).y(), editor.control.mapTo(form, QPoint()).y(), name)
            for index, control in enumerate(inputs.controls):
                self.assertEqual(control.height(), CONTROL_HEIGHT)
                option = QStyleOptionFrame()
                option.initFrom(control)
                contents = control.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, control)
                self.assertGreaterEqual(contents.height(), control.fontMetrics().height())
                if index:
                    previous = inputs.controls[index - 1]
                    gap = control.mapTo(inputs, QPoint()).y() - previous.mapTo(inputs, QPoint()).y() - previous.height()
                    self.assertGreaterEqual(gap, SMALL)
        inputs.controls[1].parentWidget().findChild(QPushButton).click()
        APP.processEvents()
        self.assertEqual(len(inputs.controls), 2)
        self.assertTrue(all(control.height() == CONTROL_HEIGHT for control in inputs.controls))

    def test_adding_rows_without_resizing_moves_following_parameters_down(self) -> None:
        self.select("basic_types.py")
        form = self.window.parameters.form
        inputs = form.editors["name"].string_inputs
        original_height = form.height()

        def check_bounds() -> None:
            QTest.qWait(20)
            wrappers = list(form.fields.values())
            for current, following in zip(wrappers, wrappers[1:]):
                self.assertGreaterEqual(following.y(), current.y() + current.height() + SMALL)
            for control in inputs.controls:
                self.assertLessEqual(control.mapTo(wrappers[0], QPoint()).y() + control.height(), wrappers[0].height())
            self.assertGreaterEqual(form.height(), wrappers[-1].y() + wrappers[-1].height())

        for index in range(6):
            inputs.add_button.click()
            inputs.controls[-1].setText(f"Additional value {index}")
            check_bounds()
        self.assertGreater(form.height(), original_height)
        while len(inputs.controls) > 1:
            inputs.controls[-1].parentWidget().findChild(QPushButton).click()
            check_bounds()
        self.assertEqual(form.height(), original_height)

    def test_deleting_middle_rows_reflows_string_and_nargs_controls(self) -> None:
        sample = self.library / "repeated_numbers.py"
        sample.write_text(
            "import argparse\ndef create_parser():\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('--items', type=int, nargs='+')\n"
            "    parser.add_argument('--following', default='Next parameter')\n"
            "    return parser\n", encoding="utf-8"
        )
        self.window.refresh_scripts()
        for script, name in (("basic_types.py", "name"), ("repeated_numbers.py", "items")):
            self.select(script)
            form = self.window.parameters.form
            editor = form.editors[name]
            inputs = editor.string_inputs or editor.multiple_inputs
            for index in range(4):
                inputs.add_button.click()
                inputs.controls[-1].setText(str(index + 1))
            QTest.qWait(20)
            while len(inputs.controls) > 1:
                inputs.controls[1].parentWidget().findChild(QPushButton).click()
                # Check before deferred events too: the removed row's minimum
                # size must not remain cached until the next click or resize.
                for _ in range(2):
                    self.assertEqual(inputs.minimumHeight(), inputs.layout().minimumSize().height())
                    for control in inputs.controls:
                        self.assertEqual(control.height(), CONTROL_HEIGHT)
                        self.assertTrue(control.parentWidget().rect().contains(control.geometry()))
                    current, following = list(form.fields.values())[:2]
                    self.assertGreaterEqual(following.y(), current.y() + current.height() + SMALL)
                    for control in inputs.controls:
                        bottom = control.mapTo(form, QPoint()).y() + control.height()
                        self.assertLessEqual(bottom, current.y() + current.height())
                        self.assertLessEqual(bottom + SMALL, following.y())
                    QTest.qWait(20)

    def test_deletion_keeps_wrapped_help_and_following_fields_separate(self) -> None:
        sample = self.library / "wrapped_fields.py"
        sample.write_text(
            "import argparse\ndef create_parser():\n"
            "    parser = argparse.ArgumentParser()\n"
            "    for name in ('first', 'second', 'third'):\n"
            "        parser.add_argument('--' + name, default='value', help='A longer description of this parameter that wraps at smaller window widths.')\n"
            "    return parser\n", encoding="utf-8"
        )
        self.window.refresh_scripts()
        self.select(sample.name)
        form = self.window.parameters.form
        for width in (760, 1100, 820):
            self.window.resize(width, 620)
            QTest.qWait(20)
            for editor in form.editors.values():
                for _ in range(4):
                    editor.string_inputs.add_button.click()
            QTest.qWait(20)
            for name, editor in form.editors.items():
                inputs = editor.string_inputs
                while len(inputs.controls) > 1:
                    inputs.controls[1].parentWidget().findChild(QPushButton).click()
                    QTest.qWait(20)
                    wrappers = list(form.fields.values())
                    for wrapper, item in zip(wrappers, form.editors.values()):
                        for control in item.string_inputs.controls:
                            self.assertLessEqual(control.mapTo(wrapper, QPoint()).y() + control.height(), wrapper.height(), name)
                        for child in wrapper.findChildren(QLabel):
                            if child.isVisible():
                                self.assertLessEqual(child.mapTo(wrapper, QPoint()).y() + child.height(), wrapper.height(), name)
                    for current, following in zip(wrappers, wrappers[1:]):
                        self.assertGreaterEqual(following.y(), current.y() + current.height() + SMALL)

    def test_concurrent_runs_switch_logs_and_clear_only_view(self) -> None:
        output = self.select("output_test.py")
        panel = self.window.parameters
        panel.runtime.setCurrentText("Python")
        panel.filter_log_enabled.setChecked(False)
        panel.form.editors["steps"].control.setValue(40)
        panel.form.editors["delay"].control.setValue(0.05)
        panel.run_button.click()
        state = self.window.processes.state_for(output)
        self.assertTrue(state.is_running)
        self.assertFalse(panel.run_button.isEnabled())
        self.assertTrue(panel.stop_button.isEnabled())
        self.assertIn("Running", self.window.items[output].text(0))
        self.assertEqual(self.window.script_badge.text(), "Running")
        self.assertFalse(self.window.processes.start(self.window.scripts[output], sys.executable, []))
        choices = self.select("choices.py")
        panel.runtime.setCurrentText("Python")
        panel.filter_enabled.setChecked(False)
        panel.run_button.click()
        wait_until(lambda: not self.window.processes.state_for(choices).is_running)
        self.assertTrue(state.is_running)
        self.assertIn("Selected format: PNG", self.window.log.output.toPlainText())
        self.select("output_test.py")
        wait_until(lambda: "[SCRIPT] Processing" in self.window.log.output.toPlainText())
        self.assertNotIn("Generic diagnostic", self.window.log.output.toPlainText())
        self.assertIn("Generic diagnostic", state.current_log_path.read_text())
        self.window.log.clear_button.click()
        self.assertFalse(state.visible_log)
        self.assertTrue(state.current_log_path.is_file())
        panel.stop_button.click()
        wait_until(lambda: not state.is_running)
        self.assertTrue(panel.run_button.isEnabled())
        self.assertIn("Exit status:", state.current_log_path.read_text())
        self.select("choices.py")
        self.assertIn("Selected format: PNG", self.window.log.output.toPlainText())

    def test_log_filter_option_keeps_its_existing_behavior(self) -> None:
        output = self.select("output_test.py")
        panel = self.window.parameters
        self.assertTrue(panel.filter_enabled.isChecked())
        self.assertTrue(panel.filter_log_enabled.isChecked())
        self.assertEqual(panel.output_filter.text(), "[SCRIPT]")
        panel.runtime.setCurrentText("Python")
        panel.form.editors["steps"].control.setValue(1)
        panel.form.editors["delay"].control.setValue(0)
        panel.run_button.click()
        state = self.window.processes.state_for(output)
        wait_until(lambda: not state.is_running)
        log = state.current_log_path.read_text()
        self.assertIn("[SCRIPT] Processing", log)
        self.assertNotIn("Generic diagnostic", log)
        self.assertIn("Arguments:", log)
        self.assertIn("[stderr]", self.window.log.output.toPlainText())

    def test_creation_buttons_and_invalid_executable_still_work(self) -> None:
        for button, name in ((self.window.create_script_button, "blank.py"), (self.window.create_batch_button, "batch.py")):
            with patch("app.main_window.QInputDialog.getText", return_value=(name, True)):
                button.click()
            script = (self.library / name).resolve()
            self.assertEqual(self.window.active_path, script)
            self.assertIsNone(self.window.scripts[script].inspection_error)
            self.assertEqual(self.window.parameters.runtime.currentText(), "Blender")
        self.select("choices.py")
        panel = self.window.parameters
        panel.runtime.setCurrentText("Python")
        selector = self.window.settings_panel.selectors["Python"]
        selector.combo.setEditText(str(self.root / "missing.exe"))
        selector.combo.lineEdit().editingFinished.emit()
        panel.run_button.click()
        state = self.window.processes.state_for(self.window.active_path)
        self.assertFalse(state.is_running)
        self.assertIn("Invalid Python executable", panel.error_label.text())
        self.assertIn("Invalid Python executable", state.current_log_path.read_text())

    def test_refresh_keeps_running_script_reachable_if_library_disappears(self) -> None:
        path = self.select("output_test.py")
        panel = self.window.parameters
        panel.runtime.setCurrentText("Python")
        panel.run_button.click()
        state = self.window.processes.state_for(path)
        self.window.settings_panel.folder_edit.setText(str(self.root / "unavailable"))
        self.window.settings_panel.folder_edit.editingFinished.emit()
        self.assertTrue(state.is_running)
        self.assertIn(path, self.window.items)
        self.assertIn("unavailable", self.window.settings_panel.message.text())
        self.assertTrue(panel.stop_button.isEnabled())
        panel.stop_button.click()
        wait_until(lambda: not state.is_running)

    def test_settings_library_browse_refresh_and_executable_selection(self) -> None:
        self.window.settings_shortcut.click()
        self.assertEqual(self.window.tabs.currentWidget(), self.window.settings_panel)
        extra = self.root / "tools"
        extra.mkdir()
        shutil.copyfile(self.library / "choices.py", extra / "other.py")
        with patch("app.settings_panel.QFileDialog.getExistingDirectory", return_value=str(extra)):
            self.window.settings_panel.add_library_button.click()
        self.assertEqual(self.window.sidebar.topLevelItemCount(), 2)
        self.assertEqual(self.settings.scripts_folders, [self.library, extra])
        self.assertIn((extra / "other.py").resolve(), self.window.items)
        selector = self.window.settings_panel.selectors["Python"]
        selector.add_executable(ExecutableInfo(Path(sys.executable), "Python", "3.13"))
        self.assertEqual(selector.path(), sys.executable)
        self.assertEqual(selector.path_label.text(), sys.executable)
        self.assertEqual(self.settings.executable("Python"), sys.executable)
        new_path = extra / "added.py"
        new_path.write_text("import argparse\ndef create_parser():\n    return argparse.ArgumentParser()\n")
        self.window.settings_panel.refresh_requested.emit()
        self.assertIn(new_path.resolve(), self.window.items)

    def test_invalid_script_is_readable_and_small_window_can_scroll(self) -> None:
        self.select("missing_parser.py")
        self.assertFalse(self.window.parameters.run_button.isEnabled())
        self.assertIn("create_parser", self.window.parameters.error_label.text())
        self.assertTrue(self.window.parameters.error_label.isVisible())
        self.assertEqual(self.window.script_badge.text(), "Unavailable")
        self.select("basic_types.py")
        self.window.resize(820, 620)
        APP.processEvents()
        panel = self.window.parameters
        self.assertEqual(panel.scroll.horizontalScrollBar().maximum(), 0)
        self.assertGreater(panel.scroll.verticalScrollBar().maximum(), 0)
        self.assertTrue(panel.run_button.isVisible())
        panel.scroll.ensureWidgetVisible(panel.command_preview)
        APP.processEvents()
        self.assertTrue(panel.command_preview.isReadOnly())
        self.assertTrue(panel.command_preview.visibleRegion().rectCount() > 0)

    def test_unavailable_scripts_are_red_and_header_opens_source(self) -> None:
        path = self.select("missing_parser.py")
        item = self.window.items[path]
        self.assertEqual(item.foreground(0).color().name(), PALETTE["danger"])
        self.assertIn("Unavailable", item.text(0))
        button = self.window.open_script_button
        self.assertTrue(button.isVisible())
        self.assertTrue(button.isEnabled())
        self.assertEqual(button.text(), "")
        self.assertFalse(button.icon().isNull())
        with patch("app.main_window.open_script_file", return_value=True) as opened:
            button.click()
        opened.assert_called_once_with(path)
        with patch("app.main_window.open_script_file", return_value=False):
            button.click()
        self.assertIn("Could not open script", self.window.statusBar().currentMessage())
        # Editing a broken parser and refreshing restores the ordinary row color.
        path.write_text("import argparse\ndef create_parser():\n    return argparse.ArgumentParser()\n", encoding="utf-8")
        self.window.refresh_scripts()
        self.assertNotEqual(self.window.items[path].foreground(0).color().name(), PALETTE["danger"])
