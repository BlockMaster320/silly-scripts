"""Demonstrate the string fallback, numeric widgets, and boolean flags."""

import argparse
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="World", help="Name to greet; no explicit type means a string.")
    parser.add_argument("--count", type=int, default=3, help="Number of greetings.")
    parser.add_argument("--scale", type=float, default=1.0, help="Example floating-point value.")
    parser.add_argument("--verbose", action="store_true", help="Print extra information.")
    parser.add_argument("--no-cache", dest="cache", action="store_false", help="Uncheck Cache to disable it.")
    return parser


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = create_parser().parse_args(arguments)
    for index in range(args.count):
        print(f"Hello, {args.name}! ({index + 1}/{args.count}, scale={args.scale})", flush=True)
    if args.verbose:
        print(f"Verbose output: cache={args.cache}", flush=True)


if __name__ == "__main__":
    main()
