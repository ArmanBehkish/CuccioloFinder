"""Thin wrapper around the OpenAI Python SDK pointed at OpenRouter.

OpenRouter is OpenAI-compatible, so we reuse the official `openai` SDK
with a custom `base_url`. Public surface mirrors `groq_client.py` exactly
so the dispatchers in extract.py / api.py / translator.py / enrich.py can
add an `openrouter` branch without further refactoring:

    openrouter_translate_description(text)            → str
    openrouter_extract_filters(query, system_prompt)  → (filters_dict, raw_output)
    openrouter_extract_field(...)                     → str | list[str] | None
    openrouter_extract_good_bad_with(description_en)  → (list[str], list[str])
    is_responsive(timeout=5.0)                        → bool

Same model family as Groq (`meta-llama/llama-3.3-70b-instruct` on OR vs
`llama-3.3-70b-versatile` on Groq), so prompts, JSON-mode usage, and the
input-scaled `max_tokens` heuristic are imported verbatim from
`groq_client.py` rather than duplicated.

Retry strategy: SDK built-in retry handles 429 (Retry-After honored) and
5xx with exponential backoff + jitter. We pin `max_retries=2`. Auth errors
raise immediately.
"""

import json
import os
import re
import time
from typing import Any

from loguru import logger
from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)

from .groq_client import (
    _EXTRACT_FIELD_RULES,
    _GOOD_BAD_WITH_RULES,
    _TRANSLATION_SYSTEM,
    _VALID_KEYS,
    _coerce_extracted_value,
    _coerce_string_list,
    _parse_last_json_with_keys,
    _try_parse_extract_json,
)

_DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_RETRIES = 2  # SDK convention: total attempts = max_retries + 1


class OpenRouterError(RuntimeError):
    """Wraps SDK errors at our boundary so callers don't need to import openai.*."""


_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazily construct the OpenAI SDK client pointed at OpenRouter."""
    global _client
    if _client is None:
        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if not api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is empty")

        # `OPENROUTER_BASE_URL` may be set to empty string in `.env` (the
        # template ships with `OPENROUTER_BASE_URL=`) — same gotcha as the
        # GROQ_BASE_URL case: empty env var should mean "use default", not
        # literal "". Normalize before handing to the SDK.
        base_url = (
            (os.environ.get("OPENROUTER_BASE_URL") or "").strip()
            or _DEFAULT_BASE_URL
        )
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "max_retries": _DEFAULT_MAX_RETRIES,
            "timeout": float(os.environ.get("OPENROUTER_TIMEOUT") or _DEFAULT_TIMEOUT),
        }
        _client = OpenAI(**kwargs)
    return _client


def _model() -> str:
    return os.environ.get("OPENROUTER_MODEL") or _DEFAULT_MODEL


def _chat_completion(
    messages: list[dict],
    *,
    json_mode: bool,
    temperature: float,
    max_tokens: int,
) -> str:
    """Single SDK call. Maps SDK exceptions onto OpenRouterError."""
    client = _get_client()
    kwargs: dict[str, Any] = {
        "model": _model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        completion = client.chat.completions.create(**kwargs)
    except AuthenticationError as e:
        raise OpenRouterError(f"OpenRouter auth failed: {e}") from e
    except RateLimitError as e:
        raise OpenRouterError(f"OpenRouter rate-limited after retries: {e}") from e
    except APIConnectionError as e:
        raise OpenRouterError(f"OpenRouter unreachable after retries: {e}") from e
    except APIStatusError as e:
        raise OpenRouterError(f"OpenRouter HTTP {e.status_code}: {e}") from e
    except APIError as e:
        raise OpenRouterError(f"OpenRouter error: {e}") from e

    try:
        return completion.choices[0].message.content or ""
    except (AttributeError, IndexError) as e:
        raise OpenRouterError(f"OpenRouter returned malformed completion: {e}") from e


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def openrouter_translate_description(text: str) -> str:
    """Translate an Italian description to English in a single OpenRouter call.

    Same prompt and `max_tokens` heuristic as the Groq path — Llama 3.3
    behaves the same regardless of provider.
    """
    if not text or not text.strip():
        return ""

    stripped = text.strip()
    max_tokens = max(50, len(stripped) // 3)

    messages = [
        {"role": "system", "content": _TRANSLATION_SYSTEM},
        {"role": "user", "content": stripped},
    ]
    t0 = time.time()
    content = _chat_completion(
        messages,
        json_mode=False,
        temperature=0.2,
        max_tokens=max_tokens,
    )
    elapsed = time.time() - t0
    out = content.strip()
    logger.info(
        f"OpenRouter translation: {len(stripped)}→{len(out)} chars in {elapsed:.1f}s "
        f"(max_tokens={max_tokens})"
    )
    return out


# ---------------------------------------------------------------------------
# Filter extraction (search)
# ---------------------------------------------------------------------------


def openrouter_extract_filters(query: str, system_prompt: str) -> tuple[dict, str]:
    """Extract filters via OpenRouter with JSON mode on.

    Mirrors `groq_extract_filters`: the caller (api.py) builds
    `system_prompt` from the live enums cache so good_with/bad_with valid
    values reflect the DB. Returns `(filters_dict, raw_output)`.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Text: \"{query}\""},
    ]
    raw = _chat_completion(
        messages,
        json_mode=True,
        temperature=0.0,
        max_tokens=300,
    ).strip()
    logger.info(f"OpenRouter extraction raw output: {raw!r}")

    parsed = _try_parse_filters_json(raw)
    if parsed is None:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = _try_parse_filters_json(match.group())

    if parsed is None:
        logger.warning(
            f"OpenRouter returned non-JSON despite json_mode=True: {raw!r}"
        )
        return {}, raw

    return parsed, raw


def _try_parse_filters_json(text: str) -> dict | None:
    """Filter-extraction parser: keeps only known top-level keys."""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    return {k: v for k, v in obj.items() if k in _VALID_KEYS}


# ---------------------------------------------------------------------------
# Per-field extraction from an English description (Stage 2)
# ---------------------------------------------------------------------------


def openrouter_extract_field(
    description_en: str,
    field_name: str,
    *,
    value_type: str,
    allowed_values: list[str] | None = None,
    field_description: str = "",
    max_tokens: int = 200,
) -> str | list[str] | None:
    """Extract one field from an English description via OpenRouter.

    Same contract as `groq_extract_field`. Reuses the shared rules prompt
    and value coercion so a switch between providers is a no-op for callers.
    """
    if not description_en or not description_en.strip():
        return None
    if value_type not in ("enum", "list", "string"):
        raise ValueError(f"unknown value_type: {value_type}")
    if value_type == "enum" and not allowed_values:
        raise ValueError("enum requires allowed_values")

    user_lines = [f"Field to extract: {field_name}"]
    if field_description:
        user_lines.append(f"Field meaning: {field_description}")
    user_lines.append(f"Output type: {value_type}")
    if allowed_values:
        user_lines.append(f"Allowed values (verbatim): {allowed_values}")
    user_lines.append("")
    user_lines.append("Description:")
    user_lines.append(description_en.strip())
    user_content = "\n".join(user_lines)

    messages = [
        {"role": "system", "content": _EXTRACT_FIELD_RULES},
        {"role": "user", "content": user_content},
    ]
    raw = _chat_completion(
        messages,
        json_mode=True,
        temperature=0.0,
        max_tokens=max_tokens,
    ).strip()

    parsed = _parse_last_json_with_keys(raw, ("value",))
    if parsed is None:
        logger.warning(
            f"OpenRouter extraction returned non-JSON for {field_name}: {raw!r}"
        )
        return None

    value = parsed.get("value")
    return _coerce_extracted_value(field_name, value, value_type, allowed_values)


# ---------------------------------------------------------------------------
# Combined good_with + bad_with extraction (Stage 2)
# ---------------------------------------------------------------------------


def openrouter_extract_good_bad_with(description_en: str) -> tuple[list[str], list[str]]:
    """Extract good_with + bad_with as a single OpenRouter call.

    Mirrors `groq_extract_good_bad_with`. Same prompt, same dedup rule.
    """
    if not description_en or not description_en.strip():
        return [], []

    messages = [
        {"role": "system", "content": _GOOD_BAD_WITH_RULES},
        {"role": "user", "content": f"Description:\n{description_en.strip()}"},
    ]
    raw = _chat_completion(
        messages,
        json_mode=True,
        temperature=0.0,
        max_tokens=300,
    ).strip()

    parsed = _parse_last_json_with_keys(raw, ("good_with", "bad_with"))
    if parsed is None:
        logger.warning(f"OpenRouter returned non-JSON for good/bad_with: {raw!r}")
        return [], []

    good = _coerce_string_list(parsed.get("good_with"))
    bad = _coerce_string_list(parsed.get("bad_with"))
    if good and bad:
        good_lower = {g.lower() for g in good}
        bad = [b for b in bad if b.lower() not in good_lower]
    return good, bad


# ---------------------------------------------------------------------------
# Liveness probe (for /api/health)
# ---------------------------------------------------------------------------


def is_responsive(timeout: float = 5.0) -> bool:
    """Cheap probe — list available models with the configured key.

    OpenRouter exposes `GET /api/v1/models` with OpenAI-shaped responses,
    so the SDK's `client.models.list()` works directly. The api.py health
    handler caches the result for 30 s to avoid hammering OR on every poll.
    """
    try:
        client = _get_client()
    except OpenRouterError:
        return False
    try:
        client.with_options(timeout=timeout, max_retries=0).models.list()
    except (AuthenticationError, APIError, APIConnectionError) as e:
        logger.warning(f"OpenRouter is_responsive probe failed: {e}")
        return False
    except Exception as e:  # noqa: BLE001 — defensive net for any SDK-internal error
        logger.warning(f"OpenRouter is_responsive probe unexpected error: {e}")
        return False
    return True
