"""Run a single-file Blender script against each path in a launcher manifest."""

from __future__ import annotations

import json
import runpy
import sys
import traceback
from pathlib import Path

import bpy


def count_datablocks() -> int:
    total = 0
    for collection_name in dir(bpy.data):
        if collection_name.startswith("_"):
            continue
        data_collection = getattr(bpy.data, collection_name)
        if isinstance(data_collection, bpy.types.bpy_prop_collection):
            total += len(data_collection)
    return total


def purge_unused_data(keep_linked: bool = True) -> int:
    before = count_datablocks()
    bpy.data.orphans_purge(
        do_local_ids=True,
        do_linked_ids=not keep_linked,
        do_recursive=True,
    )
    return before - count_datablocks()


def run_batch(manifest_path: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    script_path = Path(manifest["script_path"]).resolve()
    script_arguments = [str(value) for value in manifest["script_arguments"]]
    files = [Path(value).resolve() for value in manifest["files"]]
    if str(script_path.parent) not in sys.path:
        sys.path.insert(0, str(script_path.parent))

    failures = 0
    for index, blend_path in enumerate(files, 1):
        print(f"[SCRIPT] Processing {index}/{len(files)}: {blend_path}", flush=True)
        try:
            result = bpy.ops.wm.open_mainfile(filepath=str(blend_path), load_ui=True)
            if "FINISHED" not in result:
                raise RuntimeError(f"Blender did not open {blend_path}: {result}")

            # Supply the target script with a normal Python argv. Compatible
            # scripts parse their own options inside main().
            sys.argv = [str(script_path), *script_arguments]
            namespace = runpy.run_path(
                str(script_path), run_name=f"_launcher_single_file_{index}"
            )
            entry_point = namespace.get("main")
            if not callable(entry_point):
                raise RuntimeError("The target script does not define a callable main().")
            try:
                entry_point()
            except SystemExit as exc:
                if exc.code not in (None, 0):
                    raise RuntimeError(f"The target script exited with status {exc.code}.") from exc

            if manifest.get("purge_unused_data"):
                removed = purge_unused_data(keep_linked=True)
                print(f"[SCRIPT] Purged {removed} unused data-block(s).", flush=True)

            result = bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), check_existing=False)
            if "FINISHED" not in result:
                raise RuntimeError(f"Blender did not save {blend_path}: {result}")
            print(f"[SCRIPT] Saved {blend_path}", flush=True)
        except Exception as exc:
            failures += 1
            print(f"[SCRIPT] ERROR {blend_path}: {exc}", file=sys.stderr, flush=True)
            for line in traceback.format_exc().splitlines():
                print(f"[SCRIPT] {line}", file=sys.stderr, flush=True)

    print(
        f"[SCRIPT] Batch complete: {len(files) - failures} saved, {failures} failed.",
        flush=True,
    )
    return 1 if failures else 0


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if len(argv) != 2 or argv[0] != "--manifest":
        raise SystemExit("Expected --manifest <path> after Blender's -- separator.")
    raise SystemExit(run_batch(Path(argv[1])))


if __name__ == "__main__":
    main()
