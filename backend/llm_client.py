"""Anthropic LLM client with rate limiting and cost tracking."""

import logging
import time
from collections import deque

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Wrapper around the Anthropic API with rate limiting, retry logic, and cost tracking."""

    def __init__(self) -> None:
        """Initialize the LLM client with API credentials and rate limiting."""
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model
        self.max_rpm = settings.anthropic_rate_limit_rpm
        self._request_timestamps: deque[float] = deque()
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _enforce_rate_limit(self) -> None:
        now = time.monotonic()
        # Remove timestamps older than 60 seconds
        while self._request_timestamps and now - self._request_timestamps[0] > 60:
            self._request_timestamps.popleft()
        if len(self._request_timestamps) >= self.max_rpm:
            sleep_time = 60 - (now - self._request_timestamps[0])
            if sleep_time > 0:
                logger.info("Rate limit reached, sleeping %.1fs", sleep_time)
                time.sleep(sleep_time)
        self._request_timestamps.append(time.monotonic())

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def create_message(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Send a message to the LLM and return the response text."""
        self._enforce_rate_limit()
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = self.client.messages.create(**kwargs)
        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens
        logger.debug(
            "Tokens used: %d in, %d out",
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        return response.content[0].text

    def get_cost_estimate(self) -> dict[str, float]:
        """Return token counts and estimated cost in USD."""
        input_cost = self.total_input_tokens * settings.llm_input_price_per_million / 1_000_000
        output_cost = self.total_output_tokens * settings.llm_output_price_per_million / 1_000_000
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(input_cost + output_cost, 4),
        }


# Lazy singleton — avoids import-time Anthropic client creation when no API key is set.
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Return the shared LLMClient, creating it on first call."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
