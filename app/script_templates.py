"""Create standalone script files without overwriting existing work."""

from pathlib import Path
from typing import Literal

from . import shot_selection

TemplateKind = Literal["blank", "batch"]


def template_source(kind: TemplateKind) -> str:
    filename = {"blank": "blank_script.py", "batch": "batch_script.py"}[kind]
    source = (Path(__file__).parent / "templates" / filename).read_text(encoding="utf-8")
    if kind == "batch":
        # Embed the same validator used by the launcher so new scripts have no
        # dependency on the app package or the launcher's installation folder.
        helper = Path(shot_selection.__file__).read_text(encoding="utf-8")
        source = source.replace("from app.shot_selection import parse_shot_selection", helper)
    return source


def create_script(folder: Path, name: str, kind: TemplateKind) -> Path:
    name = name.strip()
    if not name or any(character in name for character in '/\\<>:"|?*'):
        raise ValueError("Enter a filename without a folder path or special filename characters.")
    if name.endswith((" ", ".")) or any(ord(character) < 32 for character in name):
        raise ValueError("The filename contains invalid characters or ends with a dot.")
    if not Path(name).suffix:
        name += ".py"
    if Path(name).suffix.lower() != ".py" or name.lower() == "__init__.py":
        raise ValueError("Choose a .py filename other than __init__.py.")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if name.split(".")[0].upper() in reserved:
        raise ValueError("This filename is reserved on Windows. Choose another name.")
    folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"Choose an existing scripts folder in Settings first: {folder}")
    path = folder / name
    source = template_source(kind)
    compile(source, str(path), "exec")
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    return path
