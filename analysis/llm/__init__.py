"""Multi-LLM client abstraction."""

import sys
import os
from typing import Optional

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import config
from .base import BaseLLMClient


def get_llm_client(provider: Optional[str] = None) -> BaseLLMClient:
    """Get LLM client based on config or explicit provider selection."""
    provider = provider or config.llm_provider

    if provider == "claude":
        from .claude import ClaudeLLMClient
        if not config.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")
        return ClaudeLLMClient(api_key=config.anthropic_api_key, model=config.claude_model)
    elif provider == "openai":
        from .openai_client import OpenAILLMClient
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        return OpenAILLMClient(api_key=config.openai_api_key, model=config.openai_model)
    elif provider == "gemini":
        from .gemini import GeminiLLMClient
        if not config.google_api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")
        return GeminiLLMClient(api_key=config.google_api_key, model=config.gemini_model)
    elif provider == "ollama":
        from .ollama import OllamaLLMClient
        return OllamaLLMClient(model=config.ollama_model, base_url=config.ollama_url)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Use 'claude', 'openai', 'gemini', or 'ollama'.")
