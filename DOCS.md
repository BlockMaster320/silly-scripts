# SillyScripts

A local desktop frontend for running Python scripts directly or through Blender.
Built with Python 3, PySide6, Qt Widgets, and asynchronous `QProcess`; no shell,
web frontend, `.ui` files, or additional runtime dependencies.

## Setup and launch

Install Python 3.13, then run these commands from this repository in a terminal:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

Activation is optional. These equivalent commands work from Windows Command
Prompt and avoid any shell activation policy:

```bat
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

Run these commands from the `silly-scripts` repository root.
Python 3.12 is also supported and was used to validate this prototype on Windows.
The launch command after activation is always **`python main.py`**.

On Linux/macOS, use `python3 -m venv .venv`, then
`.venv/bin/python -m pip install -r requirements.txt` and
`.venv/bin/python main.py`. Those platforms were not exercised here.

## Build a Windows executable

From the activated environment in the repository root:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --clean --noconfirm BlenderScriptLauncher.spec
```

Launch `dist/BlenderScriptLauncher/BlenderScriptLauncher.exe`. Distribute the
entire `dist/BlenderScriptLauncher` folder, including `_internal`.
The spec includes the stylesheet, SVG icons, script templates, and the
shot-selection source used when generating batch scripts. These files are read
from disk at runtime, so importing Python modules alone does not bundle them.
Build from the spec to preserve these settings; passing `main.py` with the same
`--name` regenerates the spec.

## Try the application

1. The initial library is the `scripts/default` folder. Put your scripts there to load
   them automatically. The bundled examples in `scripts/test_scripts` are not loaded by
   default; add that folder in **Settings** if you want to use them. Select
   folders with **Browse**, use **+ Add library** to load more than one, and use
   **−** to remove a library. Each library is scanned one level deep;
   `__init__.py` is ignored. Use **Refresh Scripts** after editing files.
2. Python and Blender installations are discovered automatically, with version
   probes performed asynchronously. Both selectors support manual paths and
   **Browse**. Python discovery checks the current interpreter, PATH, and Windows
   `py -0p` installations. Blender discovery checks PATH and common
   `Program Files/Blender Foundation/Blender*/blender.exe` locations.
   Blender automatically selects the newest detected version, including when a
   newer installation is found after startup. Choosing an executable manually
   keeps that selection for the current session.
3. Select `basic_types`, keep **Runtime: Python**, and press **Run**. `Name` is a
   string field even though its argparse definition has no `type=`. `Count` and
   `Scale` are numeric controls. `choices` demonstrates a format dropdown.
4. Optional value arguments are included only when a value is provided; leave a
   text field blank or a picker/choice unselected to omit it and let the script
   apply its default. Required numeric arguments without defaults use **Provide
   value**, so an untouched zero is not mistaken for a supplied required value.
   Required controls have a `*` marker.
5. Boolean controls represent the resulting Python boolean. A checked
   `store_true` control passes its flag. An unchecked `store_false` control passes
   its flag; for example, unchecking `Cache` emits `--no-cache`.
6. For a script that edits the currently open Blender scene, choose **Batch .blend
   files** in **Run mode**. The script's own parameters remain visible alongside
   the batch file-selection controls. `scripts/default/spawn_monkey_batch.py` is a
   single-file example for this mode: it replaces scene objects with a named
   monkey, while the launcher opens and saves each selected file.
7. Output filtering defaults to `[SCRIPT]`, with both displayed-output and saved
   log filtering enabled. Matching is case-insensitive. Run `output_test` to see
   matching stdout and stderr lines live, plus launcher status messages. Switch to another script
   and run it concurrently, then return to see the first script's retained log.
8. **Stop** first requests termination. After three seconds the launcher calls
   `kill()` if necessary; **Force Stop** also makes that fallback available
   immediately. Closing the window stops processes and finalizes their logs
   before exiting, without blocking the Qt event loop.

The intentionally incompatible `missing_parser.py` remains visible with an
unavailable marker and an explanation. `required_values.py` demonstrates required
string and numeric fields. `output_test --fail` demonstrates a nonzero exit code.
The sidebar shows each selected library as a top-level group, with its discovered
scripts beneath it. Create buttons save into the selected script's library, or
the first library when no script is active. Adding/removing libraries and their
order persists through `QSettings`.

Directory/folder string parameters (names containing `directory`, `folder`,
`dir`, or their plurals) use **Select folder…** to open the native folder dialog.
Selected paths are displayed as labels; the Settings library path is read-only
and selected through **Browse**.
Arguments declared with `type=pathlib.Path` use **Select file…** and pass the
selected file path to the script.

All string parameters, including string choices and shot filters, have a **+**
button for adding rows and a **−** button for removing additional rows. Rows and
selected folders are retained independently for each script during the session.
Empty extra rows are ignored. Arguments using `action="append"` receive repeated
flags for strings, integers, floats, paths, and choices. Each append flag takes
one value; omit `nargs`. Script defaults remain in the parsed list and entered
values are appended to them. Other arguments using `nargs="+"`, `"*"`, or a fixed count receive multiple values after
one flag. For example:

```text
--tag "first value" --tag "second value"
--message "first message" "second message"
```

An existing scalar string argument keeps its argparse behavior: the last repeated
value wins. The form explains this when extra rows are added. Use `action="append"`
or `nargs="+"` in a script to consume every row. Older scalar batch-script
`--exclude-folders` arguments receive one combined comma-separated value.

## Create scripts from the sidebar

The two buttons below the script tree create new files in the folder selected
in Settings. Enter a filename when prompted; existing files are never overwritten.
The new script is immediately inspected and selected, with Runtime set to Blender.

- **Create blank script** creates a minimal `create_parser()` / `main()` template
  with a string `--message` argument accepting one or more messages to print. Add your
  Blender work inside `main()`.
- **Create blank batch script** creates a standalone script that discovers
  matching `.blend` files, then opens and saves each in place. Batch scripts
  use the default Blender launch options. Put scene changes in
  `process_file()`, at the marked point between opening and saving. The blank
  template does not edit scene data, although saving can update file metadata,
  file format, and Blender backups.

The generated batch template is a self-contained batch program. It is separate
from the launcher **Batch .blend files** run mode described below, which can
wrap an ordinary single-file script.

Any compatible `create_parser()` / `main()` script can also run in **Batch .blend
files** mode. Its `main()` is called once for each selected file after the launcher
opens it, and the launcher saves the file after `main()` succeeds. In this mode,
scripts should make changes to the open Blender scene and leave opening and saving
to the launcher. Batch file selection options are a separate group, so they do
not collide with the script's own parameters. The launcher discovers all matching
files before starting Blender, then a standalone runner processes them in order,
continues after per-file errors, and exits with a failure status if any file fails.

The batch parser exposes:

| Argument | Behavior |
| --- | --- |
| `--target-directory` | Required search root(s). Select folders with the dialog and use + for more. Overlapping roots are deduplicated. |
| `--exclude-folders` | Optional folder pickers; use + for multiple exclusions. The CLI also accepts folder names and legacy comma-separated lists. Names exclude matching folders anywhere within each target; paths exclude that subtree. |
| `--include-shots` | Optional list such as `1,4-8,12`, using inclusive ranges. |
| `--exclude-shots` | Optional list with the same format, applied after inclusion. |
| `--ignore-hidden-folders` | Required checkbox, initially enabled; filters hidden files too. |
| `--recursive` | Required checkbox, initially enabled; disabling searches only the target's immediate files. |
| `--purge-unused-data` | Optional checkbox, initially disabled; recursively purges unused data-blocks before saving each file and prints the number removed. Linked data-blocks are kept by default. |

Shot numbers are taken from digits at the **end of the filename stem**:
`scene_0042.blend` is shot 42, while `scene_0042_edit.blend` has no shot suffix.
Folder exclusions and hidden-file rules apply first, include shots next, and
exclude shots last. Without an include filter, files without shot numbers are
eligible. Symlinks and Windows directory junctions are skipped.

Arguments named `--include-shots` or `--exclude-shots` (and their underscore
spellings) use text fields with range validation and + for additional rows. The generated template
uses argparse `action="append"`, so entering `1,4-8,12` produces:

```text
--include-shots 1 --include-shots 4-8 --include-shots 12
```

The underscore aliases `--include_shots` / `--exclude_shots` are accepted too.
Existing scripts using scalar shot arguments receive one normalized comma-separated
value. Leave an optional filter blank to omit it entirely. Each required
boolean always emits an explicit flag: for example, `--recursive` when checked
and `--no-recursive` when unchecked.

Discovery validates the entire selection before opening any file. Per-file
errors are logged and processing continues, with a nonzero exit if any file
fails. The template uses Blender's
[`open_mainfile` and `save_as_mainfile` operators](https://docs.blender.org/UATEST/api/current/bpy.ops.wm.html).

## Add a compatible script

Place a `.py` file directly in any selected library folder and press **Refresh Scripts**.
For scripts with parameters, expose `create_parser()` and put actual work behind
the `__main__` guard:

```python
import argparse


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="World", help="Name to greet")
    parser.add_argument("--count", type=int, default=3)
    return parser


def main() -> None:
    args = create_parser().parse_args()
    for _ in range(args.count):
        print(f"Hello, {args.name}!", flush=True)


if __name__ == "__main__":
    main()
```

The first section of the Script tab displays `parser.description` as selectable
plain text. Optional launcher metadata can set the initial run mode and lock it:

```python
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Modify each selected Blender file.")
    parser.script_metadata = {
        "default_run_mode": "batch",  # "single" or "batch"
        "force_default_run_mode": True,
    }
    parser.add_argument("--name", default="World", help="Name to greet")
    return parser
```

Without metadata, the default is `"single"` and `force_default_run_mode` is `False`.
The default applies when the script is first loaded in a session; subsequent
selection changes preserve the user's choice. With `force_default_run_mode=True`, the
selector is disabled and always uses the specified mode. Batch mode uses Blender
and retains the existing batch file-selection controls. Metadata is not passed
as script arguments. Unknown metadata keys are ignored; invalid values produce
an inspection error in the UI.

Scripts without parameters can omit `create_parser()` and define a callable,
zero-argument `main()` instead:

```python
"""Description shown in the launcher."""

def main():
    print("[SCRIPT] Working on the current file", flush=True)
```

The launcher calls `main()` once for a single run or once per opened blend file
in batch mode. An optional `if __name__ == "__main__": main()` guard is also
supported and will not cause duplicate execution. Parserless scripts have no
script parameter controls and use their module docstring as the description.
Parser metadata requires `create_parser()`; parserless scripts use the normal
unlocked single-run default. Files with neither interface remain unavailable.

Inspection imports the module under a unique name and calls `create_parser()`
when present;
it never calls `main()` or runs the guarded block. Module-level statements still
execute. Keep costly work and runtime-specific imports, especially `import bpy`,
inside `main()` so ordinary Python can inspect the parser. Install any imports
needed for inspection in the launcher's virtual environment.

For a script intended specifically for Blender, parse only the script arguments
after Blender's `--` separator inside `main()`:

```python
import sys


def main() -> None:
    import bpy

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = create_parser().parse_args(argv)
    # Use args and bpy here.
```

For scripts supporting both runtimes, choose this argument extraction in Blender
and ordinary `sys.argv[1:]` in Python. The bundled examples use only named options
and accept either invocation style. Scripts using positional arguments should
preserve Python's own `--` end-of-options separator.

Select **Runtime: Blender**. **Run Blender in background** and **Disable library
override auto resync** both default to checked for every script and can be
unchecked independently.
The process receives the following argument layout:

```text
blender [--background] [--disable-liboverride-auto-resync] --python script.py -- <script arguments>
```

Those two switches are omitted for Python runs. Runtime, options, parameters,
and filter settings are retained separately for each script during the session.
Executables, scripts folder, and window geometry persist through `QSettings`.

Script parameter values are saved when **Run Script** is pressed, after argument
validation, to one central JSON file for all scripts:
`%APPDATA%\SillyScripts\script_parameters.json` on Windows. On macOS this is
`~/Library/Application Support/SillyScripts/script_parameters.json`; on Linux it
is `$XDG_CONFIG_HOME/SillyScripts/script_parameters.json` (defaulting to
`~/.config/SillyScripts/script_parameters.json`). Entries are keyed by normalized
absolute script paths, so same-named scripts in different libraries remain
independent. Entries include batch-selection parameter values, repeated fields,
and numeric value-presence checkboxes. They are loaded automatically when the
script is first loaded in an application
session. Switching scripts retains any unsaved edits for that session; only
another run updates the file. Runtime, Blender launch options, and output-filter
settings retain their existing session-only behavior.

The central file is written atomically, preserving other scripts' entries.
Removed parameters or
parameters whose type/action/choices/nargs changed use their parser defaults.
Unreadable or corrupt configs are reported and defaults remain available. A
corrupt central file is preserved rather than overwritten on Run. If the config
directory is read-only, execution still works, but the application reports that
its values could not be saved. Script libraries can be read-only. To reset a
script, close the application and remove its entry from the central file, then
reopen the application.

## Project structure

```text
silly-scripts/
├── main.py
├── requirements.txt
├── README.md
├── app/
│   ├── __init__.py
│   ├── main_window.py
│   ├── models.py
│   ├── settings.py
│   ├── settings_panel.py
│   ├── executable_discovery.py
│   ├── script_discovery.py
│   ├── script_inspector.py
│   ├── script_templates.py
│   ├── script_discovery.py
│   ├── shot_selection.py
│   ├── arguments.py
│   ├── parameter_widgets.py
│   ├── parameter_config.py
│   ├── string_widgets.py
│   ├── parameters_panel.py
│   ├── process_manager.py
│   └── log_panel.py
├── logs/
│   └── .gitkeep
├── scripts/
│   ├── default/
│   ├── test_scripts/
│   └── templates/
│       ├── blank_script.py
│       ├── batch_script.py
│       └── batch_runner.py
└── tests/
    ├── __init__.py
    ├── support.py
    ├── test_executables.py
    ├── test_inspection.py
    ├── test_parameters.py
    ├── test_processes.py
    ├── test_templates.py
    ├── test_string_widgets.py
    └── test_window.py
```

`batch_support.py` reuses the standalone template's parser and discovery rules;
`scripts/templates/batch_runner.py` opens each selected blend, invokes the ordinary
script entry point, and saves successful files. `scripts/default/spawn_monkey_batch.py`
demonstrates a single-file script that can use this mode.

`main_window.py` coordinates navigation and the three composed panels. It does
not own subprocess lifetimes. `script_inspector.py` is the single boundary for
imports and argparse internals, returning neutral dataclasses from `models.py`.
`parameter_widgets.py` builds controls from those models; `arguments.py` validates
their values and constructs argument lists. No shell quoting is needed.
`parameter_config.py` saves and restores per-script last-run values through
one atomic JSON file in the user config directory, without depending on Qt or
the process manager.
`script_discovery.py` scans each selected library independently, reports missing
directories without hiding scripts from other libraries, and supplies the folder
name used by the sidebar category.

`process_manager.py` owns one `QProcess` per running script and retains independent
runtime states even when the selected script or folder changes. It uses
[`QProcess` signals](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html)
for output, startup, failures, and completion. Separate incremental UTF-8 decoders
and line buffers handle stdout/stderr chunks; stderr is labeled in the UI.
`executable_discovery.py` also uses asynchronous `QProcess` for version probes.

## Logs

Every attempted launch after parameter validation creates a fresh file:

```text
logs/<script_name>/YYYY-MM-DD_HH-MM-SS_microseconds_random.log
```

The metadata includes the full script/executable paths, runtime, working
directory, start time, and a JSON argument list. By default, stdout/stderr lines
matching the configured filter are appended and flushed as they arrive; unchecking
**Also filter output saved to the log file** preserves complete output instead.
The filter applies to output lines, not run metadata or launcher notices. A final footer records time, exit code, and exit status, even
for handled launch failures. Failure to create a log prevents execution and is
reported in the UI; failure to write an existing log stops the process.

The display keeps the last 10,000 visible lines per script, with individual
display lines capped at 32,768 characters. New runs start a fresh visible buffer;
older files remain on disk. **Clear Log** clears only the display and its retained
buffer. **Open Log Folder** opens the latest run's folder using the desktop's
native file manager. Runtime log files and `.venv` are ignored by Git.

## Validation

From the activated environment in this directory:

```text
python -m unittest discover -s tests -v
```

The tests use the standard library's `unittest`, real Qt widgets in offscreen mode,
and real `QProcess` executions of ordinary Python scripts. They cover inspection
failures, guarded main functions, widget mappings, required fields, argparse
round trips, Blender argv ordering, concurrent runs, duplicate prevention,
termination, live filtering, fragmented UTF-8, stderr, partial final lines,
unique complete logs, launch failures, script switching, refresh, settings, and
shutdown. No Blender installation is needed for these tests.
Template tests also exercise standalone generation, shot/folder filtering,
hidden-file rules, recursion, and open/save calls through a mocked Blender API.
The string-control tests cover folder-dialog selection and cancellation, adding
and removing rows, parser round trips, defaults, and session state restoration.

## Prototype limitations

- Inspection runs in the GUI process and executes module-level code. Only use
  trusted scripts. Slow or blocking imports/factories can stall the UI. It is
  deliberately isolated behind `ScriptInspector` for a future helper process.
  Module side effects and imported sibling-module caching are not sandboxed.
- Supported argparse actions are scalar `store`, `store_true`, `store_false`,
  and `BooleanOptionalAction` with long options, with `str`/unspecified type,
  `int`, `float`, `pathlib.Path`, and choices. Single-value `append` actions
  and `nargs='+'` for supported types are supported. String values also support
  other multi-value `nargs` forms. Scalar positional arguments and `nargs='?'`
  are supported. Subparsers, mutually exclusive groups, repeated arguments,
  fixed-count numeric/path arguments, other custom types/actions, and custom option prefixes
  are reported as unavailable instead of generating unreliable arguments.
  The flag-only `const` form of optional scalar `nargs='?'` has no dedicated UI.
- Numeric widgets support signed 32-bit integers and finite floats within
  ±1 trillion, with eight decimal places. Out-of-range defaults are reported.
  Optional values without defaults are omitted while blank; an explicit empty
  string override of a nonempty script default is not exposed.
- Filtering applies to newly completed lines, including a final partial line at
  exit. Saved-log filtering uses the filter text captured when the run starts.
  Changing the filter does not reconstruct earlier output. Unterminated
  progress output is held until newline or process exit. Launcher status/error
  messages remain visible independently of the filter.
- stdout and stderr are saved in Qt arrival order; exact cross-stream ordering
  cannot be guaranteed. The UI assumes UTF-8 and replaces invalid sequences;
  original bytes remain on disk. Child Python output is configured unbuffered.
- Stop controls the direct process. Arbitrary grandchildren are not managed.
  Interactive stdin is unsupported. Scripts run with their own folder as the
  working directory.
- Script and batch parameter values from the last run survive restart in
  the central user JSON file. Moving a script changes its path key, so its saved
  values do not follow automatically. Other per-script settings/log buffers survive selection
  changes during the session. Logs have no rotation or history browser. Keep the
  project in a writable folder for `logs/`.
- Python execution and Qt integration have been tested on Windows with Python
  3.12 and 3.13. Blender command construction is tested; actual Blender file
  processing is checked through a mocked API rather than real .blend files.
