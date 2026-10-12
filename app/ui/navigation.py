"""Preserve semantic script foreground colors in selected navigation rows."""

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem


class ScriptItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        super().initStyleOption(option, index)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(foreground, QBrush) and foreground.style() != Qt.BrushStyle.NoBrush:
            palette = option.palette
            palette.setBrush(QPalette.ColorRole.HighlightedText, foreground)
            option.palette = palette
