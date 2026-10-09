"""Show required strings and an explicitly supplied required integer."""

import argparse
import sys


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="A nonempty label is required.")
    parser.add_argument("--frame-end", type=int, required=True, help="Check Provide value, then enter the last frame.")
    return parser


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = create_parser().parse_args(arguments)
    print(f"{args.label}: last frame = {args.frame_end}")


if __name__ == "__main__":
    main()
