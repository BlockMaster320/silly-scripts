"""One palette, stylesheet, spacing scale, and icon family for the application."""

from pathlib import Path
from string import Template

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton, QTreeWidgetItem, QWidget


PALETTE = {
    "background": "#191c20",
    "sidebar": "#22262e",
    "surface": "#282d36",
    "surface_hover": "#323946",
    "input": "#20242c",
    "console": "#0d0f13",
    "border": "#3a424f",
    "section_rule": "#59616e",
    "parameter_rule": "#3a424f",
    "text": "#dce1e9",
    "command_text": "#ffffff",
    "muted": "#a0aaba",
    "disabled": "#818b9b",
    "accent": "#87aee8",
    "accent_fill": "#365b8c",
    "accent_hover": "#416a9e",
    "accent_pressed": "#2f507c",
    "selection": "#2c3c54",
    "success": "#9bc4ac",
    "success_surface": "#283b32",
    "warning": "#d2b483",
    "warning_surface": "#3e3528",
    "danger": "#dfa4a4",
    "danger_surface": "#443037",
}

TINY, SMALL, NORMAL, SECTION, PAGE = 4, 8, 12, 16, 24
CONTROL_HEIGHT = 36
LABEL_WIDTH = 160
ICON_SIZE = 16
SIDEBAR_WIDTH = 300
TOOLTIP_WIDTH = 400
UI_ROOT = Path(__file__).resolve().parent


def apply_theme(application: QApplication) -> None:
    """Apply once, before creating widgets, including a palette for dialogs."""
    application.setStyle("Fusion")
    application.setWindowIcon(QIcon(str(UI_ROOT / "graphics" / "logo.png")))
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: "background",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "input",
        QPalette.ColorRole.AlternateBase: "surface",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "surface",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.Highlight: "selection",
        QPalette.ColorRole.HighlightedText: "text",
        QPalette.ColorRole.PlaceholderText: "muted",
        QPalette.ColorRole.ToolTipBase: "surface",
        QPalette.ColorRole.ToolTipText: "text",
        QPalette.ColorRole.Link: "accent",
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(PALETTE[color]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(PALETTE["disabled"]))
    application.setPalette(palette)
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    if "Segoe UI" in QFontDatabase.families():
        font.setFamily("Segoe UI")
    font.setPixelSize(13)
    application.setFont(font)
    template = Template((UI_ROOT / "styles.qss").read_text(encoding="utf-8"))
    application.setStyleSheet(template.substitute(PALETTE, icons=(UI_ROOT / "icons").as_posix()))
    # Install once; retained on the application for its complete lifetime.
    from .tooltips import TooltipPresenter
    if not hasattr(application, "_sillyscripts_tooltips"):
        presenter = TooltipPresenter(application)
        application.installEventFilter(presenter)
        application._sillyscripts_tooltips = presenter
    from .interaction import InteractionCursors
    if not hasattr(application, "_sillyscripts_cursors"):
        cursors = InteractionCursors(application)
        application.installEventFilter(cursors)
        application._sillyscripts_cursors = cursors


def icon(name: str) -> QIcon:
    """Original 24px outline assets, with a shared stroke and geometry."""
    return QIcon(str(UI_ROOT / "icons" / f"{name}.svg"))


def style_script_item(item: QTreeWidgetItem, unavailable: bool) -> None:
    item.setForeground(0, QBrush(QColor(PALETTE["danger"])) if unavailable else QBrush())


def style_button(button: QPushButton, name: str | None = None, role: str = "secondary") -> None:
    button.setProperty("role", role)
    if name:
        # Segoe UI's visible glyphs sit one pixel below the font's geometric
        # center. Match that optical center using the same vector icon family;
        # native QPushButton still handles layout, focus, and interaction.
        source = icon(name)
        aligned = QIcon()
        for scale in (1, 2, 3):
            size = ICON_SIZE * scale
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.drawPixmap(0, scale, source.pixmap(size, size))
            painter.end()
            aligned.addPixmap(pixmap)
        button.setIcon(aligned)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))


def set_variant(widget: QWidget, name: str, value: str) -> None:
    """Refresh QSS when a semantic property changes after widget construction."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def monospace_font() -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if "Consolas" in QFontDatabase.families():
        font.setFamily("Consolas")
    font.setPixelSize(12)
    return font
