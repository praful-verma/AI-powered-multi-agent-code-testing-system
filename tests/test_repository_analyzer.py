import json
import tempfile
import unittest
from pathlib import Path

from multiagent_testing.analyzer import analyze_repository
from multiagent_testing.analyzer.import_analyzer import extract_imports
from multiagent_testing.main import _run_analysis_only
from multiagent_testing.models import AgentState


class RepositoryAnalyzerTests(unittest.TestCase):
    def test_extracts_multiline_destructured_require_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            route = root / "backend" / "routes" / "bookRoutes.js"
            controller = root / "backend" / "controllers" / "bookController.js"
            controller.parent.mkdir(parents=True)
            route.parent.mkdir(parents=True)
            controller.write_text("exports.getBooks = () => {};\n", encoding="utf-8")
            route.write_text(
                "const {\n"
                "  getBooks,\n"
                "  getBookById,\n"
                "} = require('../controllers/bookController');\n",
                encoding="utf-8",
            )

            imports = extract_imports(route.read_text(encoding="utf-8"), route, root)

            self.assertEqual(imports[0].bindings, ["getBooks", "getBookById"])
            self.assertEqual(imports[0].source, "../controllers/bookController")

    def test_builds_graph_with_imports_dependencies_calls_and_mock_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            (backend / "controllers").mkdir(parents=True)
            (backend / "models").mkdir()
            (backend / "package.json").write_text(
                '{"dependencies": {"express": "^4.0.0", "mongoose": "^7.0.0"}}',
                encoding="utf-8",
            )
            (backend / "models" / "Book.js").write_text(
                "const mongoose = require('mongoose');\n"
                "module.exports = mongoose.model('Book', new mongoose.Schema({ title: String }));\n",
                encoding="utf-8",
            )
            (backend / "controllers" / "bookController.js").write_text(
                "const Book = require('../models/Book');\n"
                "async function getBooks(req, res) {\n"
                "  const books = await Book.find();\n"
                "  res.json(books);\n"
                "}\n"
                "module.exports = { getBooks };\n",
                encoding="utf-8",
            )

            graph = analyze_repository(str(root), "mern")
            controller_file = next(
                file for file in graph.files if file.relative_path == "backend/controllers/bookController.js"
            )
            controller_unit = next(unit for unit in graph.units if unit.name == "getBooks")

            self.assertEqual(controller_file.file_role, "controller")
            self.assertEqual(controller_file.imports[0].resolved_path, "backend/models/Book.js")
            self.assertIn("Book.find", controller_unit.calls)
            self.assertIn("Book", controller_unit.dependencies)
            self.assertIsNotNone(controller_unit.mock_plan)
            self.assertEqual(controller_unit.mock_plan.module_mocks[0]["dependency_type"], "mongoose_model")

    def test_analysis_only_writes_repository_graph_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            output = Path(tmpdir) / "runs"
            (root / "backend" / "routes").mkdir(parents=True)
            (root / "backend" / "package.json").write_text(
                '{"dependencies": {"express": "^4.0.0"}}',
                encoding="utf-8",
            )
            (root / "backend" / "routes" / "healthRoutes.js").write_text(
                "const router = require('express').Router();\n"
                "router.get('/health', (req, res) => res.json({ ok: true }));\n"
                "module.exports = router;\n",
                encoding="utf-8",
            )
            state: AgentState = {
                "repo_path": str(root),
                "stack": "mern",
                "output_dir": str(output),
                "errors": [],
            }

            final_state = _run_analysis_only(state)
            graph_path = Path(final_state["repository_graph_path"])
            payload = json.loads(graph_path.read_text(encoding="utf-8"))

            self.assertTrue(graph_path.exists())
            self.assertEqual(payload["stack"], "mern")
            self.assertGreaterEqual(len(payload["units"]), 1)


if __name__ == "__main__":
    unittest.main()
