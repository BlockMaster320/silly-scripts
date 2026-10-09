"""Independent asynchronous script runs, unfiltered disk logs, and view buffers."""

from __future__ import annotations

import codecs
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .arguments import build_process_arguments
from .batch_support import BATCH_RUNNER
from .models import ScriptInfo, ScriptRuntimeState


@dataclass
class _Run:
    process: QProcess
    log: BinaryIO
    stop_timer: QTimer
    manifest_path: Path | None = None
    filter_text: str = ""
    filter_log_enabled: bool = False
    decoders: dict[str, codecs.IncrementalDecoder] = field(default_factory=dict)
    pending: dict[str, str] = field(default_factory=lambda: {"stdout": "", "stderr": ""})
    log_pending: dict[str, str] = field(default_factory=lambda: {"stdout": "", "stderr": ""})
    finalized: bool = False
    log_failed: bool = False


class ProcessManager(QObject):
    state_changed = Signal(object)  # Path
    output_received = Signal(object, str)  # Path, visible line
    view_cleared = Signal(object)
    execution_error = Signal(object, str)

    def __init__(self, log_root: Path, parent: QObject | None = None, stop_timeout_ms: int = 3000) -> None:
        super().__init__(parent)
        self.log_root = log_root
        self.stop_timeout_ms = stop_timeout_ms
        self.states: dict[Path, ScriptRuntimeState] = {}
        self._runs: dict[Path, _Run] = {}

    def state_for(self, path: Path) -> ScriptRuntimeState:
        return self.states.setdefault(path, ScriptRuntimeState())

    @property
    def has_running(self) -> bool:
        return any(state.is_running for state in self.states.values())

    def start(
        self,
        script: ScriptInfo,
        executable: str,
        script_arguments: list[str],
        *,
        batch_payload: dict[str, object] | None = None,
    ) -> bool:
        path = script.path
        state = self.state_for(path)
        if state.is_running:
            self.execution_error.emit(path, "This script is already running.")
            return False
        if script.inspection_error:
            self.execution_error.emit(path, script.inspection_error)
            return False
        launch_path = path
        manifest_path: Path | None = None
        arguments: list[str] = []
        try:
            folder_name = re.sub(r"[^\w.-]", "_", path.stem).strip(". ") or "script"
            if folder_name.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
                folder_name = f"script_{folder_name}"
            folder = self.log_root / folder_name[:100]
            folder.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
            log_path = folder / f"{timestamp}_{uuid4().hex[:8]}.log"
            log = log_path.open("xb")
            if batch_payload is not None:
                manifest_path = log_path.with_suffix(".batch.json")
                with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
                    json.dump(batch_payload, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                launch_path = BATCH_RUNNER
                arguments = build_process_arguments(
                    launch_path, ["--manifest", str(manifest_path)], state
                )
            else:
                arguments = build_process_arguments(path, script_arguments, state)
        except OSError as exc:
            if "log" in locals():
                log.close()
            if "log_path" in locals():
                log_path.unlink(missing_ok=True)
            if manifest_path:
                manifest_path.unlink(missing_ok=True)
            self.execution_error.emit(path, f"Cannot create a run log: {exc}")
            return False
        except ValueError as exc:
            log.close()
            log_path.unlink(missing_ok=True)
            if manifest_path:
                manifest_path.unlink(missing_ok=True)
            self.execution_error.emit(path, str(exc))
            return False

        process = QProcess(self)
        timer = QTimer(process)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._kill(path, process))
        run = _Run(
            process, log, timer, manifest_path=manifest_path,
            filter_text=state.output_filter,
            filter_log_enabled=state.filter_log_enabled,
        )
        run.decoders = {channel: codecs.getincrementaldecoder("utf-8")("replace") for channel in ("stdout", "stderr")}
        self._runs[path] = run
        state.process = process
        state.current_log_path = log_path
        state.is_running = True
        state.status = "Starting…"
        self.clear_view(path)
        metadata = (
            f"Script: {path}\nRuntime: {state.runtime}\nExecutable: {executable}\n"
            f"Started: {datetime.now().astimezone().isoformat()}\n"
            f"Working directory: {path.parent}\n"
            f"Arguments: {json.dumps(arguments, ensure_ascii=False)}\n"
        )
        if batch_payload is not None:
            metadata += (
                "Mode: Batch .blend files\n"
                f"Batch target script: {batch_payload.get('script_path')}\n"
                f"Batch files: {len(batch_payload.get('files', []))}\n"
                f"Script arguments: {json.dumps(batch_payload.get('script_arguments', []), ensure_ascii=False)}\n"
                f"Batch selection arguments: {json.dumps(batch_payload.get('batch_selection_arguments', []), ensure_ascii=False)}\n"
                f"Manifest: {manifest_path}\n"
            )
        metadata += "-" * 60 + "\n"
        self._write(path, metadata.encode("utf-8"))
        self._display(path, f"[Launcher] Log: {log_path}", force=True)
        self.state_changed.emit(path)

        process.readyReadStandardOutput.connect(lambda: self._read(path, "stdout"))
        process.readyReadStandardError.connect(lambda: self._read(path, "stderr"))
        process.started.connect(lambda: self._started(path))
        process.finished.connect(lambda code, status: self._finish(path, code, status.name))
        process.errorOccurred.connect(lambda error: self._error(path, error))
        process.setWorkingDirectory(str(path.parent))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.setStandardInputFile(QProcess.nullDevice())
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("PYTHONIOENCODING", "utf-8")
        process.setProcessEnvironment(environment)

        if run.log_failed:
            self._finish(path, None, "LogError")
            return False
        if not executable.strip() or not Path(executable).is_file():
            self._notice(path, f"Invalid {state.runtime} executable. Select an executable file in Settings.", error=True)
            self._finish(path, None, "FailedToStart")
            return False
        if not path.is_file():
            self._notice(path, f"The script no longer exists: {path}", error=True)
            self._finish(path, None, "FailedToStart")
            return False
        if not launch_path.is_file():
            self._notice(path, f"The batch runner is unavailable: {launch_path}", error=True)
            self._finish(path, None, "FailedToStart")
            return False
        process.start(executable, arguments)
        return True

    def _started(self, path: Path) -> None:
        state = self.state_for(path)
        # Stop may be clicked while QProcess is still starting.
        stopping = state.status == "Stopping…"
        state.status = "Stopping…" if stopping else "Running"
        self._notice(path, "Process started.")
        self.state_changed.emit(path)
        if stopping and state.process:
            state.process.terminate()

    def _write(self, path: Path, data: bytes) -> None:
        run = self._runs[path]
        if run.log_failed:
            return
        try:
            run.log.write(data)
            run.log.flush()
        except OSError as exc:
            run.log_failed = True
            message = f"Cannot write log; stopping the process: {exc}"
            self._display(path, f"[Launcher] {message}", force=True)
            self.execution_error.emit(path, message)
            self.stop(path)

    def _read(self, path: Path, channel: str) -> None:
        run = self._runs.get(path)
        if not run or run.finalized:
            return
        reader = run.process.readAllStandardOutput if channel == "stdout" else run.process.readAllStandardError
        data = bytes(reader())
        if data:
            text = run.decoders[channel].decode(data)
            if run.filter_log_enabled and run.filter_text:
                self._consume_log(path, channel, text)
            else:
                # Preserve original bytes whenever saved-log filtering is off.
                self._write(path, data)
            self._consume(path, channel, text)

    def _consume_log(self, path: Path, channel: str, text: str, final: bool = False) -> None:
        """Write complete matching lines to disk when saved-log filtering is on."""
        run = self._runs[path]
        lines = (run.log_pending[channel] + text).split("\n")
        run.log_pending[channel] = lines.pop()
        for line in lines:
            normalized = line.rstrip("\r")
            if run.filter_text.casefold() in normalized.casefold():
                self._write(path, (normalized + "\n").encode("utf-8"))
        if final and run.log_pending[channel]:
            line = run.log_pending[channel].rstrip("\r")
            if run.filter_text.casefold() in line.casefold():
                self._write(path, (line + "\n").encode("utf-8"))
            run.log_pending[channel] = ""

    def _consume(self, path: Path, channel: str, text: str, final: bool = False) -> None:
        run = self._runs[path]
        pending = run.pending[channel] + text
        lines = pending.split("\n")
        run.pending[channel] = lines.pop()
        for line in lines:
            self._display(path, line.rstrip("\r"), channel=channel)
        if final and run.pending[channel]:
            self._display(path, run.pending[channel].rstrip("\r"), channel=channel)
            run.pending[channel] = ""

    def _display(self, path: Path, line: str, channel: str = "stdout", force: bool = False) -> None:
        state = self.state_for(path)
        if not force and state.filter_enabled and state.output_filter:
            if state.output_filter.lower() not in line.lower():
                return
        # The disk log remains complete; avoid giant individual GUI blocks.
        if len(line) > 32_768:
            line = line[:32_768] + " … [view line truncated; see log file]"
        if channel == "stderr":
            line = f"[stderr] {line}"
        state.visible_log.append(line)
        self.output_received.emit(path, line)

    def _notice(self, path: Path, message: str, error: bool = False) -> None:
        self._write(path, f"\n[Launcher] {message}\n".encode("utf-8"))
        self._display(path, f"[Launcher] {message}", force=True)
        if error:
            self.execution_error.emit(path, message)

    def _error(self, path: Path, error: QProcess.ProcessError) -> None:
        run = self._runs.get(path)
        if not run or run.finalized:
            return
        self._notice(path, f"{error.name}: {run.process.errorString()}", error=True)
        if error == QProcess.ProcessError.FailedToStart:
            self._finish(path, None, "FailedToStart")

    def _finish(self, path: Path, exit_code: int | None, exit_status: str) -> None:
        run = self._runs.get(path)
        if not run or run.finalized:
            return
        for channel in ("stdout", "stderr"):
            self._read(path, channel)
            tail = run.decoders[channel].decode(b"", final=True)
            if run.filter_log_enabled and run.filter_text:
                self._consume_log(path, channel, tail, final=True)
            self._consume(path, channel, tail, final=True)
        run.stop_timer.stop()
        run.finalized = True
        footer = (
            "\n" + "-" * 60 + "\n"
            f"Finished: {datetime.now().astimezone().isoformat()}\n"
            f"Exit code: {exit_code if exit_code is not None else 'not available'}\n"
            f"Exit status: {exit_status}\n"
        )
        self._write(path, footer.encode("utf-8"))
        try:
            run.log.close()
        except OSError:
            pass
        if run.manifest_path:
            try:
                run.manifest_path.unlink(missing_ok=True)
            except OSError:
                pass
        state = self.state_for(path)
        state.is_running = False
        state.process = None
        state.status = f"Finished (exit {exit_code}, {exit_status})" if exit_code is not None else exit_status
        self._display(path, f"[Launcher] {state.status}", force=True)
        del self._runs[path]
        run.process.deleteLater()
        self.state_changed.emit(path)

    def stop(self, path: Path) -> None:
        state = self.state_for(path)
        run = self._runs.get(path)
        if not run or run.finalized:
            return
        if state.status == "Stopping…":
            self._kill(path, run.process)
            return
        state.status = "Stopping…"
        run.process.terminate()
        run.stop_timer.start(self.stop_timeout_ms)
        self.state_changed.emit(path)

    def _kill(self, path: Path, process: QProcess) -> None:
        run = self._runs.get(path)
        if run and run.process is process and not run.finalized:
            self._notice(path, "Force stopping the process.")
            process.kill()

    def stop_all(self) -> None:
        for path, state in tuple(self.states.items()):
            if state.is_running:
                self.stop(path)

    def clear_view(self, path: Path) -> None:
        self.state_for(path).visible_log.clear()
        self.view_cleared.emit(path)
