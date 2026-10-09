"""Render real Qt Widgets pages using isolated settings and sample Python scripts.

Run `python tools/render_ui.py`. Preferences and production scripts are not
modified; the sample process logs live in a temporary directory.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from app.main_window import MainWindow
from app.models import ExecutableInfo
from app.parameter_config import ParameterConfigStore
from app.settings import AppSettings
from app.ui.theme import apply_theme


def render() -> None:
    app = QApplication.instance() or QApplication([])
    # Qt's Windows offscreen plugin exposes no system fonts by default.
    if not QFontDatabase.families():
        font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "consola.ttf", "consolab.ttf"):
            font_path = font_directory / name
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
    apply_theme(app)
    destination = PROJECT / "docs" / "ui"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="launcher preview ") as directory:
        root = Path(directory)
        settings = AppSettings(root, QSettings(str(root / "preferences.ini"), QSettings.Format.IniFormat))
        settings.set_scripts_folders([PROJECT / "scripts" / "test_scripts"])
        settings.set_executable("Python", sys.executable)
        window = MainWindow(root, settings, auto_discover=False,
                            parameter_configs=ParameterConfigStore(root / "script_parameters.json"))
        window.settings_panel.add_executable(ExecutableInfo(Path(sys.executable), "Python", sys.version.split()[0]))
        window.resize(1120, 900)
        window.show()

        def capture(name: str, *, bottom: bool = False, focus: QWidget | None = None) -> None:
            QTest.qWait(120)
            if bottom:
                scrollbar = window.parameters.scroll.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            elif focus is not None:
                window.parameters.scroll.ensureWidgetVisible(focus)
            app.processEvents()
            if not window.grab().save(str(destination / name)):
                raise RuntimeError(f"Could not save {name}")

        basic = (PROJECT / "scripts" / "test_scripts" / "basic_types.py").resolve()
        window.sidebar.setCurrentItem(window.items[basic])
        window.parameters.runtime.setCurrentText("Python")
        capture("script.png")
        inputs = window.parameters.form.editors["name"].string_inputs
        for value in ("Second value", "Third value"):
            inputs.add_button.click()
            inputs.controls[-1].setText(value)
        capture("repeated.png")
        while len(inputs.controls) > 1:
            inputs.controls[1].parentWidget().findChild(QPushButton).click()
        capture("command.png", bottom=True)
        choices = (PROJECT / "scripts" / "test_scripts" / "choices.py").resolve()
        window.sidebar.setCurrentItem(window.items[choices])
        window.parameters.runtime.setCurrentText("Blender")
        window.parameters.run_mode.setCurrentIndex(1)
        window.parameters.batch_form.editors["target_directory"].control.set_path(str(PROJECT / "scripts" / "default"))
        window.parameters.batch_form.editors["include_shots"].control.setText("1,4-8,12")
        capture("batch.png", focus=window.parameters.batch_group)
        window.tabs.setCurrentWidget(window.settings_panel)
        capture("settings.png")
        window.resize(820, 620)
        window.tabs.setCurrentWidget(window.parameters)
        capture("compact.png")
        window.resize(1120, 900)
        output = (PROJECT / "scripts" / "test_scripts" / "output_test.py").resolve()
        window.sidebar.setCurrentItem(window.items[output])
        window.parameters.runtime.setCurrentText("Python")
        window.parameters.form.editors["steps"].control.setValue(12)
        window.parameters.run_button.click()
        deadline = time.monotonic() + 10
        while "Processing 4/12" not in window.log.output.toPlainText():
            if time.monotonic() > deadline:
                raise RuntimeError("Sample process did not produce expected output")
            QTest.qWait(20)
        capture("log.png")
        window.processes.stop(output)
        while window.processes.has_running:
            QTest.qWait(20)
        window.close()
        app.processEvents()
    print(f"Rendered seven Qt screenshots in {destination}")


if __name__ == "__main__":
    render()
