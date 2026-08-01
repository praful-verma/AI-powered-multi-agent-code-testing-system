import tempfile
import unittest
from pathlib import Path

from multiagent_testing.adapters.mern import MERNAdapter


class MERNAdapterFrontendApiTests(unittest.TestCase):
    def test_injects_axios_mock_for_frontend_api_helper_tests(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "frontend" / "src").mkdir(parents=True)
            (root / "frontend" / "package.json").write_text(
                '{"name": "frontend", "dependencies": {"react": "^18.0.0"}}',
                encoding="utf-8",
            )
            test_path = root / "frontend" / "src" / "api.test.js"
            test_code = "import { getTodos } from './api.js';\n\ndescribe('getTodos', () => {\n  it('calls the API', async () => {\n    await getTodos();\n  });\n});\n"

            prepared = adapter.prepare_test_code(test_code, test_path)

            self.assertIn("vi.mock('axios'", prepared)
            self.assertIn("import { vi } from 'vitest';", prepared)
            self.assertIn("get: createResolvedMethod", prepared)
            self.assertIn("post: createResolvedMethod", prepared)
            self.assertIn("put: createResolvedMethod", prepared)
            self.assertIn("delete: createResolvedMethod", prepared)

    def test_injects_axios_mock_for_book_api_helper_tests(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "frontend" / "src"
            src.mkdir(parents=True)
            (root / "frontend" / "package.json").write_text(
                '{"name": "frontend", "dependencies": {"react": "^18.0.0"}}',
                encoding="utf-8",
            )
            (src / "api.js").write_text(
                "export async function getBooks() {}\nexport async function getBookById(id) {}\nexport async function addBook(book) {}\n",
                encoding="utf-8",
            )
            test_path = src / "api.generated.TC-0001_getBooks.test.js"
            test_code = "import { getBooks } from './api.js';\n\ndescribe('getBooks', () => {\n  it('calls the API', async () => {\n    await getBooks();\n  });\n});\n"

            prepared = adapter.prepare_test_code(test_code, test_path)

            self.assertIn("vi.mock('axios'", prepared)
            self.assertIn("import axios from 'axios';", prepared)

    def test_parses_coverage_summary_percent(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            coverage = backend / "coverage"
            coverage.mkdir(parents=True)
            (backend / "package.json").write_text('{"name": "backend"}', encoding="utf-8")
            test_path = backend / "controllers" / "bookController.generated.TC-0001_addBook.test.js"
            test_path.parent.mkdir()
            test_path.write_text("test('x', () => {});\n", encoding="utf-8")
            (coverage / "coverage-summary.json").write_text(
                '{"total":{"lines":{"pct":55.5},"statements":{"pct":50}},'
                '"backend/controllers/bookController.js":{"lines":{"pct":91.2},"statements":{"pct":90}}}',
                encoding="utf-8",
            )

            percent = adapter.parse_coverage_percent("", str(backend), str(test_path))

            self.assertEqual(percent, 91.2)

    def test_coverage_command_uses_runner_specific_flags(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            backend.mkdir()
            (backend / "package.json").write_text('{"name": "backend"}', encoding="utf-8")
            test_path = backend / "book.generated.TC-0001.test.js"

            command = adapter.get_coverage_command(str(test_path))

            self.assertIn("--coverage", command)
            self.assertIn("--coverageReporters=json-summary", command)


class MERNAdapterBackendRepairTests(unittest.TestCase):
    def test_repairs_controller_object_mount_to_route_module(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            (backend / "controllers").mkdir(parents=True)
            (backend / "routes").mkdir()
            (backend / "models").mkdir()
            (backend / "package.json").write_text('{"name": "backend"}', encoding="utf-8")
            (backend / "routes" / "bookRoutes.js").write_text("module.exports = require('express').Router();\n", encoding="utf-8")
            (backend / "models" / "Book.js").write_text("module.exports = {};\n", encoding="utf-8")
            test_path = backend / "controllers" / "bookController.generated.TC-0001_getBooks.test.js"
            test_code = "\n".join(
                [
                    "const request = require('supertest');",
                    "const express = require('express');",
                    "const bookController = require('../controllers/bookController');",
                    "const app = express();",
                    "app.use('/api/books', bookController);",
                ]
            )

            prepared = adapter.prepare_test_code(test_code, test_path)

            self.assertIn("const bookRoutes = require('../routes/bookRoutes');", prepared)
            self.assertIn("app.use('/api/books', bookRoutes);", prepared)
            self.assertNotIn("app.use('/api/books', bookController);", prepared)
            self.assertIn("jest.mock('../models/Book'", prepared)

    def test_repairs_repo_relative_require_after_materialization(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            (backend / "utils").mkdir(parents=True)
            (backend / "package.json").write_text('{"name": "backend"}', encoding="utf-8")
            (backend / "utils" / "validateBook.js").write_text("module.exports = { validateBook() {} };\n", encoding="utf-8")
            test_path = backend / "utils" / "validateBook.generated.TC-0001_validateBook.test.js"
            test_code = "const __mat_utils_validateBook_js = require('./utils/validateBook.js');\n"

            prepared = adapter.prepare_test_code(test_code, test_path)

            self.assertIn("require('./validateBook')", prepared)
            self.assertNotIn("require('./utils/validateBook.js')", prepared)

    def test_rewrites_named_import_require_relative_to_test_file_directory(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            (backend / "utils").mkdir(parents=True)
            (backend / "package.json").write_text('{"name": "backend"}', encoding="utf-8")
            (backend / "utils" / "validateBook.js").write_text("module.exports = { validateBook() {} };\n", encoding="utf-8")
            test_path = backend / "utils" / "validateBook.generated.TC-0001_validateBook.test.js"
            test_code = "import { validateBook } from './utils/validateBook.js';\n"

            prepared = adapter.prepare_test_code(test_code, test_path)

            self.assertIn("const __mat_utils_validateBook_js = require('./validateBook');", prepared)
            self.assertIn("const validateBook = __mat_utils_validateBook_js.validateBook", prepared)
            self.assertNotIn("require('./utils/validateBook.js')", prepared)

    def test_server_route_mocks_are_express_routers(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            backend = root / "backend"
            (backend / "routes").mkdir(parents=True)
            (backend / "package.json").write_text('{"name": "backend"}', encoding="utf-8")
            (backend / "routes" / "bookRoutes.js").write_text("module.exports = require('express').Router();\n", encoding="utf-8")
            (backend / "server.js").write_text(
                "const express = require('express');\n"
                "const bookRoutes = require('./routes/bookRoutes');\n"
                "const app = express();\n"
                "app.use('/api/books', bookRoutes);\n"
                "module.exports = app;\n",
                encoding="utf-8",
            )
            test_path = backend / "server.generated.TC-0001_health.test.js"
            test_code = "\n".join(
                [
                    "jest.mock('./routes/bookRoutes', () => ({ default: jest.fn() }));",
                    "const targetModule = require('./server');",
                    "const express = require('express');",
                    "const request = require('supertest');",
                    "const app = express();",
                    "app.use(express.json());",
                    "app.use('/', targetModule);",
                    "it('x', async () => { await request(app).get('/api/books'); });",
                ]
            )

            prepared = adapter.prepare_test_code(test_code, test_path)

            self.assertIn("jest.mock('./routes/bookRoutes', () => {", prepared)
            self.assertIn("const router = express.Router();", prepared)
            self.assertIn("return router;", prepared)
            self.assertIn("const app = require('./server');", prepared)
            self.assertNotIn("app.use('/', targetModule);", prepared)

    def test_discovery_skips_private_functions_nested_in_components(self) -> None:
        adapter = MERNAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "frontend" / "src" / "components"
            src.mkdir(parents=True)
            (root / "frontend" / "package.json").write_text(
                '{"name": "frontend", "dependencies": {"react": "^18.0.0"}}',
                encoding="utf-8",
            )
            (src / "BookList.jsx").write_text(
                "import React from 'react';\n"
                "export default function BookList() {\n"
                "  const handleDelete = async () => {};\n"
                "  return <button onClick={handleDelete}>Delete</button>;\n"
                "}\n"
                "export const publicHelper = () => true;\n",
                encoding="utf-8",
            )

            units = adapter.discover_units(str(root))
            names = {unit.name for unit in units}

            self.assertIn("BookList", names)
            self.assertIn("publicHelper", names)
            self.assertNotIn("handleDelete", names)


if __name__ == "__main__":
    unittest.main()
