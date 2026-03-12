"""LLM client — unified interface to Ollama, OpenAI, and Anthropic via litellm."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from prompt_pulse.config import LLMConfig

logger = logging.getLogger(__name__)

# Transient HTTP status codes worth retrying.
_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

# Default retry configuration.
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_RETRY_DELAY = 1.0  # seconds


def _is_transient(exc: Exception) -> bool:
    """Return True if *exc* looks like a transient / retriable failure."""
    # Connection-level errors (timeout, refused, DNS, reset)
    transient_types = (
        ConnectionError,
        TimeoutError,
        OSError,
    )
    if isinstance(exc, transient_types):
        return True
    # httpx network errors
    try:
        import httpx

        if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
            return True
    except ImportError:
        pass
    # litellm wraps HTTP status in its own exception hierarchy.
    # Check for a status_code attribute (rate-limit, server errors).
    status = getattr(exc, "status_code", None)
    if status and int(status) in _TRANSIENT_STATUS_CODES:
        return True
    # Some providers include "rate" or "timeout" in the message.
    msg = str(exc).lower()
    if any(kw in msg for kw in ("rate limit", "timed out", "timeout")):
        return True
    return False


@dataclass
class EnhanceResult:
    """Outcome of a prompt-enhancement attempt."""

    text: str
    used_fallback: bool = False
    error: str | None = None


class LLMClient:
    """Wrapper around litellm for prompt enhancement."""

    def __init__(
        self,
        config: LLMConfig,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        retry_delay: float = _DEFAULT_RETRY_DELAY,
    ):
        self._config = config
        self._model_name = self._resolve_model_name()
        self._max_retries = max_retries
        self._retry_delay = retry_delay

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
        """Send a prompt to the LLM and return the response text.

        Retries up to *max_retries* times on transient errors before
        raising.  Permanent errors (auth, invalid model) raise
        immediately.
        """
        import litellm

        api_key = self._config.resolve_api_key()
        last_exc: Exception | None = None

        for attempt in range(1 + self._max_retries):
            try:
                if attempt > 0:
                    delay = self._retry_delay * (2 ** (attempt - 1))
                    logger.info(
                        "Retrying LLM call (attempt %d/%d) in %.1fs…",
                        attempt + 1,
                        1 + self._max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)

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
                last_exc = e
                if _is_transient(e) and attempt < self._max_retries:
                    logger.warning(
                        "Transient LLM error (attempt %d/%d): %s",
                        attempt + 1,
                        1 + self._max_retries,
                        e,
                    )
                    continue
                # Permanent error or final attempt — stop retrying.
                logger.error("LLM call failed: %s", e)
                raise

        # Should not reach here, but satisfy type-checkers.
        raise last_exc  # type: ignore[misc]

    async def is_available(self) -> bool:
        """Check if the configured LLM is reachable."""
        try:
            if self._config.provider == "ollama":
                import httpx

                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        "http://localhost:11434/api/tags",
                        timeout=5.0,
                    )
                    return resp.status_code == 200
            # For cloud providers, assume available if API key is set
            return bool(self._config.resolve_api_key()) or self._config.provider == "ollama"
        except Exception:
            return False


async def enhance_prompt(
    meta_prompt: str,
    config: LLMConfig,
    fallback_text: str | None = None,
) -> EnhanceResult:
    """High-level function: send meta-prompt to LLM.

    Returns an ``EnhanceResult`` with ``used_fallback=True`` and the
    error message when the LLM fails and a fallback is available.
    Raises if no fallback is provided.
    """
    client = LLMClient(config)

    try:
        text = await client.complete(meta_prompt)
        return EnhanceResult(text=text)
    except Exception as e:
        error_msg = str(e)
        if _is_transient(e):
            logger.warning("LLM failed after retries (transient): %s", error_msg)
        else:
            logger.warning("LLM failed (permanent — check config): %s", error_msg)

        if fallback_text:
            return EnhanceResult(
                text=fallback_text,
                used_fallback=True,
                error=error_msg,
            )
        raise
