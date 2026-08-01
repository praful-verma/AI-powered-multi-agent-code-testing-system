from __future__ import annotations

import os
import json
import re
import time
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class GroqStructuredClient:
    def __init__(
        self,
        model: str,
        temperature: float = 0.1,
        max_retries: int = 3,
        sleep_seconds: float = 1.0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.sleep_seconds = sleep_seconds

    def invoke(self, schema: type[T], system_prompt: str, user_prompt: str) -> T:
        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError(
                "GROQ_API_KEY is not set. Put it in a repo-root .env file or export it in the current shell."
            )
        from langchain_groq import ChatGroq

        llm = ChatGroq(
            model=self.model,
            temperature=self.temperature,
            max_retries=self.max_retries,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                retry_note = ""
                if last_error is not None:
                    retry_note = (
                        "\n\nPrevious response was invalid: "
                        f"{last_error}. Return the data object only, not the JSON schema."
                    )
                response = llm.invoke(
                    [
                        (
                            "system",
                            f"{system_prompt}\n\nReturn one JSON object only. Do not wrap the answer in markdown.",
                        ),
                        ("user", self._json_prompt(schema, user_prompt) + retry_note),
                    ]
                )
                content = getattr(response, "content", response)
                if isinstance(content, list):
                    content = "".join(str(part) for part in content)
                return self._decode_schema(schema, str(content))
            except Exception as exc:
                recovered = self._parse_failed_generation(schema, exc)
                if recovered is not None:
                    return recovered
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.sleep_seconds * (2**attempt))
        raise RuntimeError(f"Groq structured call failed after retries: {last_error}") from last_error

    def _json_prompt(self, schema: type[T], user_prompt: str) -> str:
        return (
            f"{user_prompt}\n\n"
            "Return exactly one JSON data object that validates against this schema.\n"
            "Do not return the schema itself. Do not include schema-only keys such as $defs, properties, title, or type unless they are real data fields.\n"
            f"The top-level JSON object must contain these data keys: {', '.join(schema.model_fields)}.\n"
            "Example shape only: "
            f"{json.dumps({name: [] if name.endswith('s') else '' for name in schema.model_fields})}\n"
            f"{json.dumps(schema.model_json_schema(), separators=(',', ':'))}"
        )

    def _decode_schema(self, schema: type[T], content: str) -> T:
        extracted = self._extract_json_object(content)
        if extracted is None:
            raise ValueError(f"Model did not return valid JSON: {content[:1000]}")
        return schema.model_validate(extracted)

    def _parse_failed_generation(self, schema: type[T], exc: Exception) -> T | None:
        text = str(exc)
        for candidate in self._candidate_payloads(text):
            try:
                return self._decode_schema(schema, candidate)
            except Exception:
                continue
        return None

    def _candidate_payloads(self, text: str) -> list[str]:
        candidates: list[str] = []
        markers = ["failed_generation", "<function="]
        if not any(marker in text for marker in markers):
            return candidates

        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            candidates.append(text[brace_start : brace_end + 1])

        quoted = re.search(r"'failed_generation':\s*'(.+)'", text, flags=re.DOTALL)
        if quoted:
            candidates.append(quoted.group(1))

        double_quoted = re.search(r'"failed_generation":\s*"(.+)"', text, flags=re.DOTALL)
        if double_quoted:
            candidates.append(double_quoted.group(1))

        return candidates

    def _extract_json_object(self, content: str) -> dict | list | None:
        content = content.strip()
        if not content:
            return None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, (dict, list)) else None
