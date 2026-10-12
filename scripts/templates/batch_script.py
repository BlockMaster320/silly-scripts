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

from app.shot_selection import parse_shot_selection

INFO_PREFIX = "[SCRIPT]"

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target-directory", nargs="+", required=True,
        help="Directories in which to discover .blend files. Use + to select more.")
    parser.add_argument(
        "--exclude-folders", action="append",
        help="Folders excluded with their subfolders. Use + to select more; flags may be repeated.",
    )
    parser.add_argument(
        "--include-shots", action="append",
        help="Only filename number suffixes in these inclusive ranges. Use 1,4-8,12; flags may be repeated.",
    )
    parser.add_argument(
        "--exclude-shots", action="append",
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
    parser.add_argument(
        "--purge-unused-data", action="store_true", default=False,
        help="Recursively purge unused local data-blocks before saving; linked data is kept (default: disabled).",
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


def _discover_in_directory(args: argparse.Namespace, target_directory: str) -> list[Path]:
    """Applies folder and file selection restrictions, include ranges, then exclude ranges.

    Symlinked folders/files are skipped to keep discovery within the target.
    Files without a numeric suffix are allowed when no include filter is set.
    """
    root = Path(target_directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Target directory is unavailable: {root}")
    
    include = shot_ranges(args.include_shots)
    exclude = shot_ranges(args.exclude_shots)
    excluded_names: set[str] = set()
    excluded_paths: set[Path] = set()
    folder_values = args.exclude_folders or []

    if isinstance(folder_values, str):
        folder_values = [folder_values]

    folder_entries: list[str] = []
    for value in folder_values:
        # Native pickers can select paths containing commas. Keep existing
        # folders intact while accepting legacy comma-separated exclusions
        if (root / Path(value).expanduser()).is_dir():
            folder_entries.append(value)
        else:
            folder_entries.extend(value.split(","))
            
    for entry in folder_entries:
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


def discover_blend_files(args: argparse.Namespace) -> list[Path]:
    """
    Validates and discovers all target folders before opening any Blender file.
    Overlapping search roots are deduplicated so each file is processed once.
    """
    targets = args.target_directory
    if isinstance(targets, str):
        targets = [targets]
    return list(dict.fromkeys(
        path for target in targets for path in _discover_in_directory(args, target)
    ))


def count_datablocks() -> int:
    """Count all bpy.data collections before or after an orphan purge."""
    import bpy

    total = 0
    for collection_name in dir(bpy.data):
        if collection_name.startswith("_"):
            continue
        data_collection = getattr(bpy.data, collection_name)
        if not isinstance(data_collection, bpy.types.bpy_prop_collection):
            continue
        total += len(data_collection)
    return total


def purge_unused_data(keep_linked: bool) -> int:
    """Recursively purge orphaned data-blocks; return the number removed."""
    import bpy

    before = count_datablocks()
    bpy.data.orphans_purge(
        do_local_ids=True,
        do_linked_ids=not keep_linked,
        do_recursive=True,
    )
    return before - count_datablocks()


def process_file(path: Path, purge_data: bool = False) -> None:
    import bpy  # import bpy at execution time if possible

    # Open the .blend file
    print(f"{INFO_PREFIX} Opening {path}", flush=True)
    result = bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=True)
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender did not open {path}: {result}")

    # == ADD YOUR BLENDER CODE HERE ==

    # Purge unused data-blocks if requested
    if purge_data:
        # Keep linked IDs by default; change to False if the job should purge them too.
        removed = purge_unused_data(keep_linked=True)
        print(f"{INFO_PREFIX} Purged {removed} unused data-block(s).", flush=True)

    # Save the .blend file
    result = bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender did not save {path}: {result}")
    print(f"{INFO_PREFIX} File saved.", flush=True)


def main() -> None:
    # Parse script arguments
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = create_parser()
    args = parser.parse_args(argv)

    # Discover all .blend files in the target directories
    try:
        files = discover_blend_files(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        
    # Process the discovered files
    print(f"{INFO_PREFIX} Found {len(files)} matching .blend file(s).", flush=True)
    failures = 0
    for index, path in enumerate(files, 1):
        print(f"{INFO_PREFIX} Processing {index}/{len(files)}: {path}", flush=True)
        try:
            process_file(path, purge_data=args.purge_unused_data)
        except Exception as exc:
            failures += 1
            print(f"{INFO_PREFIX}[ERROR] {path}: {exc}", file=sys.stderr, flush=True)

    print(f"{INFO_PREFIX} Done: {len(files) - failures} saved, {failures} failed.", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
