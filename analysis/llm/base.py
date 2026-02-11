"""Base LLM client interface."""

from abc import ABC, abstractmethod
from pydantic import BaseModel


class LLMResponse(BaseModel):
    """Standardized response from any LLM provider."""
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0


class BaseLLMClient(ABC):
    """Abstract base for LLM providers."""

    provider_name: str

    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send a completion request and return structured response."""
        ...

    @abstractmethod
    def max_context_tokens(self) -> int:
        """Maximum context window size in tokens."""
        ...

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (~4 chars per token)."""
        return len(text) // 4
