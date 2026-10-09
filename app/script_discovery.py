"""Shallow, deterministic script discovery independent of Qt."""

from pathlib import Path


class ScriptDiscoveryError(Exception):
    pass


def discover_scripts(directory: Path) -> list[Path]:
    try:
        if not directory.is_dir():
            raise ScriptDiscoveryError(f"Scripts folder is unavailable: {directory}")
        return sorted(
            (
                entry.resolve()
                for entry in directory.iterdir()
                if entry.is_file()
                and entry.suffix.lower() == ".py"
                and entry.name.lower() != "__init__.py"
            ),
            key=lambda path: path.name.casefold(),
        )
    except OSError as exc:
        raise ScriptDiscoveryError(f"Cannot read scripts folder {directory}: {exc}") from exc


def discover_script_libraries(directories: list[Path]) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Discover direct child scripts from each library and report local failures."""
    discovered: list[tuple[Path, Path]] = []
    errors: list[str] = []
    seen: set[Path] = set()
    for directory in directories:
        library = directory.expanduser().resolve()
        try:
            scripts = discover_scripts(library)
        except ScriptDiscoveryError as exc:
            errors.append(str(exc))
            continue
        for script in scripts:
            if script not in seen:
                discovered.append((script, library))
                seen.add(script)
    return discovered, errors
