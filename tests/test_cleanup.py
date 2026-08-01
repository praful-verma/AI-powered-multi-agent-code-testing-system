import tempfile
import unittest
from pathlib import Path

from multiagent_testing.cleanup import cleanup_generated_test_files, cleanup_temp_dir


class CleanupTests(unittest.TestCase):
    def test_cleanup_generated_test_files_deletes_only_generated_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "frontend" / "src"
            ignored_dir = root / "node_modules" / "pkg"
            source_dir.mkdir(parents=True)
            ignored_dir.mkdir(parents=True)

            generated = source_dir / "App.generated.TC-0001_render.test.jsx"
            ordinary_test = source_dir / "App.test.jsx"
            source_file = source_dir / "App.jsx"
            ignored_generated = ignored_dir / "Thing.generated.TC-0002_case.test.js"
            for path in (generated, ordinary_test, source_file, ignored_generated):
                path.write_text("// test\n", encoding="utf-8")

            deleted = cleanup_generated_test_files(str(root))

            self.assertEqual(deleted, 1)
            self.assertFalse(generated.exists())
            self.assertTrue(ordinary_test.exists())
            self.assertTrue(source_file.exists())
            self.assertTrue(ignored_generated.exists())

    def test_cleanup_temp_dir_removes_directory_when_set(self) -> None:
        temp_dir = tempfile.mkdtemp()
        path = Path(temp_dir)
        (path / "file.txt").write_text("temporary", encoding="utf-8")

        cleanup_temp_dir(temp_dir)

        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
