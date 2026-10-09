"""Launcher-side discovery and metadata for running ordinary scripts in batches."""

from __future__ import annotations

import runpy
from dataclasses import dataclass
from pathlib import Path


BATCH_TEMPLATE = Path(__file__).parent / "templates" / "batch_script.py"
BATCH_RUNNER = Path(__file__).parent / "templates" / "batch_runner.py"


@dataclass(frozen=True)
class BatchSelection:
    files: list[Path]
    purge_unused_data: bool


class BatchSupport:
    """Reuse the standalone batch template's exact parser and file filters."""

    def __init__(self) -> None:
        self.template_info: dict[str, object] = runpy.run_path(
            str(BATCH_TEMPLATE), run_name="_launcher_batch_template"
        )

    def discover(self, arguments: list[str]) -> BatchSelection:
        parser_factory = self.template_info["create_parser"]
        discover_files = self.template_info["discover_blend_files"]
        if not callable(parser_factory) or not callable(discover_files):
            raise RuntimeError("The batch selection template is not available.")
        parser = parser_factory()
        try:
            parsed = parser.parse_args(arguments)
        except SystemExit as exc:
            raise ValueError("The batch file selection options are invalid.") from exc
        files = discover_files(parsed)
        return BatchSelection(files, bool(parsed.purge_unused_data))
