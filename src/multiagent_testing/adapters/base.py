from __future__ import annotations

from abc import ABC, abstractmethod

from multiagent_testing.models import CodeUnit, TestCaseResult, TestResult


class BaseStackAdapter(ABC):
    name: str

    @abstractmethod
    def detect(self, repo_path: str) -> bool:
        """Return True if this adapter can handle the repo."""

    @abstractmethod
    def discover_units(self, repo_path: str) -> list[CodeUnit]:
        """Return discrete testable code units."""

    @abstractmethod
    def get_test_framework(self) -> str:
        """Return the default test framework name."""

    @abstractmethod
    def get_test_runner_command(self, test_file_path: str) -> list[str]:
        """Return command used to execute a generated test file."""

    def get_test_cwd(self, repo_path: str, test_file_path: str) -> str:
        """Return working directory for executing a generated test file."""
        return repo_path

    def get_coverage_command(self, test_file_path: str) -> list[str]:
        """Return command used to execute a generated test file with coverage."""
        return self.get_test_runner_command(test_file_path)

    @abstractmethod
    def parse_test_output(self, raw_output: str) -> TestResult:
        """Normalize framework output."""

    def parse_test_results(self, raw_output: str) -> list[TestCaseResult]:
        """Normalize framework output into individual assertion-level results."""
        summary = self.parse_test_output(raw_output)
        return [
            TestCaseResult(
                test_title="",
                status=summary.status,
                duration_ms=summary.duration_ms,
                error_message=summary.error_message,
            )
        ]

    def parse_coverage_percent(self, raw_output: str, cwd: str, test_file_path: str) -> float | None:
        """Return line coverage percent for the coverage run when available."""
        return None

    @abstractmethod
    def map_code_location(self, unit: CodeUnit) -> str:
        """Return a precise file:line or file:function reference."""

    def setup_environment(self, repo_path: str) -> None:
        """Optional one-time environment setup for a repo."""
