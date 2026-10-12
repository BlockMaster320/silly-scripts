"""Decorate native Qt hover tooltips without changing widget/model text."""

from html import escape

from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtGui import QHelpEvent, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QToolTip, QWidget

from .theme import SECTION, SMALL, TOOLTIP_WIDTH, UI_ROOT


class TooltipPresenter(QObject):
    """Use Qt's own tooltip window, timing, placement and dismissal behavior."""

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        path = UI_ROOT / "graphics" / "tooltip.png"
        image = QPixmap(str(path))
        self.image_url = path.as_uri() if not image.isNull() else ""
        self.image_size = image.size().scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio)

    def format_text(self, text: str, *, show_image: bool = True, parameter: bool = False) -> str:
        content = escape(text).replace("\n", "<br/>")
        if parameter:
            name, separator, description = text.partition("\n")
            if separator and description.strip():
                content = (
                    f'<p style="margin-top:0px; margin-bottom:{SMALL}px;">{escape(name)}</p>'
                    '<p style="margin-top:0px; margin-bottom:0px;">'
                    + escape(description).replace("\n", "<br/>") + '</p>'
                )
        if not self.image_url or not show_image:
            return f'<table width="{TOOLTIP_WIDTH}" cellspacing="0" cellpadding="0"><tr><td>{content}</td></tr></table>'
        return (
            f'<table width="{TOOLTIP_WIDTH}" cellspacing="0" cellpadding="0"><tr>'
            f'<td width="{self.image_size.width()}" valign="middle">'
            f'<img src="{escape(self.image_url, quote=True)}" '
            f'width="{self.image_size.width()}" height="{self.image_size.height()}">'
            f'</td><td width="{SECTION}"></td>'
            f'<td width="{TOOLTIP_WIDTH - self.image_size.width() - SECTION}" valign="middle">{content}</td></tr></table>'
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not isinstance(watched, QWidget) or event.type() != QEvent.Type.ToolTip:
            return False
        if not isinstance(event, QHelpEvent):
            return False
        text = watched.toolTip()
        rectangle = QRect()
        view = watched.parentWidget()
        if isinstance(view, QAbstractItemView) and watched is view.viewport():
            index = view.indexAt(event.pos())
            if index.isValid():
                value = index.data(Qt.ItemDataRole.ToolTipRole)
                if value:
                    text = str(value)
                    rectangle = view.visualRect(index)
        if not text:
            return False
        QToolTip.showText(
            event.globalPos(), self.format_text(
                text, show_image=watched.property("role") != "path",
                parameter=watched.property("tooltipKind") == "parameter",
            ), watched,
            rectangle, watched.toolTipDuration(),
        )
        event.accept()
        return True
