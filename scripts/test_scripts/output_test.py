"""Exercise live output, filtering, stderr, Stop, and nonzero exit codes."""

import argparse
import sys
import time


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=20, help="Number of progress updates.")
    parser.add_argument("--delay", type=float, default=0.25, help="Seconds between updates.")
    parser.add_argument("--message", default="Processing", help="Text printed alongside [SCRIPT].")
    parser.add_argument("--fail", action="store_true", help="Exit with code 2 after printing output.")
    return parser


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = create_parser().parse_args(arguments)
    for index in range(args.steps):
        print(f"Generic diagnostic line {index + 1}", flush=True)
        print(f"[SCRIPT] {args.message} {index + 1}/{args.steps}", flush=True)
        print(f"Diagnostic stderr line {index + 1}", file=sys.stderr, flush=True)
        if index % 3 == 0:
            print("[SCRIPT] matching stderr marker", file=sys.stderr, flush=True)
        time.sleep(max(0.0, args.delay))
    # No newline: verifies that the final partial line is retained.
    print("[SCRIPT] Finished", end="", flush=True)
    if args.fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
