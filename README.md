# SillyScripts

SillyScripts is a desktop launcher for Python and Blender scripts. Choose a script, fill in its parameters, and run it without assembling command-line commands. It can also run a script against multiple `.blend` files, handling file discovery, opening, and saving for you.

## Installation

1. Download the ZIP from this repository's **Releases** page.
2. Extract the archive.
3. Open `SillyScripts.exe` from the extracted folder. Keep its supporting files alongside it.

Select the Blender and Python executables in **Settings**.

## User guide

Select a script from the library panel on the left. Libraries are grouped by folder name; switching scripts preserves their controls and logs and does not interrupt a running process.

### Script tab

Displays the script description, execution settings, script parameters, and a command preview that you can copy to the clipboard.

- **Runtime:** Blender runs scripts with Blender's API; Python runs ordinary Python scripts. Blender is selected by default.
- **Run mode:** Single run executes the script once as it is. Batch mode uses Blender to open each selected `.blend` file, call the script, and save the file afterward.
- **Batch selection:** Choose a target directory, enable recursive discovery, and optionally exclude folders or hidden files. Include/exclude shots accepts lists such as `1,4-8,12`, matching numbers at the end of blend filenames. **Purge unused data** optionally removes unused data-blocks before saving.
- **Blender options:** Background mode runs without Blender's window. Disabling library override auto resync skips Blender's automatic override resync.
- **Parameters:** Fields marked `*` are required. Leave optional value fields empty to omit them. Folder/file controls open a picker; `+` adds another value where supported.
- **Run Script / Stop:** Start or stop the selected script. Different scripts can run concurrently; the same script cannot run twice simultaneously.

Batch mode saves over the selected files, so use copies when testing a script.

### Log tab

Shows live output and the current/latest log path for the selected script. Each execution creates a separate timestamped log file. **Clear View** only clears the visible buffer; **Open Log Folder** opens the saved logs.

Output filtering uses case-insensitive substring matching. By default, `[SCRIPT]` filters both the displayed output and output saved to the log. Disable **Also filter output saved to the log file** to retain complete diagnostic output.

### Settings tab

Use **Add library** to select one or more script directories, or the remove button to remove a library. Only `.py` files directly inside each directory are loaded; `__init__.py` is ignored. Press **Refresh Scripts** after adding or editing files. Select discovered Python/Blender installations or browse for executables.

Global preferences are remembered. Script and batch parameter values are saved when you run a script and restored when it is loaded again.

## For scripters

Use **Create blank script** or **Create blank batch script** in the left panel as the starting point for new scripts. Both create an editable template with the launcher-compatible structure already in place.

- **Create blank script:** Recommended when each file can be processed independently, without sharing context between files. Write the changes for the currently open file, then choose the launcher's **Batch mode** to run them on multiple `.blend` files. The launcher handles discovery, opening, and saving.
- **Create blank batch script:** Recommended when processing needs context across multiple files, such as shared results or comparisons. This template owns the discovery and processing loop, so you can retain context throughout it. Execute it with **Single run**; its own code handles the batch.

A parameterless script only needs a callable `main()` taking no arguments:

```python
"""Description displayed in SillyScripts."""

def main():
    print("[SCRIPT] Hello", flush=True)
```

The launcher calls `main()` directly for parserless scripts. An optional `if __name__ == "__main__": main()` guard is also supported.

To expose parameters, add `create_parser()` returning an `argparse.ArgumentParser`. Parse arguments inside `main()` and include the guard for single-run execution:

```python
import argparse
import sys

def create_parser():
    parser = argparse.ArgumentParser(description="Print a greeting.")
    parser.add_argument("--name", default="World", help="Name to greet")
    return parser

def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = create_parser().parse_args(argv)
    print(f"[SCRIPT] Hello, {args.name}!", flush=True)

if __name__ == "__main__":
    main()
```

The UI supports strings, integers, floats, choices, boolean actions, `pathlib.Path`, and `nargs="+"`. Names ending in `directory`, `dir`, or `folder` use folder pickers; other `Path` arguments use file pickers.

Optional parser metadata sets and, if requested, locks the run mode:

```python
parser.script_metadata = {
    "default_run_mode": "batch",  # "single" or "batch"
    "force_default_run_mode": True,
}
```

Without metadata, the default is an unlocked single run. For launcher batch mode, modify the currently open file in `main()`; the launcher handles opening and saving. `import bpy` at module level is supported, but keep Blender API calls inside functions. Inspection imports the module and calls `create_parser()` when present, so keep actual work out of module-level code and only load trusted scripts.

See [DOCS.md](DOCS.md) for detailed development documentation.
