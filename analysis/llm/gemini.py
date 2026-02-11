"""Google Gemini LLM client."""

import google.generativeai as genai
from .base import BaseLLMClient, LLMResponse


class GeminiLLMClient(BaseLLMClient):
    provider_name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        genai.configure(api_key=api_key)
        self.model_obj = genai.GenerativeModel(
            model,
            system_instruction=None,  # Set per-request
        )
        self.model = model

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        # Recreate model with system instruction for this request
        model = genai.GenerativeModel(
            self.model,
            system_instruction=system_prompt,
            generation_config=genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
                response_mime_type="application/json",
            ),
        )
        response = model.generate_content(user_prompt)
        usage = response.usage_metadata
        return LLMResponse(
            content=response.text,
            model=self.model,
            provider=self.provider_name,
            input_tokens=usage.prompt_token_count if usage else 0,
            output_tokens=usage.candidates_token_count if usage else 0,
        )

    def max_context_tokens(self) -> int:
        return 1000000
