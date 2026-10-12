"""Exercise the actual startup frames and native widget/model tooltip events."""

import unittest

from tests.support import APP
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QToolTip, QTreeWidget, QTreeWidgetItem

from app.ui.loading_screen import LoadingScreen
from app.string_widgets import FilePicker, FolderPicker
from app.ui.theme import apply_theme


class LoadingAndTooltipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apply_theme(APP)

    def tearDown(self) -> None:
        QToolTip.hideText()
        APP.processEvents()

    def test_loading_frames_alternate_and_stop_when_hidden(self) -> None:
        screen = LoadingScreen()
        try:
            self.assertTrue(all(not frame.isNull() for frame in screen.frames))
            self.assertEqual(screen.frame_index, 0)
            screen.show()
            APP.processEvents()
            self.assertTrue(screen.timer.isActive())
            initial = screen.image.pixmap().cacheKey()
            QTest.qWait(350)
            self.assertEqual(screen.frame_index, 1)
            self.assertNotEqual(screen.image.pixmap().cacheKey(), initial)
            available = APP.primaryScreen().availableGeometry()
            self.assertLessEqual(abs(screen.geometry().center().x() - available.center().x()), 1)
            screen.close()
            self.assertFalse(screen.timer.isActive())
        finally:
            screen.close()
            screen.deleteLater()

    def test_button_tooltip_contains_image_and_escaped_original_text(self) -> None:
        button = QPushButton("Test")
        text = "--name <value> & extra\nSecond line"
        button.setProperty("tooltipKind", "parameter")
        button.setToolTip(text)
        try:
            button.show()
            APP.processEvents()
            point = QPoint(8, 8)
            APP.sendEvent(button, QHelpEvent(QEvent.Type.ToolTip, point, button.mapToGlobal(point)))
            self.assertIn("tooltip.png", QToolTip.text())
            self.assertIn("&lt;value&gt; &amp; extra", QToolTip.text())
            self.assertIn("Second line", QToolTip.text())
            self.assertIn('margin-bottom:8px', QToolTip.text())
            self.assertIn('width="48"', QToolTip.text())
            self.assertIn('<td width="16">', QToolTip.text())
            self.assertEqual(button.toolTip(), text)
        finally:
            button.close()
            button.deleteLater()

    def test_file_and_folder_paths_have_text_only_tooltips(self) -> None:
        for picker_type in (FilePicker, FolderPicker):
            path = "C:/A folder/with & symbols/example"
            picker = picker_type("Target", path)
            try:
                picker.show()
                APP.processEvents()
                label = picker.path_label
                point = QPoint(8, 8)
                APP.sendEvent(label, QHelpEvent(QEvent.Type.ToolTip, point, label.mapToGlobal(point)))
                self.assertNotIn("<img", QToolTip.text())
                self.assertIn("with &amp; symbols", QToolTip.text())
                self.assertEqual(label.toolTip(), path)
            finally:
                picker.close()
                picker.deleteLater()

    def test_tree_item_tooltips_use_the_same_image(self) -> None:
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        item = QTreeWidgetItem(tree, ["Script"])
        item.setToolTip(0, "Script path\nIdle")
        try:
            tree.show()
            APP.processEvents()
            point = tree.visualItemRect(item).center()
            APP.sendEvent(tree.viewport(), QHelpEvent(QEvent.Type.ToolTip, point, tree.viewport().mapToGlobal(point)))
            self.assertIn("tooltip.png", QToolTip.text())
            self.assertIn("Script path<br/>Idle", QToolTip.text())
            self.assertEqual(item.toolTip(0), "Script path\nIdle")
        finally:
            tree.close()
            tree.deleteLater()
