import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multiagent_testing.agents.assertion_generator import (
    assertion_generator_node,
    generate_deterministic_assertion_block,
    validate_assertion_fragment,
)
from multiagent_testing.agents.test_runner import _attach_coverage
from multiagent_testing.agents.test_builder import test_builder_node
from multiagent_testing.agents.test_planner import build_deterministic_test_plan, test_planner_node
from multiagent_testing.agents.test_runner import _materialize_row_test_file
from multiagent_testing.agents.test_runner import _write_execution_reports
from multiagent_testing.confidence import confidence_breakdown
from multiagent_testing.excel_store import ExcelStore
from multiagent_testing.failure_analyzer import categorize_failure
from multiagent_testing.graph import build_graph
from multiagent_testing.models import AgentState
from multiagent_testing.repair import repair_test_code
from multiagent_testing.templates import build_test_code
from multiagent_testing.validators import validate_test_code


class ArchitecturePipelineTests(unittest.TestCase):
    def test_graph_starts_with_repository_analyzer(self) -> None:
        graph = build_graph()

        self.assertIsNotNone(graph)

    def test_validation_and_repair_insert_supertest_and_clear_mocks(self) -> None:
        test_code = "const express = require('express');\nconst express = require('express');\ntest('x', () => { jest.fn(); request(app); });\n"

        issues = validate_test_code(test_code, "bookRoutes.test.js", "jest")
        repaired = repair_test_code(test_code, issues, "jest")

        self.assertIn("const request = require('supertest');", repaired.test_code)
        self.assertIn("jest.clearAllMocks();", repaired.test_code)
        self.assertEqual(repaired.test_code.count("const express = require('express');"), 1)

    def test_validation_and_repair_remove_duplicate_imports(self) -> None:
        test_code = "import axios from 'axios';\nimport axios from 'axios';\nit('x', () => expect(axios).toBeDefined());\n"

        issues = validate_test_code(test_code, "frontend/src/api/bookApi.test.js", "vitest")
        repaired = repair_test_code(test_code, issues, "vitest")

        self.assertIn("duplicate_import", {issue.code for issue in issues})
        self.assertEqual(repaired.test_code.count("import axios from 'axios';"), 1)

    def test_validation_and_repair_insert_missing_axios_mock(self) -> None:
        test_code = "const axios = require('axios');\nit('x', () => { expect(axios).toBeDefined(); });\n"

        issues = validate_test_code(test_code, "frontend/src/api/bookApi.test.js", "jest")
        repaired = repair_test_code(test_code, issues, "jest")

        self.assertIn("missing_axios_mock", {issue.code for issue in issues})
        self.assertIn("jest.mock('axios');", repaired.test_code)

    def test_validation_and_repair_move_mongoose_mock_before_controller_import(self) -> None:
        test_code = "\n".join(
            [
                "const controller = require('../controllers/bookController');",
                "jest.mock('../models/Book', () => ({ create: jest.fn() }));",
                "it('x', () => expect(controller).toBeDefined());",
                "",
            ]
        )

        issues = validate_test_code(test_code, "backend/controllers/bookController.test.js", "jest")
        repaired = repair_test_code(test_code, issues, "jest")

        self.assertIn("mongoose_mock_order", {issue.code for issue in issues})
        self.assertLess(repaired.test_code.index("jest.mock('../models/Book'"), repaired.test_code.index("require('../controllers/bookController')"))

    def test_validation_flags_ignored_paths_and_private_imports(self) -> None:
        test_code = "import { handleDelete, publicThing } from './BookList';\nit('x', () => expect(handleDelete).toBeDefined());\n"

        issues = validate_test_code(test_code, "coverage/BookList.test.js", "jest")
        issue_codes = {issue.code for issue in issues}

        self.assertIn("ignored_test_path", issue_codes)
        self.assertIn("private_import", issue_codes)

    def test_repair_report_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir)

            _write_execution_reports(
                output,
                [
                    {
                        "test_id": "TC-0001",
                        "target_file": "backend/routes/bookRoutes.js",
                        "target_function_or_route": "GET /books",
                        "repairs_applied": "inserted missing supertest import",
                        "validation_status": "Pass",
                    }
                ],
            )

            report = output / "repair_report.md"
            self.assertTrue(report.exists())
            self.assertIn("inserted missing supertest import", report.read_text(encoding="utf-8"))

    def test_failure_analyzer_categorizes_realistic_runner_snippets(self) -> None:
        cases = {
            "SyntaxError: Unexpected token '<'": "Syntax",
            "Error: Cannot find module '../models/Book'": "Import",
            "TypeError: Book.find.mockResolvedValue is not a function": "Mock",
            "Error: Test timed out in 10000ms": "Timeout",
            "Expected: 201\nReceived: 500": "Assertion",
            "Coverage command failed because no coverage provider was found": "Coverage",
            "Environment setup failed: npm install failed": "Environment",
            "ReferenceError: document is not defined": "Runtime",
            "Error: Route.get() requires a callback function but got a [object Undefined]": "Mock",
        }

        for output, category in cases.items():
            with self.subTest(output=output):
                self.assertEqual(categorize_failure(output), category)

    def test_runner_attaches_coverage_percent_to_updates(self) -> None:
        class Adapter:
            timeout_seconds = 5

            def get_coverage_command(self, test_file_path: str) -> list[str]:
                return ["coverage-tool", test_file_path]

            def get_test_cwd(self, repo_path: str, test_file_path: str) -> str:
                return repo_path

            def parse_coverage_percent(self, raw_output: str, cwd: str, test_file_path: str) -> float:
                return 87.5

        class Completed:
            returncode = 0
            stdout = "{}"
            stderr = ""

        rows = [{"test_id": "TC-0001"}]
        updates = {"TC-0001": {"status": "Pass", "score": 100, "actual_output": "OK"}}

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("multiagent_testing.agents.test_runner.subprocess.run", return_value=Completed()):
                _attach_coverage(Adapter(), tmpdir, str(Path(tmpdir) / "x.generated.TC-0001.test.js"), rows, updates)

        self.assertEqual(updates["TC-0001"]["coverage_percent"], 87.5)
        self.assertGreaterEqual(updates["TC-0001"]["confidence_score"], 95)
        self.assertIn("coverage is high", updates["TC-0001"]["confidence_details"])

    def test_confidence_breakdown_penalizes_repairs_and_explains_score(self) -> None:
        breakdown = confidence_breakdown(
            {
                "status": "Pass",
                "score": 100,
                "validation_status": "Pass",
                "repairs_applied": "removed duplicate import; inserted clearAllMocks",
                "coverage_percent": 32,
            }
        )

        self.assertLess(breakdown.score, 90)
        self.assertIn("2 deterministic repair(s)", breakdown.details)
        self.assertIn("coverage is low", breakdown.details)

    def test_confidence_report_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir)

            _write_execution_reports(
                output,
                [
                    {
                        "test_id": "TC-0001",
                        "target_file": "backend/controllers/bookController.js",
                        "target_function_or_route": "addBook",
                        "status": "Pass",
                        "confidence_score": 98,
                        "confidence_details": "execution passed; static validation passed",
                    }
                ],
            )

            report = output / "confidence_report.md"
            self.assertTrue(report.exists())
            text = report.read_text(encoding="utf-8")
            self.assertIn("Average confidence: 98.0", text)
            self.assertIn("execution passed; static validation passed", text)

    def test_runner_materialization_records_validation_and_repairs(self) -> None:
        class Adapter:
            def get_test_framework(self) -> str:
                return "jest"

            def prepare_test_code(self, test_code: str, test_file_path: str) -> str:
                return test_code

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "backend" / "routes" / "bookRoutes.js"
            target.parent.mkdir(parents=True)
            target.write_text("module.exports = require('express').Router();\n", encoding="utf-8")
            row = {
                "test_id": "TC-0001",
                "target_file": "backend/routes/bookRoutes.js",
                "target_function_or_route": "GET /books",
                "test_code": "const express = require('express');\nconst express = require('express');\ntest('x', () => { jest.fn(); request(app); });\n",
            }

            test_path = _materialize_row_test_file(Adapter(), str(root), row)

            self.assertTrue(test_path.exists())
            self.assertIn("removed duplicate require statements", row["repairs_applied"])
            self.assertIn("inserted missing supertest import", row["repairs_applied"])
            self.assertIn(row["validation_status"], {"Pass", "Warning"})

    def test_planner_creates_behavior_specifications_from_graph(self) -> None:
        graph = {
            "units": [
                {
                    "id": "backend/controllers/book.js:addBook",
                    "unit_type": "controller",
                    "name": "addBook",
                    "dependencies": ["Book"],
                    "risk_level": "high",
                    "mock_plan": {"module_mocks": [{"binding": "Book"}]},
                }
            ]
        }

        specs = build_deterministic_test_plan(graph)

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].target_unit_id, "backend/controllers/book.js:addBook")
        self.assertEqual(specs[0].priority, "High")
        self.assertIn("Book", specs[0].required_mocks)

    def test_template_builder_outputs_runnable_planned_skeleton(self) -> None:
        graph = {
            "root_path": "",
            "units": [
                {
                    "id": "backend/routes/bookRoutes.js:router",
                    "relative_path": "backend/routes/bookRoutes.js",
                    "unit_type": "route",
                    "name": "bookRoutes",
                    "mock_plan": {"inline_stubs": ["req", "res"]},
                }
            ],
        }
        spec = build_deterministic_test_plan(graph)[0]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "backend" / "routes" / "bookRoutes.js"
            target.parent.mkdir(parents=True)
            target.write_text("module.exports = require('express').Router();\n", encoding="utf-8")
            test_file = target.parent / "bookRoutes.generated.TC-0001.test.js"

            code = build_test_code(spec, graph["units"][0], str(root), str(test_file), "jest")

            self.assertIn("const request = require('supertest');", code)
            self.assertIn("const routeUnderTest = require('./bookRoutes');", code)
            self.assertIn("it.todo('bookRoutes routes requests through isolated handlers');", code)

    def test_template_builder_uses_named_controller_handler_mocks_for_routes(self) -> None:
        graph = {
            "root_path": "",
            "units": [
                {
                    "id": "route:backend/routes/bookRoutes.js:GET /:1",
                    "relative_path": "backend/routes/bookRoutes.js",
                    "unit_type": "route",
                    "name": "GET /",
                    "mock_plan": {
                        "module_mocks": [
                            {
                                "import_path": "../controllers/bookController",
                                "dependency_type": "local_module",
                                "methods": ["getBooks", "addBook", "deleteBook"],
                            }
                        ]
                    },
                }
            ],
        }
        spec = build_deterministic_test_plan(graph)[0]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "backend" / "routes" / "bookRoutes.js"
            target.parent.mkdir(parents=True)
            target.write_text("module.exports = require('express').Router();\n", encoding="utf-8")
            test_file = target.parent / "bookRoutes.generated.TC-0001.test.js"

            code = build_test_code(spec, graph["units"][0], str(root), str(test_file), "jest")

            self.assertIn("getBooks: jest.fn((req, res) => res.status(200).json([]))", code)
            self.assertIn("addBook: jest.fn((req, res) => res.status(201).json({}))", code)
            self.assertIn("deleteBook: jest.fn((req, res) => res.status(200).json({}))", code)

    def test_template_builder_uses_named_component_dependency_mocks(self) -> None:
        graph = {
            "root_path": "",
            "units": [
                {
                    "id": "component:frontend/src/components/BookList.jsx:BookList:1",
                    "relative_path": "frontend/src/components/BookList.jsx",
                    "unit_type": "component",
                    "name": "BookList",
                    "mock_plan": {
                        "module_mocks": [
                            {"import_path": "../api", "dependency_type": "local_module", "methods": ["getBooks", "deleteBook"]},
                            {"import_path": "../utils", "dependency_type": "local_module", "methods": ["formatRating"]},
                        ]
                    },
                }
            ],
        }
        spec = build_deterministic_test_plan(graph)[0]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "frontend" / "src" / "components" / "BookList.jsx"
            target.parent.mkdir(parents=True)
            target.write_text("export default function BookList() { return <div />; }\n", encoding="utf-8")
            test_file = target.parent / "BookList.generated.TC-0001.test.jsx"

            code = build_test_code(spec, graph["units"][0], str(root), str(test_file), "vitest")

            self.assertIn("vi.mock('../api', () => ({ getBooks: vi.fn().mockResolvedValue([]), deleteBook: vi.fn().mockResolvedValue({}) }));", code)
            self.assertIn("vi.mock('../utils', () => ({ formatRating: vi.fn((value) => String(value)) }));", code)

    def test_excel_store_upserts_by_unit_and_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ExcelStore(Path(tmpdir) / "cases.xlsx")
            first = {"test_id": "TC-0001", "unit_id": "unit:a", "scenario_name": "scenario", "test_code": "old", "status": "Fail"}
            second = {"test_id": "TC-0002", "unit_id": "unit:a", "scenario_name": "scenario", "test_code": "new", "status": ""}

            store.append_rows([first])
            store.upsert_rows([second], ["unit_id", "scenario_name"])
            rows = store.rows()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["test_id"], "TC-0001")
            self.assertEqual(rows[0]["test_code"], "new")
            self.assertIsNone(rows[0]["status"])

    def test_assertion_fragment_validation_rejects_setup_and_imports(self) -> None:
        errors = validate_assertion_fragment("import x from 'y';\njest.mock('z');\nexpect(true).toBe(true);")

        self.assertTrue(any("forbidden" in error for error in errors))

    def test_assertion_generator_creates_localized_body_fragment(self) -> None:
        graph = {
            "units": [
                {
                    "id": "backend/controllers/bookController.js:addBook",
                    "relative_path": "backend/controllers/bookController.js",
                    "unit_type": "controller",
                    "name": "addBook",
                    "mock_plan": {"framework": "jest", "inline_stubs": ["req", "res"]},
                }
            ]
        }
        spec = build_deterministic_test_plan(graph)[0]

        block = generate_deterministic_assertion_block(spec, graph["units"][0])

        self.assertFalse(validate_assertion_fragment(block.body))
        self.assertIn("await handler(req, res, next);", block.body)
        self.assertNotIn("it(", block.body)

    def test_assertion_generator_uses_source_status_and_axios_behavior(self) -> None:
        controller = {
            "id": "backend/controllers/bookController.js:addBook",
            "unit_type": "controller",
            "name": "addBook",
            "source": "exports.addBook = async (req, res) => res.status(201).json({ ok: true });",
            "mock_plan": {"framework": "jest"},
        }
        api_helper = {
            "id": "frontend/src/api.js:getBooks",
            "unit_type": "function",
            "name": "getBooks",
            "source": "export const getBooks = () => axios.get(API_URL);",
            "mock_plan": {"framework": "vitest"},
        }
        controller_spec, api_spec = build_deterministic_test_plan({"units": [controller, api_helper]})

        controller_block = generate_deterministic_assertion_block(controller_spec, controller)
        api_block = generate_deterministic_assertion_block(api_spec, api_helper)

        self.assertIn("toHaveBeenCalledWith(201)", controller_block.body)
        self.assertIn("axios.get", api_block.body)
        self.assertIn("result).toEqual({ data: [] })", api_block.body)

    def test_validation_and_confidence_reject_vacuous_assertions(self) -> None:
        issues = validate_test_code(
            "it('x', () => { expect(document.body).toBeTruthy(); });",
            "component.test.jsx",
            "vitest",
        )
        self.assertIn("vacuous_assertion", {issue.code for issue in issues})

        breakdown = confidence_breakdown(
            {
                "status": "Pass",
                "score": 100,
                "validation_status": "Pass",
                "test_code": "expect(subject).toBeDefined();",
            }
        )
        self.assertLessEqual(breakdown.score, 25)
        self.assertIn("vacuous assertion", breakdown.details)

    def test_template_builder_inserts_assertion_fragment(self) -> None:
        graph = {
            "units": [
                {
                    "id": "backend/controllers/bookController.js:addBook",
                    "relative_path": "backend/controllers/bookController.js",
                    "unit_type": "controller",
                    "name": "addBook",
                    "mock_plan": {"framework": "jest", "inline_stubs": ["req", "res"]},
                }
            ]
        }
        spec = build_deterministic_test_plan(graph)[0]
        block = generate_deterministic_assertion_block(spec, graph["units"][0])

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "backend" / "controllers" / "bookController.js"
            target.parent.mkdir(parents=True)
            target.write_text("exports.addBook = async (req, res) => res.json({ ok: true });\n", encoding="utf-8")
            test_file = target.parent / "bookController.generated.TC-0001.test.js"

            code = build_test_code(spec, graph["units"][0], str(root), str(test_file), "jest", block.body)

            self.assertIn("it('addBook performs its expected behavior', async () => {", code)
            self.assertIn("await handler(req, res, next);", code)
            self.assertNotIn("it.todo", code)

    def test_plan_and_builder_nodes_write_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output = root / "runs"
            (root / "package.json").write_text('{"dependencies":{"express":"latest"}}\n', encoding="utf-8")
            target = root / "backend" / "controllers" / "bookController.js"
            target.parent.mkdir(parents=True)
            target.write_text("exports.addBook = async (req, res) => res.json({ ok: true });\n", encoding="utf-8")
            graph = {
                "units": [
                    {
                        "id": "backend/controllers/bookController.js:addBook",
                        "relative_path": "backend/controllers/bookController.js",
                        "unit_type": "controller",
                        "name": "addBook",
                        "risk_level": "high",
                        "mock_plan": {"inline_stubs": ["req", "res"]},
                    }
                ]
            }
            state: AgentState = {
                "repo_path": str(root),
                "output_dir": str(output),
                "excel_path": str(output / "test_cases.xlsx"),
                "repository_graph": graph,
                "stack": "mern",
            }

            state = test_planner_node(state)
            state = assertion_generator_node(state)
            state = test_builder_node(state)

            self.assertTrue(Path(state["test_plan_path"]).exists())
            self.assertTrue(Path(state["assertion_blocks_path"]).exists())
            self.assertTrue(Path(state["excel_path"]).exists())
            self.assertEqual(state["generated_test_count"], 1)


if __name__ == "__main__":
    unittest.main()
