"""Shared shot-list validation, also embedded in generated standalone scripts."""

import re


def parse_shot_selection(text: str) -> list[tuple[int, int]]:
    """Parse comma-separated nonnegative shot numbers and inclusive ranges.

    Keep ranges as pairs rather than expanding them into potentially huge lists.
    Leading zeros are accepted; descending ranges and empty entries are errors.
    """
    ranges: list[tuple[int, int]] = []
    for entry in text.split(","):
        match = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", entry)
        if not match:
            raise ValueError(f"Invalid shot entry {entry!r}. Use a list such as 1,4-8,12.")
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) is not None else start
        if start > end:
            raise ValueError(f"Shot range {entry.strip()!r} starts after it ends.")
        ranges.append((start, end))
    return ranges


def format_shot_selection(ranges: list[tuple[int, int]]) -> list[str]:
    return [str(start) if start == end else f"{start}-{end}" for start, end in ranges]
