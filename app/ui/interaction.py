"""Consistent cursors for standard Qt controls, including dynamic forms."""

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QCheckBox, QComboBox, QLineEdit,
    QScrollBar, QTabBar, QWidget,
)


class InteractionCursors(QObject):
    """Apply hand cursors centrally while preserving text/resize cursors."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind in (QEvent.Type.Polish, QEvent.Type.Show, QEvent.Type.EnabledChange, QEvent.Type.Enter):
            if isinstance(watched, QCheckBox):
                watched.setMouseTracking(True)
                self._set_pointer(watched, False)
            elif isinstance(watched, (QAbstractButton, QComboBox, QScrollBar)):
                self._set_pointer(watched, watched.isEnabled())
            elif isinstance(watched, QLineEdit):
                watched.setCursor(Qt.CursorShape.IBeamCursor if watched.isEnabled() else Qt.CursorShape.ArrowCursor)
            elif isinstance(watched, QAbstractItemView):
                watched.viewport().setMouseTracking(True)
            elif isinstance(watched, QTabBar):
                watched.setMouseTracking(True)
        if kind in (QEvent.Type.MouseMove, QEvent.Type.Enter, QEvent.Type.EnabledChange):
            position = event.position().toPoint() if hasattr(event, "position") else watched.mapFromGlobal(QCursor.pos())
            if isinstance(watched, QCheckBox):
                self._set_pointer(watched, watched.isEnabled() and watched.hitButton(position))
            elif isinstance(watched, QTabBar):
                tab = watched.tabAt(position)
                self._set_pointer(watched, watched.isEnabled() and tab >= 0 and watched.isTabEnabled(tab))
            else:
                view = watched.parentWidget()
                if isinstance(view, QAbstractItemView) and watched is view.viewport():
                    index = view.indexAt(position)
                    flags = index.flags()
                    enabled = watched.isEnabled() and bool(flags & Qt.ItemFlag.ItemIsEnabled)
                    actionable = bool(flags & Qt.ItemFlag.ItemIsSelectable) or (
                        index.isValid() and view.model().hasChildren(index)
                    )
                    self._set_pointer(watched, enabled and actionable)
        return False

    @staticmethod
    def _set_pointer(widget: QWidget, enabled: bool) -> None:
        shape = Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor
        if widget.cursor().shape() != shape:
            widget.setCursor(shape)
