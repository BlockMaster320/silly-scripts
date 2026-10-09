import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import APP, wait_until
from PySide6.QtCore import QTimer

from app.models import ScriptInfo
from app.process_manager import ProcessManager


class ProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="launcher tests ")
        self.root = Path(self.temp.name)
        self.manager = ProcessManager(self.root / "logs", stop_timeout_ms=100)
        self.errors: list[str] = []
        self.manager.execution_error.connect(lambda path, message: self.errors.append(message))

    def tearDown(self) -> None:
        self.manager.stop_all()
        wait_until(lambda: not self.manager.has_running)
        APP.processEvents()
        self.manager.deleteLater()
        self.temp.cleanup()

    def script(self, name: str, source: str) -> ScriptInfo:
        path = self.root / name
        path.write_text(source, encoding="utf-8")
        return ScriptInfo(path, path.stem)

    def test_live_filtering_chunked_unicode_and_complete_unique_logs(self) -> None:
        script = self.script("output test.py", """
import os, time
os.write(1, b'generic line\\n[MY_')
time.sleep(0.06)
os.write(1, b'SCRIPT] caf\\xc3')
time.sleep(0.06)
os.write(1, b'\\xa9\\n')
time.sleep(0.06)
os.write(2, b'generic stderr\\n[my_script] warning\\n')
time.sleep(0.06)
os.write(1, b'[MY_SCRIPT] tail')
""")
        state = self.manager.state_for(script.path)
        state.filter_enabled = True
        state.output_filter = "[my_script]"
        self.assertTrue(self.manager.start(script, sys.executable, []))
        first_log = state.current_log_path
        wait_until(lambda: any("café" in line for line in state.visible_log))
        self.assertTrue(state.is_running)
        # Flushes to disk while the process is still running.
        self.assertIn(b"generic line", first_log.read_bytes())
        wait_until(lambda: not state.is_running)
        visible = "\n".join(state.visible_log)
        self.assertNotIn("generic", visible)
        self.assertIn("[stderr] [my_script] warning", visible)
        self.assertIn("[MY_SCRIPT] tail", visible)
        raw = first_log.read_bytes()
        self.assertIn(b"generic stderr", raw)
        self.assertIn("café".encode(), raw)
        self.assertIn(b"Exit code: 0", raw)
        self.assertIn(b"Exit status: NormalExit", raw)
        self.manager.clear_view(script.path)
        self.assertFalse(state.visible_log)
        self.assertEqual(first_log.read_bytes(), raw)
        self.assertTrue(self.manager.start(script, sys.executable, []))
        wait_until(lambda: not state.is_running)
        self.assertNotEqual(first_log, state.current_log_path)
        self.assertTrue(first_log.exists())

    def test_concurrent_scripts_duplicate_prevention_and_stop(self) -> None:
        first = self.script("first.py", "import time\nprint('ready', flush=True)\ntime.sleep(30)")
        second = self.script("second.py", "import time\nprint('second', flush=True)\ntime.sleep(0.25)")
        first_state = self.manager.state_for(first.path)
        second_state = self.manager.state_for(second.path)
        ticks: list[bool] = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start(10)
        self.addCleanup(timer.stop)
        self.assertTrue(self.manager.start(first, sys.executable, []))
        self.assertFalse(self.manager.start(first, sys.executable, []))
        self.assertTrue(self.manager.start(second, sys.executable, []))
        self.assertIsNot(first_state.process, second_state.process)
        wait_until(lambda: not second_state.is_running)
        self.assertTrue(first_state.is_running)
        self.manager.stop(first.path)
        wait_until(lambda: not first_state.is_running)
        self.assertGreater(len(ticks), 3)
        self.assertIn("Exit status:", first_state.current_log_path.read_text())

    def test_invalid_executable_and_failed_to_start(self) -> None:
        script = self.script("okay.py", "print('okay')")
        state = self.manager.state_for(script.path)
        self.assertFalse(self.manager.start(script, str(self.root / "missing.exe"), []))
        self.assertFalse(state.is_running)
        self.assertIn("Invalid Python executable", state.current_log_path.read_text())
        bad = self.root / "invalid.exe"
        bad.write_bytes(b"not an executable")
        self.manager.start(script, str(bad), [])
        wait_until(lambda: not state.is_running)
        self.assertEqual(state.status, "FailedToStart")
        self.assertIn("FailedToStart", state.current_log_path.read_text())
        self.assertIsNone(state.process)

    def test_nonzero_exit_and_missing_script(self) -> None:
        script = self.script("failure.py", "import sys\nprint('failure', file=sys.stderr)\nraise SystemExit(7)")
        state = self.manager.state_for(script.path)
        self.manager.start(script, sys.executable, [])
        wait_until(lambda: not state.is_running)
        self.assertIn("exit 7", state.status)
        self.assertIn("failure", state.current_log_path.read_text())
        script.path.unlink()
        self.assertFalse(self.manager.start(script, sys.executable, []))
        self.assertIn("no longer exists", state.current_log_path.read_text())
