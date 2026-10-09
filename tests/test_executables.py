import os
import sys
import unittest
from pathlib import Path

from tests.support import APP, wait_until

from app.executable_discovery import ExecutableDiscovery, executable_candidates
from app.models import ExecutableInfo


class ExecutableTests(unittest.TestCase):
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
