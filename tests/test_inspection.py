import tempfile
import unittest
from pathlib import Path

from app.script_discovery import ScriptDiscoveryError, discover_scripts
from app.script_inspector import ScriptInspector

EXAMPLES = Path(__file__).resolve().parents[1] / "scripts" / "test_scripts"


class InspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.inspector = ScriptInspector()

    def inspect_source(self, source: str):
        path = self.root / "example.py"
        path.write_text(source, encoding="utf-8")
        return self.inspector.inspect(path)

    def test_neutral_models_and_guarded_main(self) -> None:
        marker = self.root / "should_not_exist"
        info = self.inspect_source(
            "import argparse\n"
            "def create_parser():\n"
            "    p = argparse.ArgumentParser()\n"
            "    p.add_argument('--name', help='Your name')\n"
            "    p.add_argument('--count', type=int, required=True)\n"
            "    p.add_argument('--no-cache', dest='cache', action='store_false')\n"
            "    return p\n"
            "if __name__ == '__main__':\n"
            f"    open({str(marker)!r}, 'w').close()\n"
        )
        self.assertIsNone(info.inspection_error)
        self.assertFalse(marker.exists())
        self.assertEqual(len(info.parameters), 3)
        self.assertIs(info.parameters[0].parameter_type, str)
        self.assertEqual(info.parameters[0].help, "Your name")
        self.assertTrue(info.parameters[1].required)
        self.assertEqual(info.parameters[2].action_type, "store_false")

    def test_errors_are_returned_instead_of_raised(self) -> None:
        cases = [
            ("import nonexistent_launcher_test_dependency", "ModuleNotFoundError"),
            ("x = 1", "create_parser"),
            ("def create_parser():\n    raise ValueError('broken factory')", "broken factory"),
            ("def create_parser():\n    raise SystemExit(2)", "SystemExit"),
            ("def create_parser():\n    return []", "ArgumentParser"),
            ("not valid python !", "SyntaxError"),
        ]
        for source, error in cases:
            with self.subTest(error=error):
                self.assertIn(error, self.inspect_source(source).inspection_error)

    def test_parser_description_and_script_metadata_become_neutral_models(self) -> None:
        info = self.inspect_source(
            "import argparse\ndef create_parser():\n"
            "    parser = argparse.ArgumentParser(description='Process scene assets.\\nKeeps materials.')\n"
            "    parser.script_metadata = {'default_run_mode': 'batch', 'force_default_run_mode': True, 'future_key': 'ignored'}\n"
            "    return parser\n"
        )
        self.assertIsNone(info.inspection_error)
        self.assertEqual(info.description, "Process scene assets.\nKeeps materials.")
        self.assertEqual(info.metadata.default_run_mode, "batch")
        self.assertTrue(info.metadata.force_default_run_mode)
        defaults = self.inspect_source("import argparse\ndef create_parser():\n    return argparse.ArgumentParser()\n")
        self.assertIsNone(defaults.description)
        self.assertEqual(defaults.metadata.default_run_mode, "single")
        self.assertFalse(defaults.metadata.force_default_run_mode)

    def test_invalid_script_metadata_and_description_report_clear_errors(self) -> None:
        for value, error in (
            ("None", "dictionary"), ("{'default_run_mode': 'wrong'}", "'single' or 'batch'"),
            ("{'force_default_run_mode': 'False'}", "True or False"),
        ):
            with self.subTest(value=value):
                info = self.inspect_source(
                    "import argparse\ndef create_parser():\n"
                    "    parser = argparse.ArgumentParser()\n"
                    f"    parser.script_metadata = {value}\n    return parser\n"
                )
                self.assertIn(error, info.inspection_error)
        info = self.inspect_source("import argparse\ndef create_parser():\n    return argparse.ArgumentParser(description=123)\n")
        self.assertIn("description must be", info.inspection_error)
        self.assertIsNone(info.description)

    def test_top_level_bpy_import_is_allowed_for_parser_inspection(self) -> None:
        info = self.inspect_source(
            "import argparse\nimport bpy\n"
            "BLENDER_OBJECT_TYPE = bpy.types.Object\n"
            "def create_parser():\n"
            "    parser = argparse.ArgumentParser()\n"
            "    parser.add_argument('--name', default='Suzanne')\n"
            "    return parser\n"
        )
        self.assertIsNone(info.inspection_error)
        self.assertEqual(info.parameters[0].name, "name")

    def test_spawn_monkey_example_inspects_with_global_bpy(self) -> None:
        info = self.inspector.inspect(Path(__file__).resolve().parents[1] / "scripts" / "default" / "spawn_monkey.py")
        self.assertIsNone(info.inspection_error)
        self.assertEqual(info.parameters[0].name, "monkey_name")

    def test_bpy_api_use_during_parser_inspection_has_clear_error(self) -> None:
        info = self.inspect_source(
            "import argparse\nimport bpy\n"
            "def create_parser():\n"
            "    bpy.utils.register_class(object)\n"
            "    return argparse.ArgumentParser()\n"
        )
        self.assertIn("unavailable during launcher inspection", info.inspection_error)

    def test_optional_nargs_and_unsupported_actions(self) -> None:
        info = self.inspect_source(
            "import argparse\ndef create_parser():\n"
            "    p = argparse.ArgumentParser()\n"
            "    p.add_argument('value', nargs='?', default='fallback')\n    return p\n"
        )
        self.assertIsNone(info.inspection_error)
        self.assertEqual(info.parameters[0].nargs, "?")
        self.assertFalse(info.parameters[0].required)
        info = self.inspect_source(
            "import argparse\ndef create_parser():\n"
            "    p = argparse.ArgumentParser()\n"
            "    p.add_argument('--verbosity', action='count')\n    return p\n"
        )
        self.assertIn("not supported", info.inspection_error)

    def test_refresh_reads_changed_source(self) -> None:
        original = "import argparse\ndef create_parser():\n    p=argparse.ArgumentParser()\n    p.add_argument('--one')\n    return p\n"
        self.assertEqual(self.inspect_source(original).parameters[0].name, "one")
        self.assertEqual(self.inspect_source(original.replace("--one", "--two")).parameters[0].name, "two")

    def test_discovery_is_shallow_and_handles_disappearing_folder(self) -> None:
        for name in ("b.py", "A.PY", "__init__.py", "notes.txt"):
            (self.root / name).touch()
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "hidden.py").touch()
        self.assertEqual([p.name for p in discover_scripts(self.root)], ["A.PY", "b.py"])
        with self.assertRaises(ScriptDiscoveryError):
            discover_scripts(self.root / "missing")

    def test_all_examples_inspect_as_expected(self) -> None:
        for path in discover_scripts(EXAMPLES):
            info = self.inspector.inspect(path)
            with self.subTest(path=path.name):
                self.assertEqual(info.inspection_error is not None, path.name == "missing_parser.py")
