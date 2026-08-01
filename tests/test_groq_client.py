import unittest

from multiagent_testing.groq_client import GroqStructuredClient
from multiagent_testing.models import GeneratedTestBatch


class GroqStructuredClientPromptTests(unittest.TestCase):
    def test_json_prompt_rejects_schema_echo_and_names_data_keys(self) -> None:
        client = GroqStructuredClient(model="test-model")

        prompt = client._json_prompt(GeneratedTestBatch, "Generate tests.")

        self.assertIn("Do not return the schema itself", prompt)
        self.assertIn("schema-only keys such as $defs", prompt)
        self.assertIn("top-level JSON object must contain these data keys: tests", prompt)
        self.assertIn('"tests": []', prompt)

    def test_decode_generated_batch_drops_null_test_code_rows(self) -> None:
        client = GroqStructuredClient(model="test-model")

        batch = client._decode_schema(
            GeneratedTestBatch,
            """
            {
              "tests": [
                {
                  "unit_type": "function",
                  "target_file": "backend/controllers/bookController.js",
                  "target_function_or_route": "getBooks",
                  "test_description": "bad row",
                  "test_code": null,
                  "priority": "High"
                },
                {
                  "unit_type": "function",
                  "target_file": null,
                  "target_function_or_route": "getBooks",
                  "test_description": "good row",
                  "test_code": "test('works', () => {});",
                  "priority": "High"
                }
              ]
            }
            """,
        )

        self.assertEqual(len(batch.tests), 1)
        self.assertEqual(batch.tests[0].target_file, "")
        self.assertEqual(batch.tests[0].test_code, "test('works', () => {});")


if __name__ == "__main__":
    unittest.main()
