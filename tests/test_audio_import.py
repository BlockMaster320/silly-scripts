"""Single-file audio importer checks without requiring a Blender installation."""

import contextlib
import io
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.script_inspector import ScriptInspector


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/default/import_audio_files.py"


class AudioImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.audio_root = Path(self.temp.name)
        self.old_audio = SimpleNamespace(channel=2)
        self.other_strip = SimpleNamespace(channel=1)
        strips = Mock()
        self.editor = SimpleNamespace(strips=strips, strips_all=[self.old_audio, self.other_strip])
        self.scene = SimpleNamespace(sequence_editor=self.editor, frame_start=1, frame_end=250)
        self.bpy = SimpleNamespace(
            data=SimpleNamespace(filepath=str(self.audio_root / "sh001234.blend")),
            context=SimpleNamespace(scene=self.scene),
        )
        with patch.dict(sys.modules, {"bpy": self.bpy}):
            self.module = runpy.run_path(str(SCRIPT), run_name="_audio_import_test")

    def create_audio(self) -> Path:
        wav = self.audio_root / "sh001234/sh001234.wav"
        wav.parent.mkdir()
        wav.touch()
        return wav

    def test_inspection_exposes_only_audio_directory_and_forces_batch(self) -> None:
        info = ScriptInspector().inspect(SCRIPT)
        self.assertIsNone(info.inspection_error)
        self.assertEqual(len(info.parameters), 1)
        parameter = info.parameters[0]
        self.assertEqual(parameter.option_strings, ["--audio-directory"])
        self.assertIs(parameter.parameter_type, Path)
        self.assertTrue(parameter.required)
        self.assertTrue(parameter.is_folder_selection)
        self.assertEqual(info.metadata.default_run_mode, "batch")
        self.assertTrue(info.metadata.force_default_run_mode)

    def test_main_imports_current_file_with_both_argument_formats(self) -> None:
        wav = self.create_audio()
        for argv in (
            [str(SCRIPT), "--audio-directory", str(self.audio_root)],
            ["blender", "--background", "--python", str(SCRIPT), "--", "--audio-directory", str(self.audio_root)],
        ):
            with self.subTest(argv=argv), patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as output:
                self.module["main"]()
                self.assertIn("[SCRIPT] Imported", output.getvalue())
                self.editor.strips.remove.assert_called_once_with(self.old_audio)
                self.editor.strips.new_sound.assert_called_once_with(
                    name="sh001234", filepath=str(wav), channel=2, frame_start=100,
                )
                self.assertEqual((self.scene.frame_start, self.scene.frame_end), (1, 250))
                self.editor.strips.reset_mock()

    def test_missing_audio_or_unmatched_filename_leaves_strips_untouched(self) -> None:
        for filename in ("sh001234.blend", "unmatched.blend"):
            self.bpy.data.filepath = str(self.audio_root / filename)
            with self.subTest(filename=filename), contextlib.redirect_stdout(io.StringIO()) as output:
                self.module["process_current_file"](self.audio_root)
                self.assertIn("Skipped", output.getvalue())
                self.editor.strips.remove.assert_not_called()
                self.editor.strips.new_sound.assert_not_called()

    def test_unsaved_file_and_missing_scene_raise_for_batch_error_handling(self) -> None:
        self.bpy.data.filepath = ""
        with self.assertRaisesRegex(ValueError, "No saved blend file"):
            self.module["process_current_file"](self.audio_root)
        self.bpy.data.filepath = str(self.audio_root / "sh001234.blend")
        self.create_audio()
        self.bpy.context.scene = None
        with self.assertRaisesRegex(RuntimeError, "No active scene"):
            self.module["process_current_file"](self.audio_root)


if __name__ == "__main__":
    unittest.main()
