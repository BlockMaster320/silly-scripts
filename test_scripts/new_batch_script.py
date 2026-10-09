"""Discover matching .blend files, then open and save each in place.

The template performs no scene edits. Add edits in process_file(), between
opening and saving. Saving can still update file format/metadata and create
Blender backup files, according to your Blender version and preferences.
"""

import argparse
import os
import re
import stat
import sys
from pathlib import Path

"""Shared shot-list validation, also embedded in generated standalone scripts."""

import re


def parse_shot_selection(text: str) -> list[tuple[int, int]]:
    """Parse comma-separated nonnegative shot numbers and inclusive ranges.

    Keep ranges as pairs rather than expanding them into potentially huge lists.
    Leading zeros are accepted; descending ranges and empty entries are errors.
    """
    ranges: list[tuple[int, int]] = []
    for entry in text.split(","):
        match = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", entry)
        if not match:
            raise ValueError(f"Invalid shot entry {entry!r}. Use a list such as 1,4-8,12.")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) is not None else start
        if start > end:
            raise ValueError(f"Shot range {entry.strip()!r} starts after it ends.")
        ranges.append((start, end))
    return ranges


def format_shot_selection(ranges: list[tuple[int, int]]) -> list[str]:
    return [str(start) if start == end else f"{start}-{end}" for start, end in ranges]



def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-directory", required=True,
        help="Directory in which to discover .blend files.")
    parser.add_argument(
        "--exclude-folders", default="",
        help="Comma-separated folder names or paths relative to the target directory; excluded with their subfolders.",
    )
    parser.add_argument(
        "--include-shots", "--include_shots", action="append",
        help="Only filename number suffixes in these inclusive ranges. Use 1,4-8,12; flags may be repeated.",
    )
    parser.add_argument(
        "--exclude-shots", "--exclude_shots", action="append",
        help="Exclude filename number suffixes after inclusion filtering. Use 2,6-7; flags may be repeated.",
    )
    parser.add_argument(
        "--ignore-hidden-folders", action=argparse.BooleanOptionalAction,
        required=True, default=True, help="Ignore hidden folders and files (default: enabled).",
    )
    parser.add_argument(
        "--recursive", action=argparse.BooleanOptionalAction,
        required=True, default=True, help="Search subfolders recursively (default: enabled).",
    )

    return parser


def is_hidden(path: Path) -> bool:
    """Determines if a path is hidden, either by name or file attributes."""
    if path.name.startswith("."):
        return True
    attributes = getattr(path.stat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0))


def shot_ranges(values: list[str] | None) -> list[tuple[int, int]]:
    """Converts a list of shot selection strings into a list of numeric ranges."""
    return [interval for value in values or [] for interval in parse_shot_selection(value)]


def discover_blend_files(args: argparse.Namespace) -> list[Path]:
    """Applies folder and file selection restrictions, include ranges, then exclude ranges.

    Symlinked folders/files are skipped to keep discovery within the target.
    Files without a numeric suffix are allowed when no include filter is set.
    """
    root = Path(args.target_directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Target directory is unavailable: {root}")
    include = shot_ranges(args.include_shots)
    exclude = shot_ranges(args.exclude_shots)
    excluded_names: set[str] = set()
    excluded_paths: set[Path] = set()
    for entry in args.exclude_folders.split(","):
        text = entry.strip()
        if not text:
            continue
        folder = Path(text).expanduser()
        if not folder.is_absolute() and len(folder.parts) == 1 and text not in (".", ".."):
            excluded_names.add(os.path.normcase(text))
        else:
            excluded_paths.add((root / folder).resolve())

    def excluded_directory(directory: Path) -> bool:
        if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
            return True
        resolved = directory.resolve()
        if not resolved.is_relative_to(root):
            return True
        if any(resolved == path or resolved.is_relative_to(path) for path in excluded_paths):
            return True
        if os.path.normcase(directory.name) in excluded_names:
            return True
        return args.ignore_hidden_folders and is_hidden(directory)

    if excluded_directory(root):
        return []
    discovered: list[Path] = []

    def walk_error(error: OSError) -> None:
        raise error

    for folder, directories, filenames in os.walk(root, topdown=True, followlinks=False, onerror=walk_error):
        directory = Path(folder)
        directories[:] = sorted(
            [name for name in directories if not excluded_directory(directory / name)],
            key=str.casefold,
        ) if args.recursive else []
        for name in sorted(filenames, key=str.casefold):
            path = directory / name
            if path.suffix.lower() != ".blend" or path.is_symlink():
                continue
            if args.ignore_hidden_folders and is_hidden(path):
                continue
            match = re.search(r"([0-9]+)$", path.stem)
            shot = int(match.group(1)) if match else None
            if include and (shot is None or not any(start <= shot <= end for start, end in include)):
                continue
            if shot is not None and any(start <= shot <= end for start, end in exclude):
                continue
            discovered.append(path.resolve())

    return discovered


def process_file(path: Path) -> None:
    import bpy  # Import only at execution time, never during launcher inspection.

    print(f"[BATCH] Opening {path}", flush=True)
    result = bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=True)
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender did not open {path}: {result}")

    # ADD YOUR BLENDER CHANGES HERE.
    # The blank template intentionally performs no scene edits.

    result = bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender did not save {path}: {result}")
    print(f"[BATCH] Saved {path}", flush=True)


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = create_parser()
    args = parser.parse_args(argv)

    try:
        files = discover_blend_files(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        
    # Discover the entire list before opening any file. Blender loading can
    # replace scene data; all paths and selection state stay in Python locals.
    print(f"[BATCH] Found {len(files)} matching .blend file(s).", flush=True)
    failures = 0
    for index, path in enumerate(files, 1):
        print(f"[BATCH] Processing {index}/{len(files)}: {path}", flush=True)
        try:
            process_file(path)
        except Exception as exc:
            failures += 1
            print(f"[BATCH] ERROR {path}: {exc}", file=sys.stderr, flush=True)

    print(f"[BATCH] Done: {len(files) - failures} saved, {failures} failed.", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
