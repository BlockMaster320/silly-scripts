import os
import sys
import unittest
from pathlib import Path

from tests.support import APP, wait_until

from app.executable_discovery import ExecutableDiscovery, executable_candidates
from app.models import ExecutableInfo
from app.settings_panel import ExecutableSelector


class ExecutableTests(unittest.TestCase):
    def test_blender_selects_latest_version_regardless_of_probe_order(self) -> None:
        old = Path("blender-old.exe")
        latest = Path("blender-latest.exe")
        selector = ExecutableSelector("Blender", str(old))
        self.addCleanup(selector.deleteLater)
        selector.add_executable(ExecutableInfo(latest, "Blender"))
        selector.add_executable(ExecutableInfo(old, "Blender", "4.9.9"))
        selector.add_executable(ExecutableInfo(latest, "Blender", "4.10.2"))
        selector.add_executable(ExecutableInfo(Path("blender-middle.exe"), "Blender", "4.10.1"))
        selector.add_executable(ExecutableInfo(old, "Blender", "4.9.9"))
        self.assertEqual(selector.path(), str(latest))

    def test_blender_manual_choice_survives_later_version_probes(self) -> None:
        old = Path("blender-old.exe")
        latest = Path("blender-latest.exe")
        selector = ExecutableSelector("Blender", "")
        self.addCleanup(selector.deleteLater)
        selector.add_executable(ExecutableInfo(old, "Blender", "4.0.0"))
        selector.combo.activated.emit(0)
        selector.add_executable(ExecutableInfo(latest, "Blender", "5.0.0"))
        self.assertEqual(selector.path(), str(old))

    def test_python_keeps_saved_selection(self) -> None:
        saved = Path("python-saved.exe")
        selector = ExecutableSelector("Python", str(saved))
        self.addCleanup(selector.deleteLater)
        selector.add_executable(ExecutableInfo(Path("python-new.exe"), "Python", "3.14.0"))
        self.assertEqual(selector.path(), str(saved))

    def test_current_python_is_discovered(self) -> None:
        candidates = executable_candidates()
        self.assertTrue(any(info.kind == "Python" and info.path == Path(sys.executable).resolve() for info in candidates))

    def test_async_version_probe(self) -> None:
        discovery = ExecutableDiscovery()
        self.addCleanup(discovery.deleteLater)
        found: list[ExecutableInfo] = []
        discovery.found.connect(found.append)
        discovery._add(ExecutableInfo(Path(sys.executable), "Python"))
        wait_until(lambda: not discovery.is_busy)
        self.assertTrue(any(info.version and info.version.startswith(f"{sys.version_info.major}.{sys.version_info.minor}.") for info in found))
        discovery.shutdown()

    @unittest.skipUnless(os.name == "nt", "Windows launcher format")
    def test_windows_launcher_installations(self) -> None:
        discovery = ExecutableDiscovery()
        self.addCleanup(discovery.deleteLater)
        found: list[ExecutableInfo] = []
        discovery.found.connect(found.append)
        discovery._launcher_result(f" -V:3.12 *        {sys.executable}\n")
        wait_until(lambda: not discovery.is_busy)
        self.assertTrue(any(info.path == Path(sys.executable).resolve() for info in found))
        discovery.shutdown()
