"""
Blender asset collection rename / Library Override migration.

Expected asset layout:

    ASSET_ROOT/
        Asset_A/
            Asset_A.blend

        Asset_B/
            Asset_B.blend


Mapping file:

    Asset_A / New_Asset_A
    Asset_B / New_Asset_B


Migration:

    PHASE 1
        Asset_A.blend:
            Asset_A     -> New_Asset_A   (original collection)
            duplicate root -> Asset_A    (temporary compatibility collection)

    PHASE 2
        Every .blend under PROJECT_ROOT:

            linked:
                Asset_A.blend / Asset_A

            becomes:
                New_Asset_A.blend / New_Asset_A

        Existing local Library Overrides are kept. Their source reference
        is remapped using ID.user_remap().

    PHASE 3
        Asset_A.blend:
            remove temporary Asset_A collection

        filesystem:
            Asset_A/Asset_A.blend
                ->
            New_Asset_A/New_Asset_A.blend

Usage:

    blender --background --python rename_assets_batch.py -- `
        --asset-dir "X:/project/assets" `
        --target-directory "X:/project/shots" `
        --mapping "X:/project/rename_mapping.txt" `
        --recursive --purge-unused-data

`--project-dir` remains an alias for `--target-directory`. Discovery supports
multiple roots, excluded folders, shot-number ranges, hidden-folder control, and
recursive scanning. `--relink-only` skips asset preparation and filesystem
renaming; `--preserve-overrides` avoids override maintenance. Optional
`--purge-unused-data` purges local orphan data-blocks and saves each selected
project file; linked data-blocks are retained.
"""



from __future__ import annotations

import argparse
import os
import re
import stat
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import bpy


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class AssetRename:
    old_name: str
    new_name: str

    old_blend_path: Path
    old_folder_path: Path

    new_blend_path: Path
    new_folder_path: Path


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

INFO_PREFIX = "[SCRIPT]"

def log(message: str) -> None:
    print(f"{INFO_PREFIX} {message}", flush=True)


def warning(message: str) -> None:
    print(f"{INFO_PREFIX}[WARNING] {message}", flush=True)


def error(message: str) -> None:
    print(f"{INFO_PREFIX}[ERROR] {message}", flush=True)


def purge_unused_local_data() -> int:
    before = sum(
        len(data_collection)
        for collection_name in dir(bpy.data)
        if not collection_name.startswith("_")
        for data_collection in [getattr(bpy.data, collection_name)]
        if isinstance(data_collection, bpy.types.bpy_prop_collection)
    )
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
    after = sum(
        len(data_collection)
        for collection_name in dir(bpy.data)
        if not collection_name.startswith("_")
        for data_collection in [getattr(bpy.data, collection_name)]
        if isinstance(data_collection, bpy.types.bpy_prop_collection)
    )
    return before - after


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rename linked Blender asset collections and migrate Library Overrides."
    )

    parser.add_argument(
        "--asset-dir",
        required=True,
        type=Path,
        help="Root directory containing the original asset folders.",
    )

    parser.add_argument(
        "--project-dir", "--target-directory",
        dest="target_directory", nargs="+", required=True, type=Path,
        help="Directories recursively containing project .blend files.",
    )

    parser.add_argument("--exclude-folders", action="append", help="Folders excluded with their subfolders; repeatable.")
    parser.add_argument("--include-shots", "--include_shots", action="append", help="Include filename number suffixes/ranges, e.g. 1,4-8; repeatable.")
    parser.add_argument("--exclude-shots", "--exclude_shots", action="append", help="Exclude filename number suffixes/ranges, e.g. 2,6-7; repeatable.")
    parser.add_argument("--ignore-hidden-folders", action=argparse.BooleanOptionalAction, default=True, help="Ignore hidden folders and files (default: enabled).")
    parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True, help="Search subfolders recursively (default: enabled).")
    parser.add_argument("--purge-unused-data", action="store_true", help="Purge unused local data-blocks and save each selected project file (default: disabled).")

    parser.add_argument(
        "--mapping",
        required=True,
        type=Path,
        help="Text file containing lines: old_name / new_name",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print planned operations without changing anything.",
    )

    parser.add_argument(
        "--relink-only",
        action="store_true",
        help="Relink project files to already-renamed assets on disk (skips asset prep and filesystem renames).",
    )

    parser.add_argument(
        "--preserve-overrides",
        action="store_true",
        help="Avoid override maintenance and orphan purging during project migration. Enabled automatically by --relink-only.",
    )

    return parser


def shot_ranges(values: list[str] | None) -> list[tuple[int, int]]:
    ranges = []
    for value in values or []:
        for entry in value.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split("-", maxsplit=1)
            start = int(parts[0])
            end = int(parts[1]) if len(parts) == 2 else start
            if end < start:
                raise ValueError(f"Invalid descending shot range: {entry}")
            ranges.append((start, end))
    return ranges


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def normalized_path(path: Path | str) -> Path:
    return Path(os.path.normpath(os.path.abspath(os.fspath(path))))


def same_path(a: Path | str, b: Path | str) -> bool:
    """
    Windows-safe path comparison, resolving UNC/drive-letter aliases and case.
    """
    try:
        res_a = Path(a).resolve()
        res_b = Path(b).resolve()
        if os.path.normcase(os.path.normpath(str(res_a))) == os.path.normcase(os.path.normpath(str(res_b))):
            return True
    except Exception:
        pass

    return os.path.normcase(
        os.path.normpath(str(normalized_path(a)))
    ) == os.path.normcase(
        os.path.normpath(str(normalized_path(b)))
    )


def same_name(a: str, b: str) -> bool:
    """Case-insensitive name comparison safe for Windows-style file systems."""
    return os.path.normcase(a) == os.path.normcase(b)


def blender_library_absolute_path(library: bpy.types.Library) -> Path:
    """
    Convert Blender's library path, including // relative paths,
    into an absolute filesystem path.

    The path is resolved relative to the currently open .blend.
    """

    return normalized_path(
        bpy.path.abspath(library.filepath)
    )


def make_blender_path_for_current_file(
    path: Path,
    prefer_relative: bool,
) -> str:
    """
    Convert an absolute filesystem path back into the representation
    stored in the .blend.

    If the original library used a // relative path, preserve that style.
    """

    path = normalized_path(path)

    if prefer_relative:
        return bpy.path.relpath(str(path))

    return str(path)


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def load_mapping(path: Path) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []

    with path.open("r", encoding="utf-8-sig") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            parts = line.split("/")

            if len(parts) != 2:
                raise ValueError(
                    f"Invalid mapping on line {line_number}: {raw_line!r}\n"
                    f"Expected: old_name / new_name"
                )

            old_name = parts[0].strip()
            new_name = parts[1].strip()

            if not old_name or not new_name:
                raise ValueError(
                    f"Empty old/new name on line {line_number}."
                )

            if old_name == new_name:
                warning(
                    f"Ignoring mapping where old and new names are identical: "
                    f"{old_name}"
                )
                continue

            result.append((old_name, new_name))

    if not result:
        raise RuntimeError("Mapping file contains no rename operations.")

    old_names = [x[0] for x in result]
    new_names = [x[1] for x in result]

    if len(set(old_names)) != len(old_names):
        raise RuntimeError("Mapping contains duplicate old names.")

    if len(set(new_names)) != len(new_names):
        raise RuntimeError("Mapping contains duplicate new names.")

    return result


# ---------------------------------------------------------------------------
# Asset discovery
# ---------------------------------------------------------------------------


def find_asset_file(asset_root: Path, asset_name: str) -> Path:
    """
    Search recursively for:

        .../asset_name/asset_name.blend

    Exactly one must exist.
    """

    candidates: list[Path] = []
    seen: set[str] = set()

    discovery_args = argparse.Namespace(
        target_directory=[asset_root],
        exclude_folders=None,
        include_shots=None,
        exclude_shots=None,
        ignore_hidden_folders=True,
        recursive=True,
    )

    for path in discover_blend_files(discovery_args):
        if not path.is_file():
            continue

        if not same_name(path.stem, asset_name):
            continue

        if not same_name(path.parent.name, asset_name):
            continue

        normalized = normalized_path(path)
        key = os.path.normcase(str(normalized))

        if key in seen:
            continue

        seen.add(key)
        candidates.append(normalized)

    if not candidates:
        raise FileNotFoundError(
            f"Could not find asset:\n"
            f"    {asset_name}/{asset_name}.blend\n"
            f"under:\n"
            f"    {asset_root}"
        )

    if len(candidates) > 1:
        paths = "\n".join(f"    {p}" for p in candidates)

        raise RuntimeError(
            f"Multiple asset files found for '{asset_name}':\n{paths}"
        )

    return candidates[0]


def build_asset_records(
    asset_root: Path,
    mapping: list[tuple[str, str]],
    relink_only: bool = False,
) -> list[AssetRename]:

    records: list[AssetRename] = []

    for old_name, new_name in mapping:
        if relink_only:
            try:
                new_blend = find_asset_file(asset_root, new_name)
                new_folder = new_blend.parent
                old_folder = new_folder.parent / old_name
                old_blend = old_folder / f"{old_name}.blend"
            except FileNotFoundError:
                old_blend = find_asset_file(asset_root, old_name)
                old_folder = old_blend.parent
                new_folder = old_folder.parent / new_name
                new_blend = new_folder / f"{new_name}.blend"
        else:
            old_blend = find_asset_file(asset_root, old_name)
            old_folder = old_blend.parent

            new_folder = old_folder.parent / new_name
            new_blend = new_folder / f"{new_name}.blend"

        records.append(
            AssetRename(
                old_name=old_name,
                new_name=new_name,

                old_blend_path=normalized_path(old_blend),
                old_folder_path=normalized_path(old_folder),

                new_blend_path=normalized_path(new_blend),
                new_folder_path=normalized_path(new_folder),
            )
        )

    return records


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_filesystem_renames(records: list[AssetRename]) -> None:
    """
    Catch obvious collisions before touching any .blend.
    """

    old_folders = {
        os.path.normcase(str(x.old_folder_path))
        for x in records
    }

    for record in records:
        if record.new_folder_path.exists():
            key = os.path.normcase(str(record.new_folder_path))

            # A -> B and B -> C is allowed.
            # Temporary folder names are used during the final rename.
            if key not in old_folders:
                raise RuntimeError(
                    f"Target asset folder already exists:\n"
                    f"    {record.new_folder_path}"
                )

        # Check collision inside the existing old folder.
        future_filename_in_old_folder = (
            record.old_folder_path / f"{record.new_name}.blend"
        )

        if (
            future_filename_in_old_folder.exists()
            and not same_path(
                future_filename_in_old_folder,
                record.old_blend_path,
            )
        ):
            raise RuntimeError(
                f"Cannot rename asset file because this already exists:\n"
                f"    {future_filename_in_old_folder}"
            )


# ---------------------------------------------------------------------------
# Blender helpers
# ---------------------------------------------------------------------------


def open_blend(path: Path) -> None:
    log(f"Opening: {path}")

    bpy.ops.wm.open_mainfile(
        filepath=str(path),
        load_ui=True,
    )


def save_current_blend() -> None:
    log(f"Saving: {bpy.data.filepath}")

    bpy.ops.wm.save_as_mainfile(
        filepath=bpy.data.filepath,
    )


def get_local_collection(name: str) -> bpy.types.Collection | None:
    """
    Find specifically a LOCAL collection.

    bpy.data.collections.get(name) can be ambiguous when linked datablocks
    with the same name are present.
    """

    for collection in bpy.data.collections:
        if (
            same_name(collection.name, name)
            and collection.library is None
        ):
            return collection

    return None


# ---------------------------------------------------------------------------
# PHASE 1
# Prepare asset files
# ---------------------------------------------------------------------------


def prepare_asset(
    record: AssetRename,
    dry_run: bool,
) -> None:

    log("")
    log(
        f"PREPARE ASSET: "
        f"{record.old_name} -> {record.new_name}"
    )

    open_blend(record.old_blend_path)

    original = get_local_collection(record.old_name)
    existing_new = get_local_collection(record.new_name)

    # Check if asset is already prepared (both compatibility and new canonical collections exist)
    if original is not None and existing_new is not None:
        log(
            f"  Asset already prepared (both '{record.old_name}' and "
            f"'{record.new_name}' collections exist). Continuing."
        )
        return

    if original is None:
        if existing_new is not None:
            raise RuntimeError(
                f"Source collection '{record.old_name}' is missing, but "
                f"'{record.new_name}' already exists in:\n"
                f"    {record.old_blend_path}"
            )
        raise RuntimeError(
            f"Source collection '{record.old_name}' was not found as a "
            f"local collection in:\n"
            f"    {record.old_blend_path}"
        )

    if existing_new is not None:
        raise RuntimeError(
            f"Collection '{record.new_name}' already exists in:\n"
            f"    {record.old_blend_path}"
        )

    log(
        f"  source collection: "
        f"{record.old_name} -> {record.new_name}"
    )

    if dry_run:
        return

    # ---------------------------------------------------------------
    # Rename the REAL/original collection.
    #
    # This is important:
    #
    #     old collection ID
    #
    # remains the canonical source ID. We only change its name.
    # ---------------------------------------------------------------

    original.name = record.new_name

    if original.name != record.new_name:
        raise RuntimeError(
            f"Blender could not assign exact collection name "
            f"'{record.new_name}'. Actual name became '{original.name}'."
        )

    # ---------------------------------------------------------------
    # Temporary compatibility collection.
    #
    # Collection.copy() is intentionally shallow here:
    #
    #     root collection = new ID
    #     objects          = SAME IDs
    #     child collections = SAME IDs
    #
    # Existing files can therefore still resolve:
    #
    #     old_name
    #
    # while their underlying hierarchy continues to refer to the
    # original source datablocks.
    # ---------------------------------------------------------------

    compatibility = original.copy()
    compatibility.name = record.old_name
    compatibility.use_fake_user = True

    if compatibility.name != record.old_name:
        raise RuntimeError(
            f"Could not create compatibility collection with exact name "
            f"'{record.old_name}'. Actual name: '{compatibility.name}'."
        )

    # Do not expose the temporary compatibility root as an Asset Browser
    # asset if copy() happened to retain asset metadata.
    try:
        if compatibility.asset_data is not None:
            compatibility.asset_clear()
    except Exception:
        pass

    save_current_blend()

    log("  compatibility collection created")


def prepare_all_assets(
    records: list[AssetRename],
    dry_run: bool,
) -> None:

    log("")
    log("========== PHASE 1: PREPARE ASSETS ==========")

    for record in records:
        prepare_asset(record, dry_run)


# ---------------------------------------------------------------------------
# Library collection lookup/link
# ---------------------------------------------------------------------------


def find_linked_collection(
    collection_name: str,
    library_path: Path,
) -> bpy.types.Collection | None:

    library_path = normalized_path(library_path)

    for collection in bpy.data.collections:

        if collection.library is None:
            continue

        if not same_name(collection.name, collection_name):
            continue

        try:
            path = blender_library_absolute_path(collection.library)
        except Exception:
            continue

        if same_path(path, library_path):
            return collection

    return None


def find_old_linked_reference(
    record: AssetRename,
) -> bpy.types.Collection | None:
    """
    Find linked collection referencing the old asset, even if the library
    path or file is currently broken/unresolved.
    """
    # 1. Linked collection matching old_name and path matches old_blend_path or new_blend_path
    for collection in bpy.data.collections:
        if collection.library is None or not same_name(collection.name, record.old_name):
            continue

        try:
            path = blender_library_absolute_path(collection.library)
            if same_path(path, record.old_blend_path) or same_path(path, record.new_blend_path):
                return collection
        except Exception:
            continue

    # 2. Linked collection matching old_name whose library file stem matches old_name or new_name
    for collection in bpy.data.collections:
        if collection.library is None or not same_name(collection.name, record.old_name):
            continue

        lib_stem = Path(collection.library.filepath).stem
        if same_name(lib_stem, record.old_name) or same_name(lib_stem, record.new_name):
            return collection

    # 3. Fallback: Any linked collection matching old_name
    for collection in bpy.data.collections:
        if collection.library is not None and same_name(collection.name, record.old_name):
            return collection

    return None


def find_new_linked_reference(
    record: AssetRename,
) -> bpy.types.Collection | None:
    """
    Find linked collection referencing the new asset.
    """
    for collection in bpy.data.collections:
        if collection.library is None or not same_name(collection.name, record.new_name):
            continue

        try:
            path = blender_library_absolute_path(collection.library)
            if same_path(path, record.new_blend_path) or same_path(path, record.old_blend_path):
                return collection
        except Exception:
            continue

    for collection in bpy.data.collections:
        if collection.library is None or not same_name(collection.name, record.new_name):
            continue

        lib_stem = Path(collection.library.filepath).stem
        if same_name(lib_stem, record.new_name) or same_name(lib_stem, record.old_name):
            return collection

    return None


def link_collection(
    library_path: Path,
    collection_name: str,
    prefer_relative_path: str | None = None,
) -> bpy.types.Collection:

    load_path = prefer_relative_path if prefer_relative_path else str(library_path)

    log(
        f"    linking '{collection_name}' from "
        f"'{load_path}'"
    )

    with bpy.data.libraries.load(
        load_path,
        link=True,
        relative=load_path.startswith("//"),
    ) as (data_from, data_to):

        matching_names = [
            name for name in data_from.collections
            if same_name(name, collection_name)
        ]

        if not matching_names:
            raise RuntimeError(
                f"Collection '{collection_name}' does not exist in:\n"
                f"    {library_path}"
            )

        data_to.collections = [matching_names[0]]

    result = data_to.collections[0]

    if result is None:
        raise RuntimeError(
            f"Blender failed to link collection '{collection_name}' "
            f"from '{library_path}'."
        )

    return result


# ---------------------------------------------------------------------------
# PHASE 2
# Project migration
# ---------------------------------------------------------------------------


def migrate_reference(
    record: AssetRename,
    shot_name: str | None = None,
    preserve_overrides: bool = False,
) -> bool:
    """
    Migrate one asset reference in the currently open project.

    Returns True if anything changed.
    """

    old_reference = find_old_linked_reference(record)

    if old_reference is None:
        return False

    log(
        f"  Found linked asset: "
        f"{record.old_name}"
    )

    # Remember which local overrides currently reference this root.
    affected_overrides: list[bpy.types.Collection] = []

    for collection in bpy.data.collections:
        override = collection.override_library

        if override is None:
            continue

        if override.reference == old_reference:
            affected_overrides.append(collection)

    log(
        f"    matching local collection overrides: "
        f"{len(affected_overrides)}"
    )

    # Sanity check: old collection must be linked.
    old_library = old_reference.library
    if old_library is None:
        raise RuntimeError(
            f"'{record.old_name}' unexpectedly is not linked."
        )

    # ---------------------------------------------------------------
    # Ensure old_library points to an existing file on disk.
    # If the asset file was already renamed on disk, updating filepath
    # allows bpy.data.libraries.load to read from old_library without
    # creating a duplicate Library datablock.
    # ---------------------------------------------------------------

    is_relative = old_library.filepath.startswith("//")
    try:
        current_lib_abs = blender_library_absolute_path(old_library)
    except Exception:
        current_lib_abs = None

    if current_lib_abs is None or not same_path(current_lib_abs, record.new_blend_path):
        old_library.filepath = make_blender_path_for_current_file(
            record.new_blend_path,
            prefer_relative=is_relative,
        )
        log(
            f"    updated library datablock '{old_library.name}' filepath: "
            f"{old_library.filepath}"
        )

    # ---------------------------------------------------------------
    # Link the new collection from the library datablock.
    # ---------------------------------------------------------------

    new_reference = find_new_linked_reference(record)

    if new_reference is None:
        log(
            f"    linking '{record.new_name}' from library "
            f"'{old_library.filepath}'"
        )

        with bpy.data.libraries.load(
            old_library.filepath,
            link=True,
        ) as (data_from, data_to):

            matching_names = [
                name for name in data_from.collections
                if same_name(name, record.new_name)
            ]

            if not matching_names:
                raise RuntimeError(
                    f"Collection '{record.new_name}' does not exist in library:\n"
                    f"    {old_library.filepath}"
                )

            data_to.collections = [matching_names[0]]

        new_reference = data_to.collections[0]

    if new_reference is None or new_reference.library is None:
        raise RuntimeError(
            f"Failed to link '{record.new_name}' from '{old_library.filepath}'."
        )

    # ---------------------------------------------------------------
    # Critical operation.
    #
    # This replaces every usage of the old linked root ID with the new
    # linked root ID.
    #
    # This includes the ID used as the Library Override reference.
    # ---------------------------------------------------------------

    log(
        f"    remapping linked reference "
        f"{record.old_name} -> {record.new_name}"
    )

    old_reference.user_remap(new_reference)

    if preserve_overrides:
        failed_overrides = []
        target_override_name = f"{record.new_name}_{shot_name}" if shot_name else record.new_name

        for collection in affected_overrides:
            override = collection.override_library

            if override is None or override.reference != new_reference:
                failed_overrides.append(collection.name)
                continue

            old_local_name = collection.name
            collection.name = target_override_name

            log(
                f"    preserve-overrides: renamed local override collection "
                f"'{old_local_name}' -> '{collection.name}'"
            )

            if collection.name != target_override_name:
                warning(
                    f"Expected override name '{target_override_name}', "
                    f"but Blender assigned '{collection.name}'."
                )

        if failed_overrides:
            raise RuntimeError(
                "Some Library Overrides did not remap to the new reference:\n"
                + "\n".join(
                    f"    {name}"
                    for name in failed_overrides
                )
            )

        log(
            "    preserve-overrides: skipped operations_update(), "
            "old linked ID removal, and orphan purge"
        )

        return True

    # Refresh override operation definitions after the ID remap and rename local overrides
    failed_overrides = []
    target_override_name = f"{record.new_name}_{shot_name}" if shot_name else record.new_name

    for collection in affected_overrides:
        override = collection.override_library

        if override is None or override.reference != new_reference:
            failed_overrides.append(collection.name)
            continue

        try:
            override.operations_update()
        except Exception as exc:
            warning(
                f"operations_update() failed for "
                f"'{collection.name}': {exc}"
            )

        old_local_name = collection.name
        collection.name = target_override_name

        log(
            f"    renamed local override collection "
            f"'{old_local_name}' -> '{collection.name}'"
        )

        if collection.name != target_override_name:
            warning(
                f"Expected override name '{target_override_name}', "
                f"but Blender assigned '{collection.name}'."
            )

    if failed_overrides:
        raise RuntimeError(
            "Some Library Overrides did not remap to the new reference:\n"
            + "\n".join(
                f"    {name}"
                for name in failed_overrides
            )
        )

    # ---------------------------------------------------------------
    # Remove the old linked collection datablock from the file.
    # Otherwise it remains in bpy.data.collections as an unreferenced
    # linked datablock, causing missing library/datablock warnings when
    # the project file is reopened.
    # ---------------------------------------------------------------

    log(
        f"    removing old linked collection "
        f"'{old_reference.name}'"
    )

    old_reference.use_fake_user = False
    bpy.data.collections.remove(old_reference, do_unlink=True)

    # ---------------------------------------------------------------
    # Update paths stored in all matching Library datablocks.
    # ---------------------------------------------------------------

    future_path = record.new_blend_path

    for lib in list(bpy.data.libraries):
        try:
            lib_abs = blender_library_absolute_path(lib)
        except Exception:
            continue

        if same_path(lib_abs, record.old_blend_path):
            lib_is_relative = lib.filepath.startswith("//")
            lib.filepath = make_blender_path_for_current_file(
                future_path,
                prefer_relative=lib_is_relative,
            )
            log(
                f"    updated library datablock '{lib.name}' filepath: "
                f"{lib.filepath}"
            )

    return True


def is_hidden(path: Path) -> bool:
    if path.name.startswith("."):
        return True
    try:
        attributes = getattr(path.stat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0))


def _discover_in_directory(args: argparse.Namespace, target_directory: str | Path) -> list[Path]:
    root = Path(target_directory).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Target directory is unavailable: {root}")

    include = shot_ranges(args.include_shots)
    exclude = shot_ranges(args.exclude_shots)
    excluded_names: set[str] = set()
    excluded_paths: set[Path] = set()
    folder_values = args.exclude_folders or []
    folder_entries: list[str] = []
    for value in folder_values:
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
        if any(resolved == item or resolved.is_relative_to(item) for item in excluded_paths):
            return True
        if os.path.normcase(directory.name) in excluded_names:
            return True
        return args.ignore_hidden_folders and is_hidden(directory)

    if excluded_directory(root):
        return []

    discovered: list[Path] = []
    for folder, directories, filenames in os.walk(root, topdown=True, followlinks=False):
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
    targets = args.target_directory
    if isinstance(targets, (str, Path)):
        targets = [targets]
    return list(dict.fromkeys(
        path for target in targets for path in _discover_in_directory(args, target)
    ))


def discover_project_files(args: argparse.Namespace, source_asset_paths: set[str]) -> list[Path]:
    return [
        path for path in discover_blend_files(args)
        if os.path.normcase(str(normalized_path(path))) not in source_asset_paths
    ]


def migrate_project_file(
    path: Path,
    records: list[AssetRename],
    dry_run: bool,
    preserve_overrides: bool = False,
    purge_unused: bool = False,
) -> bool:

    open_blend(path)

    changed = False
    shot_name = path.stem

    for record in records:

        # In dry-run mode we only detect references.
        if dry_run:
            old_reference = find_old_linked_reference(record)

            if old_reference is not None:
                target_override_name = f"{record.new_name}_{shot_name}"
                log(
                    f"  WOULD MIGRATE: "
                    f"{record.old_name} -> {target_override_name}"
                )
                changed = True

            continue

        if migrate_reference(record, shot_name=shot_name, preserve_overrides=preserve_overrides):
            changed = True

    # Ensure all libraries pointing to any renamed assets are updated
    for record in records:
        for lib in list(bpy.data.libraries):
            try:
                lib_abs = blender_library_absolute_path(lib)
            except Exception:
                continue

            if same_path(lib_abs, record.old_blend_path):
                if not dry_run:
                    is_relative = lib.filepath.startswith("//")
                    lib.filepath = make_blender_path_for_current_file(
                        record.new_blend_path,
                        prefer_relative=is_relative,
                    )
                    log(
                        f"  Updated remaining library datablock '{lib.name}' to: "
                        f"{lib.filepath}"
                    )
                changed = True

    if (changed or purge_unused) and not dry_run:
        if preserve_overrides:
            log("  preserve-overrides: skipped unused library removal and orphan purge")
        else:
            # Purge any remaining unreferenced libraries or orphan linked data
            for lib in list(bpy.data.libraries):
                if lib.users == 0:
                    log(f"  removing unused library datablock: {lib.filepath}")
                    bpy.data.libraries.remove(lib, do_unlink=True)

            try:
                bpy.data.orphans_purge(do_local_ids=False, do_linked_ids=True, do_recursive=True)
            except Exception:
                try:
                    bpy.data.orphans_purge(do_recursive=True)
                except Exception:
                    pass

        if purge_unused:
            removed = purge_unused_local_data()
            log(f"  purged {removed} unused local data-block(s)")

        save_current_blend()

    if not changed:
        log("  no matching linked assets")

    return changed or (purge_unused and not dry_run)


def migrate_all_projects(
    args: argparse.Namespace,
    records: list[AssetRename],
    dry_run: bool,
    preserve_overrides: bool = False,
    purge_unused: bool = False,
) -> tuple[int, int]:

    log("")
    log("========== PHASE 2: MIGRATE PROJECT FILES ==========")

    source_paths = set()
    for x in records:
        source_paths.add(os.path.normcase(str(x.old_blend_path)))
        source_paths.add(os.path.normcase(str(x.new_blend_path)))

    files = discover_project_files(args, source_paths)

    log(f"Project .blend files found: {len(files)}")

    changed_count = 0

    for i, path in enumerate(files, start=1):

        log("")
        log(f"[{i}/{len(files)}] {path}")

        changed = migrate_project_file(
            path,
            records,
            dry_run,
            preserve_overrides=preserve_overrides,
            purge_unused=purge_unused,
        )

        if changed:
            changed_count += 1

    return len(files), changed_count


# ---------------------------------------------------------------------------
# PHASE 3A
# Remove compatibility collections
# ---------------------------------------------------------------------------


def cleanup_asset(
    record: AssetRename,
    dry_run: bool,
) -> None:

    log("")
    log(
        f"CLEANUP ASSET: "
        f"{record.old_name} -> {record.new_name}"
    )

    open_blend(record.old_blend_path)

    compatibility = get_local_collection(record.old_name)
    canonical = get_local_collection(record.new_name)

    if canonical is None:
        raise RuntimeError(
            f"Canonical collection '{record.new_name}' is missing from:\n"
            f"    {record.old_blend_path}"
        )

    if compatibility is None:
        log(
            f"  compatibility collection '{record.old_name}' already removed "
            f"from '{record.old_blend_path}'"
        )
        return

    log(
        f"  removing compatibility collection: "
        f"{record.old_name}"
    )

    if dry_run:
        return

    bpy.data.collections.remove(
        compatibility,
        do_unlink=True,
    )

    save_current_blend()


def cleanup_all_assets(
    records: list[AssetRename],
    dry_run: bool,
) -> None:

    log("")
    log("========== PHASE 3A: CLEANUP ASSETS ==========")

    for record in records:
        cleanup_asset(record, dry_run)


# ---------------------------------------------------------------------------
# PHASE 3B
# Rename asset .blend files and folders
# ---------------------------------------------------------------------------


@dataclass
class TemporaryFolderRename:
    record: AssetRename
    temporary_folder: Path


def rename_asset_files_and_folders(
    records: list[AssetRename],
    dry_run: bool,
) -> None:

    log("")
    log("========== PHASE 3B: RENAME FILES/FOLDERS ==========")

    for record in records:
        log(
            f"  {record.old_folder_path}"
            f"\n    -> {record.new_folder_path}"
        )

        log(
            f"  {record.old_name}.blend"
            f"\n    -> {record.new_name}.blend"
        )

    if dry_run:
        return

    # Release the currently loaded asset before filesystem renames,
    # especially important on Windows.
    bpy.ops.wm.read_factory_settings(
        use_empty=True
    )

    temporary_renames: list[TemporaryFolderRename] = []

    # ---------------------------------------------------------------
    # First rename each .blend INSIDE its old folder, then move each
    # old folder to a unique temporary name.
    #
    # The temporary step safely supports mappings like:
    #
    #     A -> B
    #     B -> C
    #
    # without folder name collisions.
    # ---------------------------------------------------------------

    for record in records:

        current_blend = record.old_blend_path

        renamed_blend = (
            record.old_folder_path
            / f"{record.new_name}.blend"
        )

        if current_blend != renamed_blend:
            log(
                f"Renaming file:\n"
                f"    {current_blend}\n"
                f" -> {renamed_blend}"
            )

            current_blend.rename(renamed_blend)

        temporary_folder = (
            record.old_folder_path.parent
            / (
                f".__asset_rename_tmp__"
                f"{uuid.uuid4().hex}"
            )
        )

        log(
            f"Temporary folder move:\n"
            f"    {record.old_folder_path}\n"
            f" -> {temporary_folder}"
        )

        record.old_folder_path.rename(
            temporary_folder
        )

        temporary_renames.append(
            TemporaryFolderRename(
                record=record,
                temporary_folder=temporary_folder,
            )
        )

    # ---------------------------------------------------------------
    # Temporary -> final folder names.
    # ---------------------------------------------------------------

    for item in temporary_renames:

        record = item.record

        log(
            f"Final folder move:\n"
            f"    {item.temporary_folder}\n"
            f" -> {record.new_folder_path}"
        )

        item.temporary_folder.rename(
            record.new_folder_path
        )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_plan(records: list[AssetRename]) -> None:

    log("")
    log("========== RENAME PLAN ==========")

    for record in records:
        log(
            f"{record.old_name} -> {record.new_name}\n"
            f"    old: {record.old_blend_path}\n"
            f"    new: {record.new_blend_path}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
        parser = create_parser()
        args = parser.parse_args(argv)

        asset_root = normalized_path(args.asset_dir)
        project_roots = [normalized_path(path) for path in args.target_directory]
        mapping_path = normalized_path(args.mapping)

        if not asset_root.is_dir():
            raise RuntimeError(f"Asset directory does not exist:\n    {asset_root}")

        for project_root in project_roots:
            if not project_root.is_dir():
                raise RuntimeError(f"Project directory does not exist:\n    {project_root}")

        if not mapping_path.is_file():
            raise RuntimeError(f"Mapping file does not exist:\n    {mapping_path}")

        mapping = load_mapping(mapping_path)
        preserve_overrides = args.preserve_overrides or args.relink_only
        records = build_asset_records(asset_root, mapping, relink_only=args.relink_only)

        if not args.relink_only:
            validate_filesystem_renames(records)

        print_plan(records)

        if args.dry_run:
            warning("DRY RUN ENABLED - no files will be changed.")

        if args.relink_only:
            log("")
            log("RELINK-ONLY MODE: Skipping asset prep (Phase 1) and filesystem rename (Phase 3).")
            if preserve_overrides:
                log("PRESERVE-OVERRIDES MODE: Avoiding override operation updates, local override renames, old linked ID removal, and orphan purge.")
            total_files, changed_files = migrate_all_projects(
                args,
                records,
                args.dry_run,
                preserve_overrides=preserve_overrides,
                purge_unused=args.purge_unused_data,
            )
        else:
            if preserve_overrides:
                log("")
                log("PRESERVE-OVERRIDES MODE: Avoiding override operation updates, local override renames, old linked ID removal, and orphan purge.")

            prepare_all_assets(records, args.dry_run)
            total_files, changed_files = migrate_all_projects(
                args,
                records,
                args.dry_run,
                preserve_overrides=preserve_overrides,
                purge_unused=args.purge_unused_data,
            )
            cleanup_all_assets(records, args.dry_run)
            rename_asset_files_and_folders(records, args.dry_run)

        log("")
        log("============================================")
        log("MIGRATION COMPLETE")
        log(f"Project files scanned:  {total_files}")
        log(f"Project files modified: {changed_files}")
        log(f"Assets processed:       {len(records)}")
        log("============================================")

    except Exception as exc:
        error("")
        error("MIGRATION ABORTED")
        error(str(exc))
        error("")
        error(
            "Asset cleanup/final renaming is only performed if all "
            "previous phases complete successfully."
        )

        import traceback
        traceback.print_exc()

        raise SystemExit(1)


if __name__ == "__main__":
    main()