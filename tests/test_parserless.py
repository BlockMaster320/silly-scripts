"""Parserless scripts retain inspection, single execution, and batch support."""

import contextlib
import io
import json
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.support import APP, wait_until
from app.arguments import build_process_arguments
from app.models import ScriptRuntimeState
from app.process_manager import ProcessManager
from app.script_inspector import ScriptInspector

PROJECT = Path(__file__).resolve().parents[1]


class ParserlessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.path = self.root / "main only.py"

    def write_script(self, guarded: bool) -> None:
        source = '\"\"\"Parserless description.\"\"\"\ndef main():\n    print("[SCRIPT] called once", flush=True)\n'
        if guarded:
            source += 'if __name__ == "__main__":\n    main()\n'
        self.path.write_text(source, encoding="utf-8")

    def test_inspection_never_calls_main_and_invalid_factory_still_errors(self) -> None:
        self.path.write_text('"""Description."""\nimport bpy\ndef main():\n    raise RuntimeError("must not run during inspection")\n')
        info = ScriptInspector().inspect(self.path)
        self.assertIsNone(info.inspection_error)
        self.assertFalse(info.has_parser)
        self.assertEqual(info.parameters, [])
        self.assertEqual(info.description, "Description.")
        self.path.write_text('def main():\n    pass\ncreate_parser = None\n')
        self.assertIn("callable", ScriptInspector().inspect(self.path).inspection_error)

    def test_single_python_runs_main_once_with_or_without_guard(self) -> None:
        manager = ProcessManager(self.root / "logs")
        try:
            for guarded in (False, True):
                with self.subTest(guarded=guarded):
                    self.write_script(guarded)
                    info = ScriptInspector().inspect(self.path)
                    state = manager.state_for(self.path)
                    state.runtime = "Python"
                    self.assertTrue(manager.start(info, sys.executable, []))
                    wait_until(lambda: not state.is_running)
                    log = state.current_log_path.read_text(encoding="utf-8")
                    self.assertEqual(log.count("[SCRIPT] called once"), 1)
                    self.assertIn("Exit code: 0", log)
        finally:
            manager.stop_all()
            wait_until(lambda: not manager.has_running)
            manager.deleteLater()
            APP.processEvents()

    def test_blender_command_uses_main_helper_and_batch_calls_main_once_per_file(self) -> None:
        self.write_script(True)
        arguments = build_process_arguments(self.path, [], ScriptRuntimeState(), call_main=True)
        self.assertEqual(arguments[-2:], ["--", str(self.path)])
        self.assertIn(str(PROJECT / "scripts/templates/main_runner.py"), arguments)
        manifest = self.root / "batch.json"
        manifest.write_text(json.dumps({
            "script_path": str(self.path), "script_arguments": [],
            "files": [str(self.root / "one.blend"), str(self.root / "two.blend")],
        }))
        wm = SimpleNamespace(open_mainfile=Mock(return_value={"FINISHED"}), save_as_mainfile=Mock(return_value={"FINISHED"}))
        original_path = sys.path[:]
        try:
            with patch.dict(sys.modules, {"bpy": SimpleNamespace(ops=SimpleNamespace(wm=wm))}), patch.object(sys, "argv", ["batch_runner.py"]):
                runner = runpy.run_path(str(PROJECT / "scripts/templates/batch_runner.py"))
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(runner["run_batch"](manifest), 0)
                self.assertEqual(output.getvalue().count("[SCRIPT] called once"), 2)
                self.assertEqual(wm.open_mainfile.call_count, 2)
                self.assertEqual(wm.save_as_mainfile.call_count, 2)
        finally:
            sys.path[:] = original_path
