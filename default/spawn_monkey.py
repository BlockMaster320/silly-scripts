"""Replace the current scene objects with one monkey mesh.

This is deliberately a single-file script. In batch mode the launcher opens
each selected .blend file before calling main(), then saves it afterward.
"""

import argparse
import sys
import bpy


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--monkey-name",
        default="Suzanne",
        help="Name to give the generated monkey object.",
    )
    return parser

def spawn_monkey(monkey_name: str) -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.mesh.primitive_monkey_add()
    bpy.context.object.name = monkey_name
    print(f"[SCRIPT] Created monkey object: {monkey_name}", flush=True)

def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = create_parser().parse_args(argv)

    spawn_monkey(args.monkey_name)


if __name__ == "__main__":
    main()
