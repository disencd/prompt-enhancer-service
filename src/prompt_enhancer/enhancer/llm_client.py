"""LLM client — unified interface to Ollama, OpenAI, and Anthropic via litellm."""

from __future__ import annotations

import logging

from prompt_enhancer.config import LLMConfig

logger = logging.getLogger(__name__)


class LLMClient:
    """Wrapper around litellm for prompt enhancement."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._model_name = self._resolve_model_name()

    def _resolve_model_name(self) -> str:
        """Resolve the litellm model identifier based on provider."""
        model = self._config.model
        provider = self._config.provider

        # litellm uses provider prefixes
        if provider == "ollama":
            return f"ollama/{model}"
        elif provider == "openai":
            return model  # litellm defaults to OpenAI
        elif provider == "anthropic":
            return f"anthropic/{model}"
        return model

    async def complete(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the response text."""
        import litellm

        api_key = self._config.resolve_api_key()

        try:
            logger.debug(
                "Calling LLM: model=%s, provider=%s",
                self._model_name,
                self._config.provider,
            )

            response = await litellm.acompletion(
                model=self._model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a prompt enhancement engine. "
                            "Output only the enhanced prompt."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                api_key=api_key,
            )

            result = response.choices[0].message.content.strip()
            logger.debug("LLM response length: %d chars", len(result))
            return result

        except Exception as e:
            logger.error("LLM call failed: %s", e)
            raise

    async def is_available(self) -> bool:
        """Check if the configured LLM is reachable."""
        try:
            if self._config.provider == "ollama":
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "http://localhost:11434/api/tags", timeout=5.0
                    )
                    return resp.status_code == 200
            # For cloud providers, assume available if API key is set
            return (
                bool(self._config.resolve_api_key())
                or self._config.provider == "ollama"
            )
        except Exception:
            return False


async def enhance_prompt(
    meta_prompt: str,
    config: LLMConfig,
    fallback_text: str | None = None,
) -> str:
    """High-level function: send meta-prompt to LLM, return enhanced prompt.

    Falls back to fallback_text if LLM fails.
    """
    client = LLMClient(config)

    try:
        return await client.complete(meta_prompt)
    except Exception as e:
        logger.warning("LLM enhancement failed, using fallback: %s", e)
        if fallback_text:
            return fallback_text
        raise
