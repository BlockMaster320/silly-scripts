import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import APP, wait_until
from PySide6.QtCore import QSettings
from PySide6.QtTest import QTest

from app.main_window import MainWindow
from app.models import ExecutableInfo
from app.parameter_config import ParameterConfigStore
from app.settings import AppSettings

EXAMPLES = Path(__file__).resolve().parents[1] / "scripts" / "test_scripts"


class WindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="launcher ui ")
        self.root = Path(self.temp.name)
        self.library = self.root / "test_scripts"
        shutil.copytree(EXAMPLES, self.library)
        self.settings_path = self.root / "settings.ini"
        store = QSettings(str(self.settings_path), QSettings.Format.IniFormat)
        self.settings = AppSettings(self.root, store)
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

    def test_tabs_invalid_script_and_session_values(self) -> None:
        self.assertEqual([self.window.tabs.tabText(i) for i in range(self.window.tabs.count())], ["Parameters", "Log", "Settings"])
        self.select("basic_types.py")
        panel = self.window.parameters
        panel.form.editors["name"].control.setText("Retained name")
        panel.runtime.setCurrentText("Blender")
        panel.background.setChecked(True)
        panel.resync.setChecked(True)
        panel.output_filter.setText("marker")
        panel.filter_enabled.setChecked(True)
        self.select("choices.py")
        self.assertEqual(panel.runtime.currentText(), "Python")
        self.assertTrue(panel.background.isChecked())
        self.select("basic_types.py")
        self.assertEqual(panel.form.editors["name"].control.text(), "Retained name")
        self.assertEqual(panel.runtime.currentText(), "Blender")
        self.assertTrue(panel.background.isChecked())
        self.assertTrue(panel.resync.isChecked())
        self.assertEqual(panel.output_filter.text(), "marker")
        self.assertTrue(panel.filter_enabled.isChecked())
        self.select("missing_parser.py")
        self.assertFalse(panel.run_button.isEnabled())
        self.assertIn("create_parser", panel.error_label.text())

    def test_selection_does_not_interrupt_concurrent_processes_or_logs(self) -> None:
        output = self.select("output_test.py")
        self.window.parameters.run_button.click()
        state = self.window.processes.state_for(output)
        self.assertTrue(state.is_running)
        self.assertFalse(self.window.parameters.run_button.isEnabled())
        self.assertTrue(self.window.parameters.stop_button.isEnabled())
        self.assertTrue(self.window.items[output].text(0).startswith("●"))
        choices = self.select("choices.py")
        self.window.parameters.run_button.click()
        wait_until(lambda: not self.window.processes.state_for(choices).is_running)
        self.assertTrue(state.is_running)
        self.assertIn("Selected format: PNG", self.window.log.output.toPlainText())
        self.select("output_test.py")
        wait_until(lambda: "[MY_SCRIPT]" in self.window.log.output.toPlainText())
        self.assertNotIn("Selected format", self.window.log.output.toPlainText())
        self.window.log.clear_button.click()
        self.assertEqual(self.window.log.output.toPlainText(), "")
        self.assertFalse(state.visible_log)
        self.assertTrue(state.current_log_path.exists())
        self.window.parameters.stop_button.click()
        wait_until(lambda: not state.is_running)
        self.assertTrue(self.window.parameters.run_button.isEnabled())
        self.assertFalse(self.window.parameters.stop_button.isEnabled())
        self.select("choices.py")
        self.assertIn("Selected format: PNG", self.window.log.output.toPlainText())

    def test_refresh_and_missing_folder_keep_running_script_reachable(self) -> None:
        path = self.select("output_test.py")
        self.window.parameters.run_button.click()
        state = self.window.processes.state_for(path)
        self.window.settings_panel.folder_edit.setText(str(self.root / "removed folder"))
        self.window.settings_panel.folder_edit.editingFinished.emit()
        self.assertTrue(state.is_running)
        self.assertIn(path, self.window.items)
        self.assertIn("unavailable", self.window.settings_panel.message.text())
        self.assertTrue(self.window.parameters.stop_button.isEnabled())
        self.window.parameters.stop_button.click()
        wait_until(lambda: not state.is_running)
        self.window.settings_panel.folder_edit.setText(str(self.library))
        self.window.settings_panel.folder_edit.editingFinished.emit()
        extra = self.library / "new_script.py"
        extra.write_text("import argparse\ndef create_parser():\n    return argparse.ArgumentParser()\n")
        self.window.settings_panel.refresh_requested.emit()
        self.assertIn(extra.resolve(), self.window.items)

    def test_executable_version_updates_preserve_selection_and_settings(self) -> None:
        selector = self.window.settings_panel.selectors["Python"]
        selected = selector.path()
        selector.add_executable(ExecutableInfo(Path(selected), "Python", "3.12.10"))
        selector.add_executable(ExecutableInfo(self.root / "other python.exe", "Python", "3.13.7"))
        self.assertEqual(selector.path(), selected)
        self.window.close()
        restored = AppSettings(self.root, QSettings(str(self.settings_path), QSettings.Format.IniFormat))
        self.assertEqual(restored.executable("Python"), selected)
        self.assertTrue(restored.geometry())

    def test_close_finishes_logs_without_blocking(self) -> None:
        path = self.select("output_test.py")
        self.window.parameters.run_button.click()
        state = self.window.processes.state_for(path)
        self.window.close()
        wait_until(lambda: not self.window.isVisible())
        self.assertFalse(state.is_running)
        self.assertIsNone(state.process)
        self.assertIn("Finished:", state.current_log_path.read_text())

    def test_typing_decimal_does_not_reformat_each_keystroke(self) -> None:
        self.select("basic_types.py")
        control = self.window.parameters.form.editors["scale"].control
        control.setFocus()
        control.lineEdit().selectAll()
        QTest.keyClicks(control.lineEdit(), f"12{control.locale().decimalPoint()}75")
        self.assertEqual(control.value(), 12.75)
        self.assertIn("12.75", self.window.parameters.form.arguments())

    def test_creation_buttons_select_new_blender_scripts(self) -> None:
        for button, name, batch in (
            (self.window.create_script_button, "new_blank.py", False),
            (self.window.create_batch_button, "new_batch.py", True),
        ):
            with patch("app.main_window.QInputDialog.getText", return_value=(name, True)):
                button.click()
            path = self.library / name
            self.assertTrue(path.is_file())
            self.assertEqual(self.window.active_path, path)
            self.assertIsNone(self.window.scripts[path].inspection_error)
            self.assertEqual(self.window.parameters.runtime.currentText(), "Blender")
            self.assertTrue(self.window.parameters.background.isChecked())
            self.assertTrue(self.window.parameters.resync.isChecked())
            self.assertEqual(self.window.tabs.currentWidget(), self.window.parameters)

    def test_creation_cancel_and_existing_file(self) -> None:
        original_path = self.window.active_path
        with patch("app.main_window.QInputDialog.getText", return_value=("cancelled.py", False)):
            self.window.create_script_button.click()
        self.assertEqual(self.window.active_path, original_path)
        self.assertFalse((self.library / "cancelled.py").exists())
        original = (self.library / "basic_types.py").read_bytes()
        with patch("app.main_window.QInputDialog.getText", return_value=("basic_types.py", True)), patch("app.main_window.QMessageBox.warning") as warning:
            self.window.create_batch_button.click()
            warning.assert_called_once()
        self.assertEqual((self.library / "basic_types.py").read_bytes(), original)

    def test_added_string_rows_survive_selection_and_defaults_remain_per_script(self) -> None:
        self.select("basic_types.py")
        panel = self.window.parameters
        inputs = panel.form.editors["name"].string_inputs
        inputs.add_button.click()
        inputs.controls[1].setText("extra name")
        panel.runtime.setCurrentText("Blender")
        self.assertTrue(panel.background.isChecked())
        self.assertTrue(panel.resync.isChecked())
        panel.background.setChecked(False)
        panel.resync.setChecked(False)
        self.select("choices.py")
        panel.runtime.setCurrentText("Blender")
        self.assertTrue(panel.background.isChecked())
        self.assertTrue(panel.resync.isChecked())
        self.select("basic_types.py")
        self.assertEqual(panel.form.editors["name"].string_inputs.values(), ["World", "extra name"])
        self.assertFalse(panel.background.isChecked())
        self.assertFalse(panel.resync.isChecked())

    def test_settings_scripts_folder_is_selected_through_dialog(self) -> None:
        panel = self.window.settings_panel
        self.assertTrue(panel.folder_edit.isReadOnly())
        other = self.root / "other scripts"
        other.mkdir()
        with patch("app.settings_panel.QFileDialog.getExistingDirectory", return_value=str(other)):
            panel._browse_folder()
        self.assertEqual(self.settings.scripts_folder, other)
        self.assertEqual(panel.folder_edit.text(), str(other))
        self.assertFalse(self.window.scripts)
