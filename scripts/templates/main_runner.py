"""Execute a parserless script's main() once, regardless of its __main__ guard."""

import runpy
import sys
from pathlib import Path


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    if not argv:
        raise ValueError("Expected the target script path.")
    script_path = Path(argv[0]).resolve()
    sys.path.insert(0, str(script_path.parent))
    sys.argv = [str(script_path), *argv[1:]]
    namespace = runpy.run_path(str(script_path), run_name="_launcher_single_file")
    entry_point = namespace.get("main")
    if not callable(entry_point):
        raise RuntimeError("The target script does not define a callable main().")
    entry_point()


if __name__ == "__main__":
    main()
