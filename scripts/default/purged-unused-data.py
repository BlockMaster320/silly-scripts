"""Script for purging unused data (the purging itself is performed using the batch mode wrapper code)."""

import argparse


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.script_metadata = {
		"default_run_mode": "batch"
	}

    return parser


def main() -> None:
    pass

if __name__ == "__main__":
    main()
