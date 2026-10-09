"""Replace old linked camera rigs across selected shot .blend files.

Transfers supported rig transform/pose animation and camera lens animation to
the new rig, then saves each processed shot. The old rig root is discovered
recursively under --old-rigs-root.

Example:

    blender --background --python replace_camera_rigs_batch.py -- `
        --target-directory "D:/Show/02_ANIMATIONS" `
        --new-rig-blend "D:/Show/01_ASSETS/3d/cameras/cam_v2/cam_v2.blend" `
        --new-rig-collection "cam_v2" `
        --old-rigs-root "D:/Show/01_ASSETS/3d/cameras" `
        --recursive --include-shots "100-250"

Discovery also supports multiple target directories, excluded folders, shot
exclusion ranges, and hidden-folder control. `--shots-root` remains an alias
for `--target-directory`; recursion remains disabled by default. Use
`--rename-camera-objects` for rename-only mode, `--dry-run` to avoid changes,
and `--purge-unused-data` to purge local orphan data-blocks before saving.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

import bpy


@dataclass
class ProcessingStats:
    processed: int = 0
    replaced: int = 0
    skipped: int = 0
    failed: int = 0


# BASIC UTILS
INFO_PREFIX = "[SCRIPT]"

def info(message: str) -> None:
    print(f"{INFO_PREFIX} {message}", flush=True)


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(str(Path(path).resolve())))


def _log_missing_libraries() -> None:
    for library in bpy.data.libraries:
        abs_path = bpy.path.abspath(library.filepath, library=library)
        if not os.path.exists(abs_path):
            info(f"  Missing library: {abs_path!r} (stored as {library.filepath!r})")


def is_corrupted_packed_linked_datablock_error(error: Exception) -> bool:
    message = str(error)
    return (
        "seems corrupted" in message
        and "no owner 'Library' data found" in message
        and "packed linked data-block" in message
    )


def is_missing_override_root_error(error: Exception) -> bool:
    message = str(error)
    return (
        "Missing library override hierarchy root data" in message
        and "will be changed to use" in message
        and "as root" in message
    )


def is_ignorable_library_runtime_error(error: Exception) -> bool:
    return is_missing_override_root_error(error)


def is_hidden_fs_entry(path: Path) -> bool:
    """
    Return True if path is hidden by naming convention (dotfile) or filesystem
    hidden attributes (Windows).
    """
    if path.name.startswith("."):
        return True

    try:
        file_attributes = path.stat().st_file_attributes
    except (AttributeError, OSError):
        return False

    return bool(file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)


def is_hidden_path(path: Path, root: Path) -> bool:
    """
    Return True if path itself or any parent between path and root is hidden.
    """
    current = path
    while True:
        if is_hidden_fs_entry(current):
            return True

        if current == root or current.parent == current:
            break

        current = current.parent

    return False


def is_versioned_backup_blend(path: Path) -> bool:
    """
    Return True when filename ends with '_vXX' where XX is one or more digits,
    for example: shot010_v01.blend.
    This check is added because I ran into misnamed backup file folder (",version").
    """
    return re.search(r"_v\d+$", path.stem, re.IGNORECASE) is not None


# ARGUMENTS AND FILE DISCOVERY
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots-root", "--target-directory", dest="target_directory", nargs="+", required=True, help="Root folder(s) containing shot .blend files.")
    parser.add_argument("--exclude-folders", action="append", help="Folders excluded with their subfolders; repeatable.")
    parser.add_argument("--include-shots", "--include_shots", action="append", help="Include filename number suffixes/ranges, e.g. 1,4-8; repeatable.")
    parser.add_argument("--exclude-shots", "--exclude_shots", action="append", help="Exclude filename number suffixes/ranges, e.g. 2,6-7; repeatable.")
    parser.add_argument("--new-rig-blend", required=True, type=Path, help="Path to the new camera rig .blend file.")
    parser.add_argument("--new-rig-collection", default="", help="Collection name inside new rig .blend. Defaults to .blend file name.")
    parser.add_argument("--old-rigs-root", required=True, type=Path, help="Root directory containing old camera rig .blend files.")
    parser.add_argument("--old-rig-name-pattern", default="", help="Optional fallback name prefix to identify old rig collection instances.")
    parser.add_argument("--rename-camera-objects", action="store_true", help="Only rename cameras in <collection> and <collection>_old; do not replace rigs.")
    parser.add_argument("--dry-run", action="store_true", help="Do not save changes.")
    parser.add_argument("--ignore-hidden-folders", action=argparse.BooleanOptionalAction, default=True, help="Ignore hidden folders and files (default: enabled).")
    parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=False, help="Search subfolders recursively (default: disabled, preserving prior behavior).")
    parser.add_argument("--purge-unused-data", action="store_true", help="Purge unused local data-blocks before saving processed shots (default: disabled).")
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
            if path.suffix.lower() != ".blend" or path.is_symlink() or is_versioned_backup_blend(path):
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


def discover_old_rig_blend_files(old_rigs_root: Path, recursive: bool, new_rig_blend: Path) -> list[Path]:
    """
    Find all old rig .blend files under the given root directory, excluding the new rig .blend file.
    """
    discovery_args = argparse.Namespace(
        target_directory=[old_rigs_root], exclude_folders=None,
        include_shots=None, exclude_shots=None,
        ignore_hidden_folders=True, recursive=recursive,
    )
    files = [path for path in discover_blend_files(discovery_args) if not is_versioned_backup_blend(path)]
    new_rig_normalized = normalize_path(str(new_rig_blend))
    old_rig_files = [p for p in files if normalize_path(str(p)) != new_rig_normalized]
    old_rig_files.sort()
    return old_rig_files


def purge_unused_local_data() -> int:
    before = 0
    for collection_name in dir(bpy.data):
        if collection_name.startswith("_"):
            continue
        data_collection = getattr(bpy.data, collection_name)
        if isinstance(data_collection, bpy.types.bpy_prop_collection):
            before += len(data_collection)
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
    after = 0
    for collection_name in dir(bpy.data):
        if collection_name.startswith("_"):
            continue
        data_collection = getattr(bpy.data, collection_name)
        if isinstance(data_collection, bpy.types.bpy_prop_collection):
            after += len(data_collection)
    return before - after


def save_shot_file(path: Path, purge_unused: bool) -> None:
    if purge_unused:
        removed = purge_unused_local_data()
        info(f"Purged {removed} unused local data-block(s).")
    result = bpy.ops.wm.save_mainfile(filepath=str(path))
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender did not save {path}: {result}")


# COLLECTION/RIG DETECTION IN SCENE
def get_collection_library_path(collection: bpy.types.Collection) -> str:
    """
    Get the absolute file path of the library from which the collection originates.
    Returns None if the collection is not linked from an external library.

    note: If a collection/object is linked from another .blend file, that other .blend
    is treated as a library source for the current shot file. Blender exposes it through
    collection.library (or through override_library.reference.library for overrides).
    """
    if collection.library:
        return bpy.path.abspath(collection.library.filepath, library=collection.library)

    override = getattr(collection, "override_library", None)
    reference = getattr(override, "reference", None)
    library = getattr(reference, "library", None)
    if library:
        return bpy.path.abspath(library.filepath, library=library)

    return None

def find_old_rig_instances(scene: bpy.types.Scene, old_rig_paths: set[str], old_rig_name_pattern: str) -> list[bpy.types.Collection]:
    """
    Find all collections anywhere in the scene hierarchy that are linked from old rig
    paths or match the old rig name pattern.
    """
    matches = []
    stack = list(scene.collection.children)
    visited = set()

    while stack:
        collection = stack.pop()
        pointer = collection.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)

        source_path = get_collection_library_path(collection)
        if source_path and normalize_path(source_path) in old_rig_paths:
            matches.append(collection)
            continue

        if old_rig_name_pattern and collection.name.startswith(old_rig_name_pattern):   # probably is not necessary
            matches.append(collection)
            continue

        stack.extend(collection.children)

    return matches


def is_new_rig_collection_instance(collection: bpy.types.Collection, new_rig_path: str, new_rig_collection_name: str) -> bool:
    """
    Return True if collection is sourced from the new rig blend file and matches
    the requested new rig collection name (including override instances).
    """
    source_path = get_collection_library_path(collection)
    if not source_path or normalize_path(source_path) != new_rig_path:
        return False

    if collection.name == new_rig_collection_name:
        return True

    override = getattr(collection, "override_library", None)
    reference = getattr(override, "reference", None)
    reference_name = getattr(reference, "name", None)
    return reference_name == new_rig_collection_name


def has_new_rig_instance(scene: bpy.types.Scene, new_rig_blend: Path, new_rig_collection: str) -> bool:
    """
    Return True as soon as a new-rig instance is found anywhere in the scene hierarchy.
    """
    stack = list(scene.collection.children)
    visited = set()
    new_rig_path = normalize_path(str(new_rig_blend))

    while stack:
        collection = stack.pop()
        pointer = collection.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)

        if is_new_rig_collection_instance(collection, new_rig_path, new_rig_collection):
            return True

        stack.extend(collection.children)

    return False


def find_collections_by_name(scene: bpy.types.Scene, collection_name: str) -> list[bpy.types.Collection]:
    matches = []
    stack = list(scene.collection.children)
    visited = set()

    while stack:
        collection = stack.pop()
        pointer = collection.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)

        if collection.name == collection_name:
            matches.append(collection)

        stack.extend(collection.children)

    return matches


def find_collections_by_name_suffix(scene: bpy.types.Scene, suffix: str) -> list[bpy.types.Collection]:
    matches = []
    stack = list(scene.collection.children)
    visited = set()

    while stack:
        collection = stack.pop()
        pointer = collection.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)

        if collection.name.endswith(suffix):
            matches.append(collection)

        stack.extend(collection.children)

    return matches


def find_old_rig_collection_instances(scene: bpy.types.Scene, old_rig_paths: set[str]) -> list[bpy.types.Object]:
    """
    Find object-level collection instances that point to old rig collections.
    These are not currently supported by the replacement flow.
    """
    matches = []
    for obj in scene.collection.all_objects:
        if obj.instance_type != "COLLECTION":
            continue

        instance_collection = obj.instance_collection
        if instance_collection is None:
            continue

        source_path = get_collection_library_path(instance_collection)
        if source_path and normalize_path(source_path) in old_rig_paths:
            matches.append(obj)

    return matches


def find_collection_parent(root: bpy.types.Collection, target: bpy.types.Collection) -> bpy.types.Collection | None:
    """
    Find the direct parent collection of target within the given hierarchy root.
    Returns None if target is not found or is a top-level child of root.
    """
    stack = [root]
    visited = set()

    while stack:
        parent = stack.pop()
        pointer = parent.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)

        for child in parent.children:
            if child == target:
                return parent
            stack.append(child)

    return None


def unlink_collection_from_scene_tree(root: bpy.types.Collection, target: bpy.types.Collection) -> bool:
    """
    Unlink target collection from all parents under root.
    Returns True if at least one unlink happened.
    """
    removed = False
    stack = [root]
    visited = set()

    while stack:
        parent = stack.pop()
        pointer = parent.as_pointer()
        if pointer in visited:
            continue
        visited.add(pointer)

        for child in list(parent.children):
            if child == target:
                parent.children.unlink(child)
                removed = True
                continue

            stack.append(child)

    return removed


# LINKING AND OVERRIDE CREATION
def link_collection(scene: bpy.types.Scene, collection_name: str, blend_path: Path) -> bpy.types.Collection:
    """
    Link the given collection into the scene from the given .blend file.
    Returns the linked collection.
    """
    with bpy.data.libraries.load(str(blend_path), link=True) as (data_from, data_to):
        if collection_name not in data_from.collections:
            raise RuntimeError(
                f"Collection '{collection_name}' was not found in '{blend_path}'."
            )
        data_to.collections = [collection_name]

    expected_library = normalize_path(str(blend_path))
    linked_collection = None
    for collection in bpy.data.collections:
        if collection.name != collection_name:
            continue

        library = collection.library
        if library is None:
            continue

        library_path = normalize_path(str(bpy.path.abspath(library.filepath, library=library)))
        if library_path == expected_library:
            linked_collection = collection
            break

    if linked_collection is None:
        raise RuntimeError(
            f"Linked collection '{collection_name}' from '{blend_path}' could not be resolved."
        )

    if linked_collection.name not in scene.collection.children:
        scene.collection.children.link(linked_collection)

    return linked_collection


def create_override_from_linked_collection(scene: bpy.types.Scene, linked_collection: bpy.types.Collection) -> bpy.types.Collection:
    """
    Create an override collection from the linked collection.
    Returns the override collection.
    """
    if not linked_collection.library:   # not a linked collection, cannot create override
        return linked_collection

    collection = linked_collection.override_hierarchy_create(scene, bpy.context.view_layer, do_fully_editable=True)
    if collection:
        return collection

    # for collection in bpy.data.collections:
    #     if collection.override_library and collection.override_library.reference == linked_collection:
    #         return collection

    raise RuntimeError("Override collection was not found after override_hierarchy_create.")


# OBJECT/BONE LOOKUP HELPERS
def find_first_object_by_type(collection: bpy.types.Collection, object_type: str) -> bpy.types.Object:
    for obj in collection.all_objects:
        if obj.type == object_type:
            return obj
    return None


def find_pose_bone(armature_object: bpy.types.Object, bone_name: str) -> bpy.types.PoseBone:
    """
    Find a pose bone by name (case-insensitive) in the given armature object.
    """
    if armature_object.type != "ARMATURE" or not armature_object.pose:
        return None

    needle = bone_name.casefold()
    for bone in armature_object.pose.bones:
        if bone.name.casefold() == needle:
            return bone
    return None


# ACTION/FCURVE HELPERS
def create_action(owner: bpy.types.ID, action_name: str) -> bpy.types.Action:
    """
    Create a fresh action and assign it to the given owner.
    This avoids relying on legacy Action.fcurves mutation and keeps reruns deterministic.
    """
    if not owner.animation_data:
        owner.animation_data_create()

    action = bpy.data.actions.new(name=action_name)
    owner.animation_data.action = action

    return action


def find_action_fcurve(owner: bpy.types.ID, data_path: str, array_index: int) -> bpy.types.FCurve | None:
    for fcurve in get_action_fcurves(owner):
        if fcurve.data_path == data_path and fcurve.array_index == array_index:
            return fcurve
    return None


def find_first_action_fcurve_by_data_path(owner: bpy.types.ID, data_path: str) -> bpy.types.FCurve:
    for fcurve in get_action_fcurves(owner):
        if fcurve.data_path == data_path:
            return fcurve
    return None


def copy_fcurve_modifiers(source_fcurve: bpy.types.FCurve, target_fcurve: bpy.types.FCurve):
    """
    Copy modifiers from source_fcurve to target_fcurve, replacing any existing modifiers on the target.
    """
    while target_fcurve.modifiers:
        target_fcurve.modifiers.remove(target_fcurve.modifiers[0])

    for source_modifier in source_fcurve.modifiers:
        target_modifier = target_fcurve.modifiers.new(source_modifier.type)

        for prop in source_modifier.bl_rna.properties:
            if prop.identifier in {"rna_type", "type", "name"}:
                continue
            if prop.is_readonly:
                continue

            try:
                setattr(target_modifier, prop.identifier, getattr(source_modifier, prop.identifier))
            except (AttributeError, TypeError, ValueError):
                continue


def ensure_target_fcurve(owner: bpy.types.ID, data_path: str, array_index: int, frame_hint: float) -> bpy.types.FCurve:
    fcurve = find_action_fcurve(owner, data_path, array_index)
    if fcurve is not None:
        return fcurve
 
    try:
        owner.keyframe_insert(data_path=data_path, index=array_index, frame=frame_hint)
    except TypeError:
        # Scalar properties (for example custom properties) do not accept explicit index.
        owner.keyframe_insert(data_path=data_path, frame=frame_hint)

    fcurve = find_action_fcurve(owner, data_path, array_index)
    if fcurve is None:
        fcurve = find_first_action_fcurve_by_data_path(owner, data_path)
    if fcurve is None:
        raise RuntimeError(f"Failed to create target F-Curve: data_path='{data_path}', index={array_index}")

    return fcurve


def copy_fcurve_to_owner(owner: bpy.types.ID, source_fcurve: bpy.types.FCurve, target_data_path: str, target_array_index: int):
    """
    Copy the source_fcurve to the target owner at the specified data_path and array_index.
    If the target fcurve does not exist, it will be created.
    """
    frame_hint = source_fcurve.keyframe_points[0].co.x if source_fcurve.keyframe_points else 0
    target_fcurve = ensure_target_fcurve(owner, target_data_path, target_array_index, frame_hint)

    target_fcurve.keyframe_points.clear()
    copy_fcurve_points(source_fcurve, target_fcurve)
    copy_fcurve_modifiers(source_fcurve, target_fcurve)
    target_fcurve.update()


def validate_unique_fcurves(fcurves: list[bpy.types.FCurve], owner_name: str):
    seen = set()

    for fcurve in fcurves:
        key = (fcurve.data_path, fcurve.array_index)
        if key in seen:
            raise RuntimeError(
                f"{owner_name}: multiple F-Curves exist for "
                f"path={fcurve.data_path!r}, index={fcurve.array_index}. "
                "Layered animation is not supported."
            )
        seen.add(key)


def validate_no_drivers_or_nla(owner: bpy.types.ID, owner_name: str):
    anim_data = getattr(owner, "animation_data", None)
    if anim_data is None:
        return

    nla_tracks = getattr(anim_data, "nla_tracks", None)
    if nla_tracks is None:
        return

    for track in nla_tracks:
        if len(track.strips) > 0:
            raise RuntimeError(f"{owner_name}: NLA animation is not supported.")


def get_action_fcurves(owner: bpy.types.ID) -> list[bpy.types.FCurve]:
    """
    Return all fcurves from the owner's current action using the newer
    action.layers / strip / channelbag API.
    """
    anim_data = getattr(owner, "animation_data", None)
    action = getattr(anim_data, "action", None)
    slot = getattr(anim_data, "action_slot", None)

    if action is None or slot is None:
        return []

    fcurves = []
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type != "KEYFRAME":
                continue

            channelbag = strip.channelbag(slot)
            if channelbag is not None:
                fcurves.extend(channelbag.fcurves)

    return fcurves


# VALIDATION HELPERS
def extract_pose_bone_property_from_data_path(data_path: str) -> tuple[str, str] | None:
    match = re.match(r'^pose\.bones\["(.+?)"\]\.(.+)$', data_path)
    if not match:
        return None

    return match.group(1), match.group(2)


def is_pose_bone_custom_property_path(data_path: str) -> bool:
    return re.match(r'^pose\.bones\[".+?"\]\[".+?"\]$', data_path) is not None


def is_pose_bone_constraint_property(property_name: str) -> bool:
    return property_name.startswith('constraints["')


def matrices_close(a, b, epsilon: float = 1e-6) -> bool:
    return all(
        abs(a[row][column] - b[row][column]) <= epsilon
        for row in range(4)
        for column in range(4)
    )


def validate_pose_bone_rest_compatibility(old_armature, new_armature, animated_bone_names: set[str]):
    for bone_name in sorted(animated_bone_names):
        old_data_bone = old_armature.data.bones.get(bone_name)
        new_data_bone = new_armature.data.bones.get(bone_name)
        if old_data_bone is None or new_data_bone is None:
            raise RuntimeError(f"Missing data-bone for animated bone '{bone_name}'.")

        if not matrices_close(old_data_bone.matrix_local, new_data_bone.matrix_local):
            raise RuntimeError(
                f"Animated bone '{bone_name}' has different rest transform between old and new rig."
            )


# ANIMATION TRANSFER
def copy_fcurve_points(source_fcurve: bpy.types.FCurve, target_fcurve: bpy.types.FCurve):
    """
    Copy keyframe points from source_fcurve to target_fcurve, including handles and interpolation.
    """
    source_points = source_fcurve.keyframe_points
    target_fcurve.keyframe_points.add(len(source_points))

    for index, source_point in enumerate(source_points):
        target_point = target_fcurve.keyframe_points[index]
        target_point.co = source_point.co
        target_point.handle_left = source_point.handle_left
        target_point.handle_right = source_point.handle_right
        target_point.handle_left_type = source_point.handle_left_type
        target_point.handle_right_type = source_point.handle_right_type
        target_point.interpolation = source_point.interpolation
        target_point.easing = source_point.easing
        target_point.amplitude = source_point.amplitude
        target_point.back = source_point.back
        target_point.period = source_point.period

    target_fcurve.extrapolation = source_fcurve.extrapolation
    target_fcurve.color_mode = source_fcurve.color_mode
    target_fcurve.lock = source_fcurve.lock
    target_fcurve.mute = source_fcurve.mute
    target_fcurve.auto_smoothing = source_fcurve.auto_smoothing


def copy_pose_bone_animation(old_armature, new_armature) -> int:
    """
    Copy pose bone animation from the old armature to the new armature.
    Returns the number of fcurves copied.
    """
    source_fcurves = get_action_fcurves(old_armature)
    validate_no_drivers_or_nla(old_armature, old_armature.name)
    validate_unique_fcurves(source_fcurves, old_armature.name)
    copy_pose_bone_transform_values(old_armature, new_armature)

    if not source_fcurves:
        return 0

    supported_properties = {
        "location",
        "delta_location",
        "scale",
        "delta_scale",
        "rotation_euler",
        "delta_rotation_euler",
        "rotation_quaternion",
        "delta_rotation_quaternion",
        "rotation_axis_angle",
    }

    missing_bones: set[str] = set()
    unsupported_curves: list[tuple[str, int]] = []
    animated_bone_names: set[str] = set()
    for source_fcurve in source_fcurves:
        if not source_fcurve.data_path.startswith('pose.bones["'):
            continue

        if is_pose_bone_custom_property_path(source_fcurve.data_path):  # ignore custom property curves of the Camera bone
            continue

        parsed = extract_pose_bone_property_from_data_path(source_fcurve.data_path)
        if parsed is None:
            unsupported_curves.append((source_fcurve.data_path, source_fcurve.array_index))
            continue

        bone_name, property_name = parsed
        old_bone = find_pose_bone(old_armature, bone_name)
        new_bone = find_pose_bone(new_armature, bone_name)
        if new_bone is None or old_bone is None:
            missing_bones.add(bone_name)
            continue

        if property_name not in supported_properties and not is_pose_bone_constraint_property(property_name):
            unsupported_curves.append((source_fcurve.data_path, source_fcurve.array_index))
            continue

        if property_name.startswith("rotation") and old_bone.rotation_mode != new_bone.rotation_mode:
            raise RuntimeError(
                f"Rotation mode mismatch for bone '{bone_name}': "
                f"old={old_bone.rotation_mode}, new={new_bone.rotation_mode}"
            )

        animated_bone_names.add(bone_name)

    if missing_bones:
        names = ", ".join(sorted(missing_bones))
        raise RuntimeError(f"Missing target bones in new rig: {names}")

    if unsupported_curves:
        raise RuntimeError(f"Unsupported pose curves detected: {unsupported_curves}")

    validate_pose_bone_rest_compatibility(old_armature, new_armature, animated_bone_names)

    copied_fcurves = 0
    for source_fcurve in source_fcurves:
        parsed = extract_pose_bone_property_from_data_path(source_fcurve.data_path)
        if parsed is None:
            continue

        _, property_name = parsed
        if property_name not in supported_properties and not is_pose_bone_constraint_property(property_name):
            continue

        copy_fcurve_to_owner(new_armature, source_fcurve, source_fcurve.data_path, source_fcurve.array_index)
        copied_fcurves += 1

    return copied_fcurves


def copy_object_transform_animation(old_object, new_object) -> int:
    """
    Copy object-mode transform animation from old_object to new_object.
    Returns the number of fcurves copied.
    """
    copy_object_transform_values(old_object, new_object)

    source_fcurves = get_action_fcurves(old_object)
    validate_no_drivers_or_nla(old_object, old_object.name)
    validate_unique_fcurves(source_fcurves, old_object.name)
    if not source_fcurves:
        return 0

    supported_properties = {
        "location",
        "delta_location",
        "scale",
        "delta_scale",
        "rotation_euler",
        "delta_rotation_euler",
        "rotation_quaternion",
        "delta_rotation_quaternion",
        "rotation_axis_angle",
    }

    unsupported_curves: list[tuple[str, int]] = []
    copied_count = 0
    for source_fcurve in source_fcurves:
        property_name = source_fcurve.data_path

        if property_name.startswith('pose.bones["'):
            continue

        if property_name not in supported_properties:
            unsupported_curves.append((source_fcurve.data_path, source_fcurve.array_index))
            continue

        if property_name in {"location", "delta_location", "scale", "delta_scale", "rotation_euler", "delta_rotation_euler"} and source_fcurve.array_index not in {0, 1, 2}:
            unsupported_curves.append((source_fcurve.data_path, source_fcurve.array_index))
            continue

        if property_name in {"rotation_quaternion", "delta_rotation_quaternion", "rotation_axis_angle"} and source_fcurve.array_index not in {0, 1, 2, 3}:
            unsupported_curves.append((source_fcurve.data_path, source_fcurve.array_index))
            continue

        copy_fcurve_to_owner(new_object, source_fcurve, source_fcurve.data_path, source_fcurve.array_index)
        copied_count += 1

    if unsupported_curves:
        raise RuntimeError(f"Unsupported object transform curves detected: {unsupported_curves}")

    return copied_count


def copy_object_transform_values(old_object, new_object):
    """
    Copy object-mode transform values from old_object to new_object.
    This handles non-keyed (constant) transforms.
    """
    if new_object.rotation_mode != old_object.rotation_mode:
        raise RuntimeError(
            f"Rotation mode mismatch for rig object '{old_object.name}': "
            f"old={old_object.rotation_mode}, new={new_object.rotation_mode}"
        )

    new_object.location = old_object.location.copy()
    new_object.delta_location = old_object.delta_location.copy()
    new_object.scale = old_object.scale.copy()
    new_object.delta_scale = old_object.delta_scale.copy()

    new_object.rotation_euler = old_object.rotation_euler.copy()
    new_object.delta_rotation_euler = old_object.delta_rotation_euler.copy()
    new_object.rotation_quaternion = old_object.rotation_quaternion.copy()
    new_object.delta_rotation_quaternion = old_object.delta_rotation_quaternion.copy()
    new_object.rotation_axis_angle = old_object.rotation_axis_angle[:]


def copy_pose_bone_transform_values(old_armature, new_armature) -> int:
    """
    Copy pose-bone transform values between matching bones by name.
    This handles non-keyed (constant) transforms.
    Returns the number of bones that were copied.
    """
    copied_bones = 0

    for old_bone in old_armature.pose.bones:
        new_bone = find_pose_bone(new_armature, old_bone.name)
        if new_bone is None:
            continue

        if new_bone.rotation_mode != old_bone.rotation_mode:
            raise RuntimeError(
                f"Rotation mode mismatch for bone '{old_bone.name}': "
                f"old={old_bone.rotation_mode}, new={new_bone.rotation_mode}"
            )

        if hasattr(new_bone, "location") and hasattr(old_bone, "location"):
            new_bone.location = old_bone.location.copy()
        if hasattr(new_bone, "delta_location") and hasattr(old_bone, "delta_location"):
            new_bone.delta_location = old_bone.delta_location.copy()
        if hasattr(new_bone, "scale") and hasattr(old_bone, "scale"):
            new_bone.scale = old_bone.scale.copy()
        if hasattr(new_bone, "delta_scale") and hasattr(old_bone, "delta_scale"):
            new_bone.delta_scale = old_bone.delta_scale.copy()
        if hasattr(new_bone, "rotation_euler") and hasattr(old_bone, "rotation_euler"):
            new_bone.rotation_euler = old_bone.rotation_euler.copy()
        if hasattr(new_bone, "delta_rotation_euler") and hasattr(old_bone, "delta_rotation_euler"):
            new_bone.delta_rotation_euler = old_bone.delta_rotation_euler.copy()
        if hasattr(new_bone, "rotation_quaternion") and hasattr(old_bone, "rotation_quaternion"):
            new_bone.rotation_quaternion = old_bone.rotation_quaternion.copy()
        if hasattr(new_bone, "delta_rotation_quaternion") and hasattr(old_bone, "delta_rotation_quaternion"):
            new_bone.delta_rotation_quaternion = old_bone.delta_rotation_quaternion.copy()
        if hasattr(new_bone, "rotation_axis_angle") and hasattr(old_bone, "rotation_axis_angle"):
            new_bone.rotation_axis_angle = old_bone.rotation_axis_angle[:]

        copied_bones += 1

    return copied_bones


def copy_armature_constraint_targets(source_constraint, target_constraint, old_armature, new_armature):
    source_targets = getattr(source_constraint, "targets", None)
    target_targets = getattr(target_constraint, "targets", None)
    if source_targets is None or target_targets is None:
        return

    while len(target_targets) > 0:
        target_targets.remove(target_targets[0])

    for source_target in source_targets:
        new_target = target_targets.new()
        for prop in source_target.bl_rna.properties:
            if prop.identifier in {"rna_type", "name"}:
                continue
            if prop.is_readonly:
                continue

            try:
                value = getattr(source_target, prop.identifier)
            except (AttributeError, RuntimeError):
                continue

            if prop.identifier == "target" and value == old_armature:
                value = new_armature

            try:
                setattr(new_target, prop.identifier, value)
            except (AttributeError, TypeError, ValueError, RuntimeError):
                continue


def copy_pose_bone_constraints(old_armature, new_armature) -> int:
    """
    Copy pose-bone constraints from old_armature to new_armature for matching bone names.
    Returns the number of constraints copied.
    """
    copied_constraints = 0
    missing_bones: set[str] = set()

    for old_bone in old_armature.pose.bones:
        if len(old_bone.constraints) == 0:
            continue

        new_bone = find_pose_bone(new_armature, old_bone.name)
        if new_bone is None:
            missing_bones.add(old_bone.name)
            continue

        while len(new_bone.constraints) > 0:
            new_bone.constraints.remove(new_bone.constraints[0])

        for source_constraint in old_bone.constraints:
            target_constraint = new_bone.constraints.new(type=source_constraint.type)

            for prop in source_constraint.bl_rna.properties:
                if prop.identifier in {"rna_type", "type", "name", "targets"}:
                    continue
                if prop.is_readonly:
                    continue

                try:
                    value = getattr(source_constraint, prop.identifier)
                except (AttributeError, RuntimeError):
                    continue

                if prop.identifier == "target" and value == old_armature:
                    value = new_armature

                try:
                    setattr(target_constraint, prop.identifier, value)
                except (AttributeError, TypeError, ValueError, RuntimeError):
                    continue

            copy_armature_constraint_targets(source_constraint, target_constraint, old_armature, new_armature)
            copied_constraints += 1

    if missing_bones:
        names = ", ".join(sorted(missing_bones))
        raise RuntimeError(f"Missing target bones in new rig for constrained bones: {names}")

    return copied_constraints


def set_new_camera_focal_length_from_old_camera(old_collection, new_collection) -> int:
    """
    Copy the focal length animation from the old camera to the new camera rig's "Camera" bone's "lens" property.
    Returns the number of lens fcurves copied.
    """
    old_camera = find_first_object_by_type(old_collection, "CAMERA")
    new_armature = find_first_object_by_type(new_collection, "ARMATURE")
    if old_camera is None:
        raise RuntimeError(
            f"Old rig collection '{old_collection.name}' does not contain a camera object."
        )
    if new_armature is None:
        raise RuntimeError(
            f"New rig collection '{new_collection.name}' does not contain an armature."
        )

    new_camera_bone = find_pose_bone(new_armature, "Camera")
    if new_camera_bone is None:
        raise RuntimeError(
            f"New rig collection '{new_collection.name}' does not contain pose bone 'Camera'."
        )

    old_focal_length = old_camera.data.lens
    new_camera_bone["lens"] = old_focal_length
    target_path = f'pose.bones["{new_camera_bone.name}"]["lens"]'

    old_cam_fcurves = get_action_fcurves(old_camera.data)
    validate_no_drivers_or_nla(old_camera.data, f"{old_camera.name}.data")
    validate_unique_fcurves(old_cam_fcurves, f"{old_camera.name}.data")
    lens_source_curves = [f for f in old_cam_fcurves if f.data_path == "lens"]

    # Copy lens fcurve directly so interpolation, handles and modifiers are preserved.
    if lens_source_curves:
        source_curve = lens_source_curves[0]
        copy_fcurve_to_owner(new_armature, source_curve, target_path, source_curve.array_index)

    return len(lens_source_curves)


def transfer_camera_data(old_collection: bpy.types.Collection, new_collection: bpy.types.Collection):
    """
    Transfers pose bone animation and camera lens animation from the old rig to the new rig.
    """
    old_armature = find_first_object_by_type(old_collection, "ARMATURE")
    new_armature = find_first_object_by_type(new_collection, "ARMATURE")

    if old_armature is None:
        raise RuntimeError(
            f"Old rig collection '{old_collection.name}' does not contain an armature."
        )

    if new_armature is None:
        raise RuntimeError(
            f"New rig collection '{new_collection.name}' does not contain an armature."
        )

    create_action(new_armature, action_name=f"{new_armature.name}_camera_transfer")

    copied_object_curves = copy_object_transform_animation(old_armature, new_armature)
    copied_constraints = copy_pose_bone_constraints(old_armature, new_armature)
    copied_pose_curves = copy_pose_bone_animation(old_armature, new_armature)
    copied_lens_curves = set_new_camera_focal_length_from_old_camera(old_collection, new_collection)

    # info(
    #     "Transferred camera rig data: "
    #     f"object_fcurves={copied_object_curves}, "
    #     f"pose_fcurves={copied_pose_curves}, lens_fcurves={copied_lens_curves}"
    # )


# COLLECTION SWAP AND FILE BACKUP
def make_unique_collection_name(name: str) -> str:
    if name not in bpy.data.collections:
        return name

    index = 1
    while True:
        candidate = f"{name}_{index:03d}"
        if candidate not in bpy.data.collections:
            return candidate
        index += 1


def create_shot_backup_version(shot_path: Path) -> Path:
    """
    Create a backup in sibling .versions directory using
    '<file_stem>_vXX<suffix>' naming, with XX starting at 01.

    Uses Blender save-copy with relative remap so linked library paths remain valid
    even when the backup lives in a nested folder.
    Returns the created backup path.
    """
    backup_dir = shot_path.parent / ".versions"
    backup_dir.mkdir(parents=True, exist_ok=True)

    escaped_stem = re.escape(shot_path.stem)
    escaped_suffix = re.escape(shot_path.suffix)
    version_pattern = re.compile(rf"^{escaped_stem}_v(\d+){escaped_suffix}$", re.IGNORECASE)

    latest_version = 0
    for existing_file in backup_dir.iterdir():
        if not existing_file.is_file():
            continue

        match = version_pattern.match(existing_file.name)
        if not match:
            continue

        latest_version = max(latest_version, int(match.group(1)))

    next_version = latest_version + 1
    backup_name = f"{shot_path.stem}_v{next_version:02d}{shot_path.suffix}"
    backup_path = backup_dir / backup_name

    # Use Blender's save-copy operator to create the backup, preserving relative library paths
    bpy.ops.wm.save_as_mainfile(filepath=str(backup_path), copy=True, relative_remap=True, check_existing=False)

    return backup_path


def rename_camera_objects_in_shot(scene: bpy.types.Scene, new_rig_blend: Path, new_rig_collection: str) -> str:
    new_rig_path = normalize_path(str(new_rig_blend))
    old_collections = [
        collection
        for collection in find_collections_by_name_suffix(scene, "_old")
        if get_collection_library_path(collection)
        and normalize_path(get_collection_library_path(collection)) != new_rig_path
    ]

    if len(old_collections) != 1:
        raise RuntimeError(
            f"Expected exactly one old rig collection ending in '_old', found {len(old_collections)}."
        )

    old_collection = old_collections[0]
    new_collection_name = old_collection.name.removesuffix("_old")
    new_collections = [
        collection
        for collection in find_collections_by_name(scene, new_collection_name)
        if get_collection_library_path(collection)
        and normalize_path(get_collection_library_path(collection)) == new_rig_path
    ]

    if len(new_collections) != 1:
        raise RuntimeError(
            f"Expected exactly one new rig collection matching '{new_collection_name}' from '{new_rig_collection}', found {len(new_collections)}."
        )

    new_cameras = [obj for obj in new_collections[0].all_objects if obj.type == "CAMERA"]
    old_cameras = [obj for obj in old_collection.all_objects if obj.type == "CAMERA"]
    if len(new_cameras) != 1:
        raise RuntimeError(
            f"Expected exactly one camera in new rig collection '{new_collections[0].name}', found {len(new_cameras)}."
        )
    if len(old_cameras) != 1:
        raise RuntimeError(
            f"Expected exactly one camera in old rig collection '{old_collection.name}', found {len(old_cameras)}."
        )

    old_camera = old_cameras[0]
    new_camera = new_cameras[0]
    original_name = old_camera.name
    old_camera.name = f"{original_name}_old"
    new_camera.name = original_name

    return f"Renamed camera objects: '{original_name}' and '{old_camera.name}'."

def swap_old_with_new(scene: bpy.types.Scene, old_collection: bpy.types.Collection, new_collection: bpy.types.Collection, target_new_name: str):
    """
    Swap the old camera rig collection with the new one in the scene.
    """
    try:
        transfer_camera_data(old_collection, new_collection)
    except RuntimeError as exc:
        if is_ignorable_library_runtime_error(exc):
            info(
                "Ignoring non-camera library runtime error during transfer: "
                f"{exc}"
            )
        else:
            raise

    original_parent = find_collection_parent(scene.collection, old_collection) or scene.collection

    # If old collection is directly linked (not override), unlink it from the scene tree.
    # Linked data-blocks are not editable and should not be renamed/hidden in-place.
    is_direct_linked = old_collection.library is not None and old_collection.override_library is None
    if is_direct_linked:
        removed = unlink_collection_from_scene_tree(scene.collection, old_collection)
        if not removed:
            raise RuntimeError(f"Could not unlink old collection '{old_collection.name}'.")
    else:
        # Hide the old rig from viewport/render.
        old_collection.hide_viewport = True
        old_collection.hide_render = True

        # Add "_old" suffix to the old rig, then rename new -> old original name.
        old_new_name = make_unique_collection_name(f"{old_collection.name}_old")
        old_collection.name = old_new_name
    new_collection.name = target_new_name

    # Ensure the new collection is linked to the parent collection of the original rig and visible
    if new_collection.name in scene.collection.children and original_parent != scene.collection:
        scene.collection.children.unlink(new_collection)

    if new_collection.name not in original_parent.children:
        original_parent.children.link(new_collection)

    new_collection.hide_viewport = False
    new_collection.hide_render = False

    # Find the camera of the new rig and set it active for the scene
    for obj in new_collection.all_objects:
        if obj.type == "CAMERA":
            scene.camera = obj


# PER-SHOT PROCESSING
def process_shot_file(
    shot_path: Path,
    new_rig_blend: Path,
    new_rig_collection: str,
    old_rig_paths: set[str],
    old_rig_name_pattern: str,
    dry_run: bool,
    rename_camera_objects: bool,
    purge_unused_data: bool,
) -> tuple[bool, str]:

    path_split = shot_path.parts
    info(f"Processing shot: {path_split[-4]}/{path_split[-3]}/{path_split[-2]}/{path_split[-1]}")

    # Open the shot file
    try:
        bpy.ops.wm.open_mainfile(filepath=str(shot_path), load_ui=True)
    except RuntimeError as exc:
        info(f"RuntimeError during open shot: {exc}")
        if is_corrupted_packed_linked_datablock_error(exc):
            return False, f"Corrupted packed linked datablock error during open shot: {exc}"

        if not is_ignorable_library_runtime_error(exc):
            raise

        current_file = bpy.data.filepath or ""
        current_file_normalized = normalize_path(current_file) if current_file else ""
        target_file_normalized = normalize_path(str(shot_path))

        # Blender may raise a non-fatal library runtime error while still loading the requested file.
        # Continue only if the target file is actually loaded.
        if current_file_normalized == target_file_normalized and bpy.context.scene is not None:
            info("Ignored non-camera library runtime error during open shot; continuing processing.")
            _log_missing_libraries()
        else:
            return True, f"Ignored non-camera library runtime error during open shot (skipped shot): {exc}"

    scene = bpy.context.scene
    if scene is None:
        return False, "No active scene after open_mainfile."

    if rename_camera_objects:
        if dry_run:
            rename_camera_objects_in_shot(scene, new_rig_blend, new_rig_collection)
            return True, "Dry run: camera objects can be renamed."

        message = rename_camera_objects_in_shot(scene, new_rig_blend, new_rig_collection)
        save_shot_file(shot_path, purge_unused_data)
        return True, f"{message} Saved."

    # Check if the new rig is already present in the scene - if so, skip processing
    already_has_new_rig = has_new_rig_instance(scene, new_rig_blend, new_rig_collection)
    if already_has_new_rig:
        if purge_unused_data and not dry_run:
            save_shot_file(shot_path, purge_unused=True)
            return True, "New camera rig already present (skipped). Purged unused data and saved."
        return True, "New camera rig already present (skipped)."

    old_instances = find_old_rig_instances(scene, old_rig_paths, old_rig_name_pattern)
    if not old_instances:
        if purge_unused_data and not dry_run:
            save_shot_file(shot_path, purge_unused=True)
            return True, "No matching old camera rig instance found (skipped). Purged unused data and saved."
        return True, "No matching old camera rig instance found (skipped)."

    instance_objects = find_old_rig_collection_instances(scene, old_rig_paths)
    if instance_objects:
        names = ", ".join(obj.name for obj in instance_objects)
        return False, f"Unsupported collection-instance objects referencing old rig were found: {names}"

    if len(old_instances) != 1:
        return False, f"Expected exactly one old camera rig instance, found {len(old_instances)}."

    if dry_run:
        return True, "Dry run: one old camera rig instance detected and preflight checks passed."

    # Perform the camera rig replacement and save the shot file
    try:
        backup_path = create_shot_backup_version(shot_path)
        linked_collection = link_collection(scene, new_rig_collection, new_rig_blend)
        new_override_collection = create_override_from_linked_collection(scene, linked_collection)
        unlink_collection_from_scene_tree(scene.collection, linked_collection)

        old_collection = old_instances[0]
        target_new_name = old_collection.name
        swap_old_with_new(scene, old_collection, new_override_collection, target_new_name)

        try:
            rename_message = rename_camera_objects_in_shot(
                scene,
                new_rig_blend,
                new_rig_collection,
            )
        except RuntimeError as exc:
            info(f"Camera object rename skipped: {exc}")
            rename_message = "Camera object rename skipped."

        save_shot_file(shot_path, purge_unused_data)
        return True, f"Replaced 1 old camera rig instance. {rename_message} Saved."
    except RuntimeError as exc:
        info(f"RuntimeError during shot processing/save: {exc}")
        if is_corrupted_packed_linked_datablock_error(exc):
            return False, f"Corrupted packed linked datablock error during shot processing/save: {exc}"

        if is_ignorable_library_runtime_error(exc):
            return True, f"Ignored non-camera library runtime error during shot processing/save (skipped save): {exc}"

        raise


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = create_parser().parse_args(argv)

    if not bpy.app.background:
        raise RuntimeError(
            "This script is intended for Blender background mode only. "
            "Run with: blender --background --python <script> -- <args>."
        )

    shots_roots = [Path(path).expanduser().resolve() for path in args.target_directory]
    old_rigs_root = Path(args.old_rigs_root).resolve()
    new_rig_blend = Path(os.path.abspath(os.fspath(args.new_rig_blend)))    # keeps the drive-letter style provided by the user (for example K:\\...) instead of UNC resolving
    new_rig_collection = args.new_rig_collection.strip() or new_rig_blend.stem

    for shots_root in shots_roots:
        if not shots_root.exists() or not shots_root.is_dir():
            raise FileNotFoundError(f"Shots-root does not exist or is not a directory: {shots_root}")
    if not old_rigs_root.exists() or not old_rigs_root.is_dir():
        raise FileNotFoundError(f"Old-rigs-root does not exist or is not a directory: {old_rigs_root}")
    if not new_rig_blend.exists() or not new_rig_blend.is_file():
        raise FileNotFoundError(f"New-rig-blend does not exist or is not a file: {new_rig_blend}")

    # Find all old rig .blend files under old_rigs_root
    old_rig_files = discover_old_rig_blend_files(old_rigs_root, recursive=True, new_rig_blend=new_rig_blend)
    old_rig_paths_normalized = {normalize_path(str(p)) for p in old_rig_files}
    if not old_rig_paths_normalized and not args.old_rig_name_pattern:
        raise RuntimeError("No old rig .blend files were found under old-rigs-root (excluding hidden paths and new-rig-blend).")

    for file in old_rig_files:
        info(f"Found old rig .blend file: {file}")

    shots = discover_blend_files(args)
    shots = [shot for shot in shots if not is_versioned_backup_blend(shot)]
    if not shots:
        info(f"No .blend files found under: {', '.join(str(path) for path in shots_roots)}")
        return

    # Process each shot file
    stats = ProcessingStats()
    for shot_path in shots:
        stats.processed += 1
        try:
            ok, message = process_shot_file(
                shot_path=shot_path,
                new_rig_blend=new_rig_blend,
                new_rig_collection=new_rig_collection,
                old_rig_paths=old_rig_paths_normalized,
                old_rig_name_pattern=args.old_rig_name_pattern,
                dry_run=args.dry_run,
                rename_camera_objects=args.rename_camera_objects,
                purge_unused_data=args.purge_unused_data,
            )

            if ok and "skipped" in message.lower():
                stats.skipped += 1
            elif ok:
                stats.replaced += 1
            else:
                stats.failed += 1

            if ok and "skipped" not in message.lower():
                message = f"✅ {message}"
            elif ok:
                message = f"⚠️ {message}"
            else:
                message = f"❌ {message}"
            info(message)
        except Exception as exc:
            stats.failed += 1
            info(f"❌ FAILED - {type(exc).__name__}: {exc}")

    info(
        "✅ Done. "
        f"processed={stats.processed}, replaced={stats.replaced}, "
        f"skipped={stats.skipped}, failed={stats.failed}"
    )


if __name__ == "__main__":
    main()