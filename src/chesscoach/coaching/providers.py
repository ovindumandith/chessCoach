"""LLM provider adapters behind one interface. No chess logic lives here.

Providers return the raw JSON object the model produced plus usage metadata. They raise
LLMError for anything that should trigger the deterministic fallback.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import anthropic
import httpx

from chesscoach.core.config import Settings


class LLMError(Exception):
    """The provider could not produce a usable response (network, refusal, truncation...)."""


@dataclass
class LLMResult:
    data: dict
    provider: str
    model: str  # the model that actually served the request
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    metadata: dict = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str
    model: str

    def generate(self, *, system: str, user: str, schema: dict) -> LLMResult: ...


# --------------------------------------------------------------------------- Anthropic


class AnthropicProvider:
    """Claude via the official Anthropic SDK, with structured JSON output.

    Server-side refusal fallback is enabled (`fallbacks: "default"`): if the requested
    model's safety classifiers decline, the API re-runs the request on Anthropic's
    recommended fallback model, so a false positive does not become an outage.
    """

    name = "anthropic"
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(self, settings: Settings, client=None):
        self.model = settings.llm_model
        self.effort = settings.llm_effort
        self.max_tokens = settings.llm_max_tokens
        self.client = client or anthropic.Anthropic(
            api_key=settings.llm_api_key or None,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    def generate(self, *, system: str, user: str, schema: dict) -> LLMResult:
        a = anthropic
        started = time.monotonic()
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                betas=[self.FALLBACK_BETA],
                fallbacks="default",
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "effort": self.effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except a.RateLimitError as exc:
            raise LLMError(f"rate limited: {exc.message}") from exc
        except a.APIStatusError as exc:
            raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise LLMError(f"connection error: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise LLMError(f"model declined the request (category: {category})")
        if response.stop_reason == "max_tokens":
            raise LLMError("response truncated at max_tokens")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError("response contained no text block")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError("response was not valid JSON") from exc

        usage = response.usage
        served_by_fallback = any(
            getattr(entry, "type", None) == "fallback_message"
            for entry in (getattr(usage, "iterations", None) or [])
        )
        return LLMResult(
            data=data,
            provider=self.name,
            model=response.model,
            usage={
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            },
            latency_ms=latency_ms,
            metadata={
                "requested_model": self.model,
                "served_by_fallback": served_by_fallback,
                "request_id": getattr(response, "_request_id", None),
                "effort": self.effort,
            },
        )


# --------------------------------------------------------------------------- OpenAI-compatible


class OpenAICompatibleProvider:
    """Any server exposing an OpenAI-style /chat/completions endpoint with JSON-schema
    response formats (plain HTTP, no vendor SDK)."""

    name = "openai_compatible"

    def __init__(self, settings: Settings, http_client=None):
        if not settings.llm_base_url:
            raise ValueError("LLM_BASE_URL is required for the openai_compatible provider")
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        self.max_tokens_field = settings.llm_max_tokens_field
        self.max_retries = settings.llm_max_retries
        self.url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = (
            {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
        )
        self.http = http_client or httpx.Client(
            timeout=settings.llm_timeout_seconds, headers=headers
        )

    def generate(self, *, system: str, user: str, schema: dict) -> LLMResult:
        body = {
            "model": self.model,
            self.max_tokens_field: self.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "coaching_response", "schema": schema, "strict": True},
            },
        }
        started = time.monotonic()
        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.http.post(self.url, json=body)
            except httpx.HTTPError as exc:
                if attempt == self.max_retries:
                    raise LLMError(f"connection error: {exc}") from exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == self.max_retries:
                    raise LLMError(f"API error {response.status_code}: {_error_text(response)}")
                time.sleep(min(2**attempt, 8))
                continue
            break
        if response.status_code >= 400:
            # e.g. a wrong model id or key: keep the provider's message, it says what to fix.
            raise LLMError(f"API error {response.status_code}: {_error_text(response)}")
        payload = response.json()
        try:
            choice = payload["choices"][0]
            if choice.get("finish_reason") == "length":
                raise LLMError("response truncated at max_tokens")
            data = json.loads(choice["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError("unexpected response shape") from exc
        usage = payload.get("usage") or {}
        return LLMResult(
            data=data,
            provider=self.name,
            model=payload.get("model", self.model),
            usage={
                "input_tokens": usage.get("prompt_tokens"),
                "output_tokens": usage.get("completion_tokens"),
            },
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def _error_text(response: httpx.Response, limit: int = 300) -> str:
    """The provider's error message (never contains our key), shortened."""
    try:
        err = response.json().get("error", {})
        text = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        text = response.text
    return (text or "").strip()[:limit]


# --------------------------------------------------------------------------- testing


class MockProvider:
    """Deterministic provider for tests: returns whatever `responder(user_json)` returns."""

    name = "mock"

    def __init__(self, responder: Callable[[dict], dict], model: str = "mock-model"):
        self.model = model
        self.responder = responder
        self.calls: list[dict] = []

    def generate(self, *, system: str, user: str, schema: dict) -> LLMResult:
        context = json.loads(user)
        self.calls.append(context)
        data = self.responder(context)
        if isinstance(data, Exception):
            raise data
        return LLMResult(
            data=data,
            provider=self.name,
            model=self.model,
            usage={"input_tokens": len(user) // 4, "output_tokens": 200},
            latency_ms=1,
        )


def get_provider(settings: Settings) -> LLMProvider | None:
    """The configured provider, or None when LLM coaching is disabled."""
    if not settings.llm_enabled:
        return None
    if settings.llm_provider == "anthropic":
        return AnthropicProvider(settings)
    return OpenAICompatibleProvider(settings)
