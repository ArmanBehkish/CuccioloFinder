"""Unit tests for groq_client. SDK calls are mocked at the boundary.

The client is a thin wrapper — the goals here are:
- correct prompt structure (system + user roles)
- correct parameter passing (json_mode, max_tokens, temperature)
- error mapping (SDK exceptions → GroqError)
- JSON parse fallback (regex extract from non-strict output)
- `is_responsive()` truthiness behavior
"""

import pytest

import cucciolofinder.enrichment.groq_client as gc
from cucciolofinder.enrichment.groq_client import (
    GroqError,
    groq_extract_filters,
    groq_translate_description,
)


@pytest.fixture(autouse=True)
def reset_client(monkeypatch):
    """Clear the cached SDK client and ensure GROQ_API_KEY is set."""
    gc._client = None
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    yield
    gc._client = None


def _patch_chat(monkeypatch, content):
    """Replace `_chat_completion` with a stub that records its inputs."""
    calls = {}

    def fake(messages, *, json_mode, temperature, max_tokens):
        calls["messages"] = messages
        calls["json_mode"] = json_mode
        calls["temperature"] = temperature
        calls["max_tokens"] = max_tokens
        return content

    monkeypatch.setattr(gc, "_chat_completion", fake)
    return calls


# Translation -----------------------------------------------------------


def test_translate_returns_stripped_content(monkeypatch):
    _patch_chat(monkeypatch, "  Hello world.  \n")
    assert groq_translate_description("Ciao mondo.") == "Hello world."


def test_translate_empty_input_short_circuits(monkeypatch):
    # _chat_completion should NOT be called for empty input
    called = {"hit": False}

    def boom(*a, **kw):
        called["hit"] = True
        return ""

    monkeypatch.setattr(gc, "_chat_completion", boom)
    assert groq_translate_description("") == ""
    assert groq_translate_description("   ") == ""
    assert called["hit"] is False


def test_translate_uses_input_scaled_max_tokens(monkeypatch):
    calls = _patch_chat(monkeypatch, "ok")
    # 300 chars / 3 = 100 → expect max_tokens=100
    groq_translate_description("x" * 300)
    assert calls["max_tokens"] == 100


def test_translate_min_max_tokens_floor(monkeypatch):
    calls = _patch_chat(monkeypatch, "ok")
    # very short input — floor at 50
    groq_translate_description("ciao")
    assert calls["max_tokens"] == 50


def test_translate_passes_system_user_roles(monkeypatch):
    calls = _patch_chat(monkeypatch, "out")
    groq_translate_description("Cane bello")
    msgs = calls["messages"]
    assert msgs[0]["role"] == "system"
    assert "Italian" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "Cane bello"
    assert calls["json_mode"] is False


# Extraction ------------------------------------------------------------


def test_extract_returns_dict_and_raw(monkeypatch):
    calls = _patch_chat(
        monkeypatch,
        '{"size": "large", "gender": "male", "good_with": ["children"]}',
    )
    filters, raw = groq_extract_filters("big male good with kids", "SYS")
    assert filters == {"size": "large", "gender": "male", "good_with": ["children"]}
    assert raw == '{"size": "large", "gender": "male", "good_with": ["children"]}'
    assert calls["json_mode"] is True
    assert calls["temperature"] == 0.0
    assert calls["max_tokens"] == 300
    # System prompt is whatever the caller passed in
    assert calls["messages"][0] == {"role": "system", "content": "SYS"}
    assert "big male good with kids" in calls["messages"][1]["content"]


def test_extract_strips_unknown_keys(monkeypatch):
    _patch_chat(
        monkeypatch,
        '{"size": "small", "color": "brown", "evil_key": 42}',
    )
    filters, _ = groq_extract_filters("small dog", "SYS")
    assert filters == {"size": "small"}
    assert "color" not in filters and "evil_key" not in filters


def test_extract_regex_fallback_on_wrapped_json(monkeypatch):
    """JSON mode usually guarantees clean output, but stay symmetric with Mistral."""
    _patch_chat(
        monkeypatch,
        'Sure! Here you go: {"size":"medium"} hope that helps.',
    )
    filters, raw = groq_extract_filters("medium dog", "SYS")
    assert filters == {"size": "medium"}


def test_extract_returns_empty_on_unparseable(monkeypatch):
    _patch_chat(monkeypatch, "I have no idea what you're asking.")
    filters, raw = groq_extract_filters("???", "SYS")
    assert filters == {}
    assert raw == "I have no idea what you're asking."


def test_extract_returns_empty_on_non_dict_json(monkeypatch):
    _patch_chat(monkeypatch, '["large", "male"]')
    filters, _ = groq_extract_filters("query", "SYS")
    assert filters == {}


# Error mapping ---------------------------------------------------------


def _fake_response(status_code: int):
    """Build a minimal httpx.Response wired to a request — what the SDK's
    typed exceptions expect in their `response=` kwarg."""
    import httpx

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return httpx.Response(status_code=status_code, request=request)


def test_chat_completion_maps_auth_error(monkeypatch):
    from groq import AuthenticationError

    class FakeChat:
        class completions:
            @staticmethod
            def create(**kwargs):
                raise AuthenticationError(
                    message="bad key", response=_fake_response(401), body=None
                )

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(gc, "_get_client", lambda: FakeClient())

    with pytest.raises(GroqError, match="auth failed"):
        gc._chat_completion(
            [{"role": "user", "content": "hi"}],
            json_mode=False,
            temperature=0.0,
            max_tokens=10,
        )


def test_chat_completion_maps_rate_limit(monkeypatch):
    from groq import RateLimitError

    class FakeChat:
        class completions:
            @staticmethod
            def create(**kwargs):
                raise RateLimitError(
                    message="429", response=_fake_response(429), body=None
                )

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(gc, "_get_client", lambda: FakeClient())

    with pytest.raises(GroqError, match="rate-limited"):
        gc._chat_completion(
            [{"role": "user", "content": "hi"}],
            json_mode=False,
            temperature=0.0,
            max_tokens=10,
        )


def test_get_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    gc._client = None
    with pytest.raises(GroqError, match="GROQ_API_KEY is empty"):
        gc._get_client()


# is_responsive ---------------------------------------------------------


def test_is_responsive_true_on_success(monkeypatch):
    class FakeModels:
        @staticmethod
        def list():
            return {"data": []}

    class FakeOptions:
        models = FakeModels()

    class FakeClient:
        @staticmethod
        def with_options(*, timeout, max_retries):
            return FakeOptions()

    monkeypatch.setattr(gc, "_get_client", lambda: FakeClient())
    assert gc.is_responsive() is True


def test_is_responsive_false_on_auth_error(monkeypatch):
    from groq import AuthenticationError

    class FakeOptions:
        class models:
            @staticmethod
            def list():
                raise AuthenticationError(
                    message="bad key", response=_fake_response(401), body=None
                )

    class FakeClient:
        @staticmethod
        def with_options(*, timeout, max_retries):
            return FakeOptions()

    monkeypatch.setattr(gc, "_get_client", lambda: FakeClient())
    assert gc.is_responsive() is False


def test_is_responsive_false_when_key_missing(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    gc._client = None
    assert gc.is_responsive() is False
