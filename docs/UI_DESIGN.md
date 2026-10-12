# SillyScripts UI design

SillyScripts uses a compact charcoal theme with a muted blue accent, neutral
surfaces, legible secondary text, and 6–8 px corners. Spacing comes from a
4/8/12/16/24 px scale. Body text is 13 px, section headings are 17 px, and consoles
use a 12 px system monospace font. Segoe UI and Consolas are preferred when
installed. Single-line inputs and buttons are 36 px high.

Navigation keeps each library as a collapsible tree root. The sidebar starts
at 244 px and remains resizable. Selected rows have a narrow accent indicator;
running/unavailable entries have explicit text and an outline icon. A selected
script header and status badge remain above the compact three-tab workspace.

All section headings use a trailing one-pixel muted rule positioned slightly
below the heading center, shared by the Script and Settings tabs.
Form labels align with the first control, with muted help and a persistent
action footer. Settings separates libraries, Blender, and
Python; full executable paths are shown below concise selector labels. Both
forms scroll at smaller sizes. The log toolbar sits above the console; stderr
keeps its existing prefix and also gets a restrained red text color.

## Central styling

- `app/ui/theme.py` owns `PALETTE`, spacing/sizing constants, system fonts,
  icon loading, and semantic-property updates.
- `app/ui/styles.qss` is a template. `apply_theme()` substitutes palette colors
  and absolute icon paths, then applies it to `QApplication` in `main.py`.
  Fusion and a matching `QPalette` keep widget and dialog states consistent.
- Widgets declare roles such as `primary`, `danger`, `help`, `required`,
  `console`, and `badge`. Runtime badge changes use `set_variant()` to refresh
  the relevant selectors. There are no per-widget stylesheet calls.
- `app/ui/console.py` colors existing console text with `QSyntaxHighlighter`.
  It does not rewrite text or participate in file logging.
- `app/ui/components.py` composes section headings and trailing rules with
  standard Qt layouts. Repeatable value rows preserve their minimum height and
  8 px gaps. Labels align with the first control, independently of help text
  and additional rows. Native button icons have a shared optical-center offset.
- `app/ui/icons/` contains fourteen original SVG line assets. They share a
  24 px canvas, neutral stroke, 1.75 px line weight, and rounded joins. No icon
  package, web framework, font asset, or new dependency was added.

## Files changed or added

Existing files modified:

- `main.py`
- `app/main_window.py`
- `app/parameters_panel.py`
- `app/parameter_widgets.py`
- `app/string_widgets.py`
- `app/settings_panel.py`
- `app/log_panel.py`
- `app/settings.py` (keeps the existing preference store after the rename)
- `app/__init__.py`

New files:

- `app/ui/__init__.py`
- `app/ui/theme.py`
- `app/ui/styles.qss`
- `app/ui/console.py`
- `app/ui/components.py`
- `app/ui/icons/play.svg`, `stop.svg`, `folder.svg`, `refresh.svg`, `settings.svg`
- `app/ui/icons/terminal.svg`, `file-code.svg`, `plus.svg`, `minus.svg`, `check.svg`
- `app/ui/icons/chevron-down.svg`, `chevron-up.svg`, `chevron-right.svg`, `clear.svg`
- `tests/test_ui_design.py`
- `tools/render_ui.py`
- `docs/UI_DESIGN.md`
- Seven rendered PNG files under `docs/ui/`

The process manager, argument builder, parser inspector, executable/script
discovery, templates, and data models were not changed for this redesign.
Application titles and metadata use SillyScripts. Settings explicitly keeps the
previous QSettings identity so existing libraries, executables, and geometry
survive the rename. The first tab's visible label is Parameters; Settings also
has a sidebar shortcut.

## Verification

Run the focused regression checks with the existing Python environment:

```text
python -m unittest tests.test_ui_design tests.test_inspection tests.test_executables
```

All 23 checks pass. The UI checks cover mapping/defaults, repeatable argument
values, live command preview, batch selection and Blender launch flags,
concurrent Python runs, duplicate-run prevention, Stop, per-script buffers,
Clear Log, display/disk filters, executable errors, script creation,
multiple libraries, refresh after a library disappears, and 820×620 resizing.
The layout regression checks also verify that added/removed text fields retain
36 px height and 8 px gaps, label tops align with first-control tops, and the
styled editor content area has enough height for the font.

The existing parameter/string/template/inspection/discovery tests were also
run: 37 passed and six failed because they still refer to Include checkboxes
removed earlier. Older window/process fixtures likewise assume the previous
Python runtime and test_scripts defaults; they are not a clean full-suite
baseline. Production defaults remain as configured before the redesign.

Render actual Qt screenshots with isolated settings and a sample Python run:

```text
python tools/render_ui.py
```

The renderer captures [Parameters](ui/parameters.png),
[repeated fields](ui/repeated.png),
[command preview](ui/command.png), [batch selection](ui/batch.png),
[live log](ui/log.png), [Settings](ui/settings.png), and an
[820×620 window](ui/compact.png). On Windows the offscreen plugin has no system
fonts; the helper loads installed Windows fonts solely for rendering. No font
files are bundled. These screenshots were visually inspected for spacing,
text layout, contrast, and clipping. Compilation checks also pass.

No underlying feature was intentionally removed. The UI tests launch Python
processes; they do not modify production .blend files in Blender. Native file
dialogs retain the operating system's appearance. Launch the application as
before with `python main.py`; restart a running instance to load this theme.
