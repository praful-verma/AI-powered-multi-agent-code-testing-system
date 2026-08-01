import unittest
from pathlib import Path

from multiagent_testing.agents.test_generator import _normalize_repo_relative_path
from multiagent_testing.agents.test_runner import _normalize_target_file


class PathNormalizationTests(unittest.TestCase):
    def test_strips_project_prefix_before_frontend_or_backend(self) -> None:
        path = Path("mern-bookshelf-app") / "frontend" / "src" / "App.jsx"

        self.assertEqual(_normalize_repo_relative_path(str(path)), "frontend/src/App.jsx")
        self.assertEqual(_normalize_target_file(str(path)), "frontend/src/App.jsx")


if __name__ == "__main__":
    unittest.main()
