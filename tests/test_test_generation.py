import tempfile
import unittest
from pathlib import Path

from multiagent_testing.agents.test_generator import (
    SYSTEM_PROMPT,
    _build_user_prompt,
    _invoke_generation_batch,
    _materialize_test_case,
)
from multiagent_testing.chunking import build_chunk_prompt_context
from multiagent_testing.models import CodeUnit, GeneratedTestCase


class TestGenerationPromptTests(unittest.TestCase):
    def test_prompt_requires_isolated_unit_tests(self) -> None:
        user_prompt = _build_user_prompt("Context", "jest")

        self.assertIn("Generate isolated unit tests", SYSTEM_PROMPT)
        self.assertIn("mock or stub every external side effect", SYSTEM_PROMPT)
        self.assertIn("mock/stub dependencies", user_prompt)
        self.assertIn("Do not call live databases", user_prompt)

    def test_empty_generation_batch_is_retried_with_non_empty_test_code_instruction(self) -> None:
        class LLM:
            def __init__(self) -> None:
                self.prompts = []

            def invoke(self, schema, system_prompt: str, user_prompt: str):
                self.prompts.append(user_prompt)
                if len(self.prompts) == 1:
                    return schema(tests=[])
                return schema(
                    tests=[
                        {
                            "unit_type": "function",
                            "target_file": "backend/utils/math.js",
                            "target_function_or_route": "add",
                            "test_description": "adds numbers",
                            "test_code": "test('adds', () => {});",
                            "priority": "High",
                        }
                    ]
                )

        llm = LLM()

        batch = _invoke_generation_batch(llm, "Context", "jest")

        self.assertEqual(len(batch.tests), 1)
        self.assertEqual(len(llm.prompts), 2)
        self.assertIn("Previous response contained no usable test cases", llm.prompts[1])


class TestGenerationMaterializationTests(unittest.TestCase):
    def test_materialize_persists_adapter_prepared_test_code(self) -> None:
        class Adapter:
            def prepare_test_code(self, test_code: str, test_file_path: str) -> str:
                return f"// prepared for {Path(test_file_path).name}\n{test_code}"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "backend" / "controllers").mkdir(parents=True)
            (root / "backend" / "controllers" / "bookController.js").write_text("module.exports = {};\n", encoding="utf-8")
            test_case = GeneratedTestCase(
                unit_type="function",
                target_file="backend/controllers/bookController.js",
                target_function_or_route="getBooks",
                test_description="gets books",
                test_code="test('returns books', () => {});",
                priority="High",
            )

            row, _ = _materialize_test_case(test_case, str(root), 1, Adapter())

            test_file = Path(row["test_file_path"])
            self.assertTrue(str(row["test_code"]).startswith("// prepared for bookController.generated.TC-0001_getBooks.test.js"))
            self.assertEqual(test_file.read_text(encoding="utf-8"), row["test_code"])


class ChunkContextTests(unittest.TestCase):
    def test_context_includes_direct_local_dependency_source_for_mocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            controllers = root / "backend" / "controllers"
            models = root / "backend" / "models"
            controllers.mkdir(parents=True)
            models.mkdir(parents=True)
            controller = controllers / "bookController.js"
            controller.write_text(
                "const Book = require('../models/Book');\n"
                "async function getBooks(req, res) { const books = await Book.find(); res.json(books); }\n"
                "module.exports = { getBooks };\n",
                encoding="utf-8",
            )
            (models / "Book.js").write_text(
                "const mongoose = require('mongoose');\n"
                "const schema = new mongoose.Schema({ title: String });\n"
                "module.exports = mongoose.model('Book', schema);\n",
                encoding="utf-8",
            )
            unit = CodeUnit(
                id="function:backend/controllers/bookController.js:getBooks:2",
                file_path=str(controller),
                relative_path="backend/controllers/bookController.js",
                unit_type="function",
                name="getBooks",
                start_line=2,
                end_line=2,
                source="async function getBooks(req, res) { const books = await Book.find(); res.json(books); }",
            )

            context = build_chunk_prompt_context([unit], str(root))

            self.assertIn("Direct local dependency context for mocking/stubbing", context)
            self.assertIn("Dependency: backend/models/Book.js", context)
            self.assertIn("mongoose.model('Book'", context)


if __name__ == "__main__":
    unittest.main()
