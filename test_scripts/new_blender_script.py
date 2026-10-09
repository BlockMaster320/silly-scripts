"""A minimal Blender script. Add your own work inside main()."""

import argparse
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", default="Hello from Blender!", help="Message to print to the console.")
    return parser


def main() -> None:
    # Blender owns arguments before '--'; Python receives only script arguments.
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = create_parser().parse_args(argv)
    print(args.message, flush=True)

    # Import bpy here when adding Blender operations, so inspection also works
    # with ordinary Python:
    # import bpy
    # Add your Blender code here.


if __name__ == "__main__":
    main()
