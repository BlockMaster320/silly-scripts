"""Find installations locally, then query versions using asynchronous QProcess."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .models import ExecutableInfo


def executable_candidates() -> list[ExecutableInfo]:
    found: dict[tuple[str, str], ExecutableInfo] = {}

    def add(path: str | Path | None, kind: str, version: str | None = None) -> None:
        if path:
            candidate = Path(path).expanduser()
            if candidate.is_file():
                candidate = candidate.resolve()
                found[(kind, os.path.normcase(str(candidate)))] = ExecutableInfo(candidate, kind, version)

    current = Path(sys.executable)
    if current.name.lower() == "pythonw.exe" and current.with_name("python.exe").exists():
        current = current.with_name("python.exe")
    add(current, "Python", ".".join(map(str, sys.version_info[:3])))
    for name in ["python", "python3", *(f"python3.{minor}" for minor in range(8, 16))]:
        path = shutil.which(name)
        # Bare Windows App Execution Aliases can open the Store, not Python.
        if path and Path(path).parent.name.lower() != "windowsapps":
            add(path, "Python")
    add(shutil.which("blender"), "Blender")
    if os.name == "nt":
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            root = Path(os.environ.get(variable, "C:/Program Files")) / "Blender Foundation"
            try:
                for path in root.glob("Blender*/blender.exe"):
                    add(path, "Blender")
            except OSError:
                pass
    elif sys.platform == "darwin":
        add("/Applications/Blender.app/Contents/MacOS/Blender", "Blender")
    return list(found.values())


class ExecutableDiscovery(QObject):
    found = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._probes: set[QProcess] = set()
        self._seen: set[tuple[str, str]] = set()
        self._closing = False

    def discover(self) -> None:
        if self._closing:
            return
        for candidate in executable_candidates():
            self._add(candidate)
        if os.name == "nt" and (launcher := shutil.which("py")):
            self._probe(launcher, ["-0p"], self._launcher_result)

    def _add(self, candidate: ExecutableInfo) -> None:
        key = (candidate.kind, os.path.normcase(str(candidate.path)))
        if key in self._seen:
            return
        self._seen.add(key)
        self.found.emit(candidate)
        if candidate.version is None:
            self._probe(str(candidate.path), ["--version"], lambda text: self._version_result(candidate, text))

    def _launcher_result(self, output: str) -> None:
        for line in output.splitlines():
            match = re.match(r"\s*-\S+\s+\*?\s*(.+?\.exe)\s*$", line, re.IGNORECASE)
            if match:
                path = Path(match.group(1).strip().strip('"'))
                if path.is_file():
                    self._add(ExecutableInfo(path.resolve(), "Python"))

    def _version_result(self, candidate: ExecutableInfo, output: str) -> None:
        match = re.search(rf"{candidate.kind}\s+(\d+\.\d+(?:\.\d+)?)", output, re.IGNORECASE)
        if match:
            self.found.emit(ExecutableInfo(candidate.path, candidate.kind, match.group(1)))

    def _probe(self, executable: str, arguments: list[str], callback: Callable[[str], None]) -> None:
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        timer = QTimer(process)
        timer.setSingleShot(True)
        self._probes.add(process)

        def finish() -> None:
            if process not in self._probes:
                return
            timer.stop()
            self._probes.remove(process)
            output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
            if not self._closing:
                callback(output)
            process.deleteLater()

        process.finished.connect(finish)
        process.errorOccurred.connect(
            lambda error: finish() if error == QProcess.ProcessError.FailedToStart else None
        )
        timer.timeout.connect(process.kill)
        process.start(executable, arguments)
        timer.start(4000)

    def shutdown(self) -> None:
        self._closing = True
        for process in tuple(self._probes):
            process.kill()

    @property
    def is_busy(self) -> bool:
        return bool(self._probes)
