"""Persistent global settings. Per-script state lives in models.py."""

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings


class AppSettings:
    def __init__(self, project_dir: Path, store: QSettings | None = None) -> None:
        self.project_dir = project_dir
        # Retain the existing registry/preferences location after the visible
        # application rename, so saved libraries, runtimes and geometry survive.
        self.store = store if store is not None else QSettings("SillyScripts", "Silly Scripts Launcher")

    @property
    def scripts_folder(self) -> Path | None:
        folders = self.scripts_folders
        return folders[0] if folders else None

    @scripts_folder.setter
    def scripts_folder(self, folder: Path) -> None:
        remaining = self.scripts_folders[1:]
        self.set_scripts_folders([folder, *remaining])

    @property
    def scripts_folders(self) -> list[Path]:
        saved = self.store.value("scripts_folders", None)
        if saved is None:
            saved = self.store.value("scripts_folder", str(self.project_dir / "scripts" / "default"))
        if isinstance(saved, (str, Path)):
            saved = [saved]
        folders = [Path(str(value)) for value in saved or []]
        # Follow bundled libraries relocated into scripts, preserving custom paths.
        for index, folder in enumerate(folders):
            for name in ("default", "test_scripts"):
                legacy = self.project_dir / name
                relocated = self.project_dir / "scripts" / name
                if folder.resolve() == legacy.resolve() and not legacy.exists() and relocated.is_dir():
                    folders[index] = relocated
        return folders

    def set_scripts_folders(self, folders: list[Path]) -> None:
        values = [str(folder) for folder in folders]
        self.store.setValue("scripts_folders", values)
        # Keep the former single-folder setting in step for older launcher builds.
        if values:
            self.store.setValue("scripts_folder", values[0])
        else:
            self.store.remove("scripts_folder")

    def executable(self, kind: str) -> str:
        return str(self.store.value(f"executables/{kind.lower()}", ""))

    def set_executable(self, kind: str, path: str) -> None:
        self.store.setValue(f"executables/{kind.lower()}", path)

    def geometry(self) -> QByteArray:
        return self.store.value("window/geometry", QByteArray())

    def save_geometry(self, geometry: QByteArray) -> None:
        self.store.setValue("window/geometry", geometry)
        self.store.sync()
