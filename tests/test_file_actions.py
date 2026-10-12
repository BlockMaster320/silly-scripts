"""Source-file opening delegates to the user's normal file association."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ui.file_actions import open_script_file


class FileActionTests(unittest.TestCase):
    def test_open_uses_normal_file_association_and_preserves_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "script with spaces.py"
            script.write_text("", encoding="utf-8")
            with patch("app.ui.file_actions.QDesktopServices.openUrl", return_value=True) as open_url:
                self.assertTrue(open_script_file(script))
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(script).replace("\\", "/"))
            with patch("app.ui.file_actions.QDesktopServices.openUrl", return_value=False):
                self.assertFalse(open_script_file(script))

    def test_missing_file_does_not_launch_an_application(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.ui.file_actions.QDesktopServices.openUrl") as open_url:
                self.assertFalse(open_script_file(Path(directory) / "missing.py"))
            open_url.assert_not_called()
