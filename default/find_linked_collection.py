"""Find project .blend files linking collections from same-named asset files.

Collection names come from a text file, one per line; blank lines and lines
starting with '#' are ignored. Asset .blend files are recursively found under
--asset-dir by matching each filename to its collection name. Results are
grouped by collection and asset path and printed, with an optional text report.

Example:

	blender --background --python find_linked_collection.py -- `
		--asset-dir "X:/project/assets" `
		--collections "X:/project/collections.txt" `
		--target-directory "X:/project/shots" `
		--exclude-folders ".versions" `
		--include-shots "100-250" `
		--output "X:/project/linked_collection_report.txt"

Discovery supports multiple target directories, folder exclusions, shot-number
inclusion/exclusion ranges, hidden-entry filtering, and recursion controls.
Scanned files are read-only by default. --purge-unused-data opts into purging
unused local data-blocks and saving each scanned file.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import sys
from pathlib import Path

import bpy


INFO_PREFIX = "[SCRIPT]"


def info(message: str) -> None:
	print(f"{INFO_PREFIX} {message}", flush=True)


def warning(message: str) -> None:
	print(f"{INFO_PREFIX}[WARNING] {message}", flush=True)


def create_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Find project .blend files linking collections from same-named asset files."
	)

	parser.add_argument(
		"--asset-dir",
		required=True,
		type=Path,
		help="Directory recursively containing asset .blend files named after the collections.",
	)

	parser.add_argument(
		"--collections",
		required=True,
		type=Path,
		help="Text file with one collection name per line.",
	)

	parser.add_argument(
		"--search-dir", "--target-directory",
		dest="target_directory",
		nargs="+",
		required=True,
		type=Path,
		help="Directory recursively containing .blend files to inspect.",
	)

	parser.add_argument("--exclude-folders", action="append", help="Folders excluded with their subfolders; repeatable.")
	parser.add_argument("--include-shots", "--include_shots", action="append", help="Include filename number suffixes/ranges, e.g. 1,4-8; repeatable.")
	parser.add_argument("--exclude-shots", "--exclude_shots", action="append", help="Exclude filename number suffixes/ranges, e.g. 2,6-7; repeatable.")
	parser.add_argument("--ignore-hidden-folders", action=argparse.BooleanOptionalAction, default=True, help="Ignore hidden folders and files (default: enabled).")
	parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True, help="Search subfolders recursively (default: enabled).")
	parser.add_argument("--purge-unused-data", action="store_true", help="Purge unused local data-blocks and save each scanned file (default: disabled).")

	parser.add_argument(
		"--output",
		type=Path,
		help="Text file the final per-collection result list is written to.",
	)

	parser.add_argument(
		"--case-sensitive",
		action="store_true",
		help="Match collection names case-sensitively. By default matching is case-insensitive.",
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


def load_collection_names(path: Path) -> list[str]:
	names: list[str] = []
	seen: set[str] = set()

	with path.open("r", encoding="utf-8-sig") as handle:
		for raw_line in handle:
			name = raw_line.strip()

			if not name or name.startswith("#"):
				continue

			key = os.path.normcase(name)
			if key in seen:
				continue

			seen.add(key)
			names.append(name)

	return names


def normalized_path(path: Path | str) -> Path:
	return Path(os.path.normpath(os.path.abspath(os.fspath(path))))


def path_key(path: Path | str) -> str:
	return os.path.normcase(os.path.normpath(str(normalized_path(path))))


def same_path(a: Path | str, b: Path | str) -> bool:
	try:
		resolved_a = Path(a).resolve()
		resolved_b = Path(b).resolve()
		if os.path.normcase(os.path.normpath(str(resolved_a))) == os.path.normcase(os.path.normpath(str(resolved_b))):
			return True
	except Exception:
		pass

	return path_key(a) == path_key(b)


def same_name(a: str, b: str, case_sensitive: bool) -> bool:
	if case_sensitive:
		return a == b

	return os.path.normcase(a) == os.path.normcase(b)


def strip_blender_duplicate_suffix(name: str) -> str:
	stem, separator, suffix = name.rpartition(".")

	if separator and len(suffix) == 3 and suffix.isdigit():
		return stem

	return name


def same_blender_id_name(a: str, b: str, case_sensitive: bool) -> bool:
	return same_name(a, b, case_sensitive) or same_name(strip_blender_duplicate_suffix(a), b, case_sensitive)


def count_datablocks() -> int:
	total = 0
	for collection_name in dir(bpy.data):
		if collection_name.startswith("_"):
			continue
		data_collection = getattr(bpy.data, collection_name)
		if isinstance(data_collection, bpy.types.bpy_prop_collection):
			total += len(data_collection)
	return total


def purge_unused_data() -> int:
	before = count_datablocks()
	bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
	return before - count_datablocks()


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


def discover_asset_blend_files(asset_root: Path) -> list[Path]:
	asset_args = argparse.Namespace(
		target_directory=[asset_root],
		exclude_folders=None,
		include_shots=None,
		exclude_shots=None,
		ignore_hidden_folders=True,
		recursive=True,
	)
	return discover_blend_files(asset_args)


def find_asset_files(asset_root: Path, collection_names: list[str], case_sensitive: bool) -> dict[str, list[Path]]:
	assets: dict[str, list[Path]] = {}
	files = discover_asset_blend_files(asset_root)

	for name in collection_names:
		matches = [path for path in files if same_name(path.stem, name, case_sensitive)]
		if matches:
			assets[name] = matches
		else:
			warning(f"No asset .blend file found for '{name}' under {asset_root}")

	return assets


def blender_library_absolute_path(library: bpy.types.Library) -> Path:
	return normalized_path(bpy.path.abspath(library.filepath, library=library))


def collection_reference_library(collection: bpy.types.Collection) -> bpy.types.Library | None:
	if collection.library is not None:
		return collection.library

	override = getattr(collection, "override_library", None)
	reference = getattr(override, "reference", None)
	library = getattr(reference, "library", None)

	return library


def collection_reference_name(collection: bpy.types.Collection) -> str:
	override = getattr(collection, "override_library", None)
	reference = getattr(override, "reference", None)
	reference_name = getattr(reference, "name", None)

	return reference_name if reference_name else collection.name


def file_linked_collections(path: Path, asset_files: dict[str, list[Path]], case_sensitive: bool, purge_unused: bool = False) -> dict[tuple[str, Path], list[str]]:
	bpy.ops.wm.open_mainfile(
		filepath=str(path),
		load_ui=True,
	)

	matches: dict[tuple[str, Path], list[str]] = {}

	for collection in bpy.data.collections:
		library = collection_reference_library(collection)
		if library is None:
			continue

		name = collection_reference_name(collection)
		try:
			library_path = blender_library_absolute_path(library)
		except Exception:
			continue

		for wanted, paths in asset_files.items():
			if not same_blender_id_name(name, wanted, case_sensitive):
				continue
			for asset_path in paths:
				if same_path(library_path, asset_path):
					matches.setdefault((wanted, asset_path), []).append(collection.name)

	if purge_unused:
		removed = purge_unused_data()
		info(f"Purged {removed} unused local data-block(s) from {path}")
		result = bpy.ops.wm.save_as_mainfile(filepath=str(path), check_existing=False)
		if "FINISHED" not in result:
			raise RuntimeError(f"Blender did not save {path}: {result}")

	return matches


def write_report(output_path: Path, asset_root: Path, search_roots: list[Path], results: dict[str, dict[Path, list[Path]]]) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)

	with output_path.open("w", encoding="utf-8") as handle:
		handle.write(f"Asset dir:  {asset_root}\n")
		handle.write(f"Search dirs: {', '.join(str(path) for path in search_roots)}\n")
		handle.write("\n")

		for collection_name, asset_matches in results.items():
			if not asset_matches:
				handle.write(f"{collection_name} (0)\n  none\n\n")
			for asset_path, paths in asset_matches.items():
				handle.write(f"{collection_name} [{asset_path}] ({len(paths)})\n")
				if not paths:
					handle.write("  none\n")
				for path in paths:
					handle.write(f"  {path}\n")
				handle.write("\n")


def release_loaded_blend() -> None:
	try:
		bpy.ops.wm.read_factory_settings(use_empty=True)
	except Exception as exc:
		warning(f"Could not release loaded .blend data before exit: {exc}")


def main() -> None:
	try:
		argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
		parser = create_parser()
		args = parser.parse_args(argv)

		asset_root = normalized_path(args.asset_dir)
		search_roots = [normalized_path(path) for path in args.target_directory]
		collections_file = normalized_path(args.collections)
		output_path = normalized_path(args.output) if args.output else None

		if not asset_root.is_dir():
			raise RuntimeError(f"Asset directory does not exist:\n    {asset_root}")

		for search_root in search_roots:
			if not search_root.is_dir():
				raise RuntimeError(f"Search directory does not exist:\n    {search_root}")

		if not collections_file.is_file():
			raise RuntimeError(f"Collections file does not exist:\n    {collections_file}")

		collection_names = load_collection_names(collections_file)
		if not collection_names:
			raise RuntimeError("Collections file contains no collection names.")

		asset_files = find_asset_files(asset_root, collection_names, args.case_sensitive)
		asset_paths = [path for paths in asset_files.values() for path in paths]
		files = [path for path in discover_blend_files(args) if all(not same_path(path, asset) for asset in asset_paths)]
		results: dict[str, dict[Path, list[Path]]] = {
			name: {path: [] for path in asset_files.get(name, [])} for name in collection_names
		}
		matched_file_count = 0

		info(f"Asset dir:   {asset_root}")
		info(f"Collections: {collections_file} ({len(collection_names)})")
		info(f"Search dirs: {', '.join(str(path) for path in search_roots)}")
		info(f"Blend files found: {len(files)}")

		for index, path in enumerate(files, start=1):
			info("")
			info(f"[{index}/{len(files)}] Checking: {path}")
			try:
				matches = file_linked_collections(
					path,
					asset_files,
					case_sensitive=args.case_sensitive,
					purge_unused=args.purge_unused_data,
				)
			except RuntimeError as exc:
				warning(f"Could not inspect '{path}': {exc}")
				continue

			if not matches:
				continue

			matched_file_count += 1
			for (collection_name, asset_path), linked_names in matches.items():
				results[collection_name][asset_path].append(path)
				info(f"MATCH [{collection_name} | {asset_path}]: " + ", ".join(sorted(set(linked_names))))

		info("")
		info("============================================")
		info(f"Files scanned: {len(files)}")
		info(f"Files matched: {matched_file_count}")
		info("============================================")

		for collection_name, asset_matches in results.items():
			info("")
			if not asset_matches:
				info(f"{collection_name} (0)")
				info("  none")
			for asset_path, paths in asset_matches.items():
				info(f"{collection_name} [{asset_path}] ({len(paths)})")
				if not paths:
					info("  none")
				for path in paths:
					info(f"  {path}")

		if output_path is not None:
			write_report(output_path, asset_root, search_roots, results)
			info("")
			info(f"Report written to: {output_path}")
	except Exception as exc:
		print(f"{INFO_PREFIX}[ERROR] {exc}", flush=True)
		import traceback

		traceback.print_exc()
		raise SystemExit(1)
	finally:
		release_loaded_blend()


if __name__ == "__main__":
	main()