"""A choices argument becomes a QComboBox."""

import argparse
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=["PNG", "JPEG", "EXR"], default="PNG", help="Output image format.")
    return parser


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = create_parser().parse_args(arguments)
    print(f"Selected format: {args.format}", flush=True)


if __name__ == "__main__":
    main()
