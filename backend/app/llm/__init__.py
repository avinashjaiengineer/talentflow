from collections.abc import Callable
from functools import lru_cache
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..config import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class LLM(Protocol):
    name: str

    def structured(self, *, agent: str, system: str, prompt: str, schema: type[T]) -> T:
        """Run one call and return output validated against `schema`."""
        ...


class MockLLM:
    """Offline mode: agents fall back to their deterministic heuristics."""

    name = "mock"

    def structured(self, *, agent: str, system: str, prompt: str, schema: type[T]) -> T:
        raise LLMError("MockLLM has no model; pass a heuristic to run_structured()")


@lru_cache
def get_llm() -> LLM:
    settings = get_settings()
    if settings.use_mock_llm:
        return MockLLM()
    from .claude import ClaudeLLM

    return ClaudeLLM(settings)


def run_structured(
    *, agent: str, system: str, prompt: str, schema: type[T], heuristic: Callable[[], T]
) -> T:
    llm = get_llm()
    if isinstance(llm, MockLLM):
        return heuristic()
    return llm.structured(agent=agent, system=system, prompt=prompt, schema=schema)
