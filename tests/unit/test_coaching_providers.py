import json
from types import SimpleNamespace

import httpx
import pytest

from chesscoach.coaching.providers import (
    AnthropicProvider,
    LLMError,
    OpenAICompatibleProvider,
    get_provider,
)
from chesscoach.core.config import Settings

SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "string"}},
    "required": ["a"],
    "additionalProperties": False,
}


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(
    stop_reason="end_turn", text='{"a": "x"}', iterations=None, model="claude-opus-5-5"
):
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    response = SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber"),
        content=content,
        model=model,
        _request_id="req_1",
        usage=SimpleNamespace(
            input_tokens=100, output_tokens=50, cache_read_input_tokens=0, iterations=iterations
        ),
    )
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def anthropic(client, **settings):
    return AnthropicProvider(Settings(llm_enabled=True, **settings), client=client)


def test_anthropic_request_shape_and_result():
    client, messages = fake_client()
    result = anthropic(client, llm_effort="low").generate(system="S", user="U", schema=SCHEMA)
    kw = messages.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["fallbacks"] == "default"
    assert kw["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": SCHEMA},
    }
    assert kw["system"] == "S" and kw["messages"] == [{"role": "user", "content": "U"}]
    assert "thinking" not in kw  # Opus 5.5 thinks adaptively; effort is the control
    assert result.data == {"a": "x"}
    assert result.usage["input_tokens"] == 100
    assert result.metadata["served_by_fallback"] is False


def test_anthropic_reports_server_side_fallback():
    client, _ = fake_client(
        iterations=[SimpleNamespace(type="message"), SimpleNamespace(type="fallback_message")],
        model="claude-opus-4-8",
    )
    result = anthropic(client).generate(system="S", user="U", schema=SCHEMA)
    assert result.metadata["served_by_fallback"] is True
    assert result.model == "claude-opus-4-8"


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"stop_reason": "refusal"}, "declined"),
        ({"stop_reason": "max_tokens"}, "truncated"),
        ({"text": None}, "no text"),
        ({"text": "not json"}, "not valid JSON"),
    ],
)
def test_anthropic_failures_raise_llm_error(kwargs, fragment):
    client, _ = fake_client(**kwargs)
    with pytest.raises(LLMError, match=fragment):
        anthropic(client).generate(system="S", user="U", schema=SCHEMA)


def openai(handler, **settings):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    s = Settings(
        llm_enabled=True,
        llm_provider="openai_compatible",
        llm_base_url="https://llm.example/v1",
        llm_model="m",
        **settings,
    )
    return OpenAICompatibleProvider(s, http_client=http)


def test_openai_compatible_success_and_body():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "m",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "choices": [{"finish_reason": "stop", "message": {"content": '{"a": "y"}'}}],
            },
        )

    result = openai(handler).generate(system="S", user="U", schema=SCHEMA)
    assert seen["url"] == "https://llm.example/v1/chat/completions"
    assert seen["body"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert result.data == {"a": "y"} and result.usage == {"input_tokens": 10, "output_tokens": 5}


def test_openai_compatible_retries_server_errors(monkeypatch):
    monkeypatch.setattr("chesscoach.coaching.providers.time.sleep", lambda s: None)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": "z"}'}}]})

    assert openai(handler).generate(system="S", user="U", schema=SCHEMA).data == {"a": "z"}
    assert len(calls) == 2


def test_openai_compatible_truncation_and_client_errors():
    def truncated(request):
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
        )

    with pytest.raises(LLMError, match="truncated"):
        openai(truncated).generate(system="S", user="U", schema=SCHEMA)
    with pytest.raises(LLMError, match="400"):
        openai(lambda r: httpx.Response(400)).generate(system="S", user="U", schema=SCHEMA)


def test_openai_compatible_token_field_and_error_message():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            404, json={"error": {"message": "The model `openai/gpt-6.1-sol` does not exist"}}
        )

    provider = openai(handler, llm_max_tokens_field="max_completion_tokens")
    with pytest.raises(LLMError, match="404: The model `openai/gpt-6.1-sol` does not exist"):
        provider.generate(system="S", user="U", schema=SCHEMA)
    assert "max_completion_tokens" in seen["body"] and "max_tokens" not in seen["body"]


def test_plan_provider_uses_the_plan_model_and_budget():
    from chesscoach.coaching.plan import plan_provider

    base = dict(
        llm_enabled=True,
        llm_provider="openai_compatible",
        llm_base_url="https://llm.example/v1",
        llm_model="general-model",
    )
    assert plan_provider(Settings(**base)).model == "general-model"
    p = plan_provider(
        Settings(**base, llm_plan_model="openai/gpt-6.1-sol", llm_plan_max_tokens=9000)
    )
    assert p.model == "openai/gpt-6.1-sol" and p.max_tokens == 9000
    assert plan_provider(Settings()) is None


def test_openai_compatible_requires_base_url():
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(Settings(llm_enabled=True, llm_provider="openai_compatible"))


def test_disabled_by_default():
    assert get_provider(Settings()) is None
