from __future__ import annotations

from multiagent_testing.adapters.base import BaseStackAdapter
from multiagent_testing.adapters.mern import MERNAdapter


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, type[BaseStackAdapter]] = {}

    def register(self, adapter_cls: type[BaseStackAdapter]) -> None:
        self._adapters[adapter_cls.name] = adapter_cls

    def create(self, name: str) -> BaseStackAdapter:
        if name not in self._adapters:
            known = ", ".join(sorted(self._adapters))
            raise ValueError(f"Unknown stack '{name}'. Known stacks: {known}")
        return self._adapters[name]()

    def detect(self, repo_path: str, stack: str | None = None) -> BaseStackAdapter:
        if stack and stack != "auto":
            adapter = self.create(stack)
            if not adapter.detect(repo_path):
                raise ValueError(f"Stack override '{stack}' did not match repo at {repo_path}")
            return adapter

        for adapter_cls in self._adapters.values():
            adapter = adapter_cls()
            if adapter.detect(repo_path):
                return adapter

        known = ", ".join(sorted(self._adapters))
        raise ValueError(f"No adapter detected for {repo_path}. Known stacks: {known}")


DEFAULT_REGISTRY = AdapterRegistry()
DEFAULT_REGISTRY.register(MERNAdapter)
