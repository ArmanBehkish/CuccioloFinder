"""Thin wrapper around the official `groq` SDK for translation and filter extraction.

Two public call sites used by translator.py and api.py:

    groq_translate_description(text)      → str
    groq_extract_filters(query)           → (filters_dict, raw_output)

Plus a lightweight liveness probe for /api/health:

    is_responsive()                       → bool

Retry strategy:
    The SDK's built-in retry handles 429 (Retry-After honored) and 5xx with
    exponential backoff + jitter. We pin `max_retries=2` (3 attempts total)
    and let typed exceptions surface to callers. Auth errors (401/403) raise
    `groq.AuthenticationError` immediately, no retry — these are config bugs.

The extraction system prompt is built per-request by api.py's
`_build_extraction_system_prompt` and passed to `groq_extract_filters` as
the `system_prompt` argument; the translation system prompt is the static
`_TRANSLATION_SYSTEM` defined below.
"""

import json
import os
import re
import time
from typing import Any

from groq import (
    APIConnectionError,
    APIError,
    APIStatusError,
    AuthenticationError,
    Groq,
    RateLimitError,
)
from loguru import logger

_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_DEFAULT_BASE_URL = "https://api.groq.com"
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_RETRIES = 2  # SDK convention: total attempts = max_retries + 1


class GroqError(RuntimeError):
    """Wraps SDK errors at our boundary so callers don't need to import groq.*."""


_client: Groq | None = None


def _get_client() -> Groq:
    """Lazily construct the Groq SDK client. Reads env on first call."""
    global _client
    if _client is None:
        api_key = (os.environ.get("GROQ_API_KEY") or "").strip()
        if not api_key:
            raise GroqError("GROQ_API_KEY is empty")

        # `GROQ_BASE_URL` may be set to empty string in .env (the template ships
        # with `GROQ_BASE_URL=`) — the SDK reads the env var itself and treats
        # `""` as a real base URL, producing scheme-less request URLs. Always
        # pass an explicit base_url so the SDK never falls through to env read.
        base_url = (os.environ.get("GROQ_BASE_URL") or "").strip() or _DEFAULT_BASE_URL
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "max_retries": _DEFAULT_MAX_RETRIES,
            "timeout": float(os.environ.get("GROQ_TIMEOUT") or _DEFAULT_TIMEOUT),
        }
        _client = Groq(**kwargs)
    return _client


def _model() -> str:
    return os.environ.get("GROQ_MODEL") or _DEFAULT_MODEL


def _chat_completion(
    messages: list[dict],
    *,
    json_mode: bool,
    temperature: float,
    max_tokens: int,
) -> str:
    """Single SDK call. Maps SDK exceptions onto GroqError."""
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
        raise GroqError(f"Groq auth failed: {e}") from e
    except RateLimitError as e:
        raise GroqError(f"Groq rate-limited after retries: {e}") from e
    except APIConnectionError as e:
        raise GroqError(f"Groq unreachable after retries: {e}") from e
    except APIStatusError as e:
        raise GroqError(f"Groq HTTP {e.status_code}: {e}") from e
    except APIError as e:
        raise GroqError(f"Groq error: {e}") from e

    try:
        return completion.choices[0].message.content or ""
    except (AttributeError, IndexError) as e:
        raise GroqError(f"Groq returned malformed completion: {e}") from e


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

_TRANSLATION_SYSTEM = (
    "You are translating an Italian dog shelter adoption listing into English.\n"
    "\n"
    "Rules:\n"
    "- Translate the full text naturally, preserving the warm and hopeful tone "
    "typical of adoption listings.\n"
    "- Keep the meaning accurate but use natural English phrasing, not "
    "word-for-word translation.\n"
    "- Shelter-specific terms: \"canile\" = shelter, \"box\" = kennel, "
    "\"adottabile\" = available for adoption, \"staffetta\" = transport relay.\n"
    "- Preserve any names, dates, locations, and identification numbers exactly "
    "as written.\n"
    "- Return ONLY the English translation, nothing else.\n"
    "- Do NOT add notes, comments, explanations, or repeat the translation.\n"
    "- Do NOT prefix with \"Translation:\" or similar headers."
)


def groq_translate_description(text: str) -> str:
    """Translate an Italian description to English in a single Groq call.

    `max_tokens` is input-scaled (`max(50, len(text)//3)`) — same heuristic as
    the Mistral path — to defend against the fill-the-runway hallucination
    pattern (paraphrased duplicates / meta-commentary). Llama 3.3's 128k
    context easily holds any shelter description, so no chunking.
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
        f"Groq translation: {len(stripped)}→{len(out)} chars in {elapsed:.1f}s "
        f"(max_tokens={max_tokens})"
    )
    return out


# ---------------------------------------------------------------------------
# Filter extraction
# ---------------------------------------------------------------------------

_VALID_KEYS = {
    "size", "gender", "fur", "weight", "age", "breed", "good_with", "bad_with",
}


def groq_extract_filters(query: str, system_prompt: str) -> tuple[dict, str]:
    """Extract filters via Groq with JSON mode on.

    The caller (api.py) builds `system_prompt` from the live enums cache so
    `good_with`/`bad_with` valid values reflect what's actually in the DB.
    Returns `(filters_dict, raw_output)` to match the Mistral signature.
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
    logger.info(f"Groq extraction raw output: {raw!r}")

    parsed = _try_parse_json(raw)
    if parsed is None:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = _try_parse_json(match.group())

    if parsed is None:
        logger.warning(f"Groq returned non-JSON despite json_mode=True: {raw!r}")
        return {}, raw

    return parsed, raw


def _try_parse_json(text: str) -> dict | None:
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

_EXTRACT_FIELD_RULES = (
    "You extract a single field from an English dog adoption listing description.\n"
    "\n"
    "Rules:\n"
    "- Output JSON only: {\"value\": <value>}.\n"
    "- If the description does NOT clearly mention the field, output {\"value\": null}.\n"
    "- Do NOT guess. Do NOT infer from indirect cues unless the description is "
    "explicit.\n"
    "- For enum fields: output MUST be one of the allowed values verbatim. "
    "If the meaning matches none of them, output null.\n"
    "- For list fields: output a JSON array of allowed values; empty array if "
    "none mentioned.\n"
    "- For free-text fields: output a short concise string verbatim from the "
    "description, or null."
)


def groq_extract_field(
    description_en: str,
    field_name: str,
    *,
    value_type: str,
    allowed_values: list[str] | None = None,
    field_description: str = "",
) -> str | list[str] | None:
    """Extract one field from an English description via Groq.

    `value_type` is one of:
      - "enum"   → returns a string from `allowed_values`, or None.
      - "list"   → returns a list[str] subset of `allowed_values` (possibly empty).
      - "string" → returns a free-form short string, or None.

    Returns None when the description does not carry the field. The caller
    is responsible for any further validation (e.g. breed FK lookup).
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
        max_tokens=200,
    ).strip()

    parsed = _try_parse_extract_json(raw)
    if parsed is None:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = _try_parse_extract_json(match.group())
    if parsed is None:
        logger.warning(f"Groq extraction returned non-JSON for {field_name}: {raw!r}")
        return None

    value = parsed.get("value")
    return _coerce_extracted_value(field_name, value, value_type, allowed_values)


# ---------------------------------------------------------------------------
# Combined good_with + bad_with extraction (Stage 2)
# ---------------------------------------------------------------------------
#
# `good_with` and `bad_with` are extracted in a single call so the model sees
# both lists at once and can place each topic in exactly one bucket — a
# constraint that's impossible to honor across two independent calls.

_GOOD_BAD_WITH_RULES = (
    "You extract two compatibility lists from an English dog adoption "
    "listing description.\n"
    "\n"
    "good_with = things/beings the dog gets along with or is suitable for.\n"
    "bad_with  = things/beings the dog does NOT get along with or is "
    "NOT suitable for.\n"
    "\n"
    "Rules:\n"
    "- Output JSON only: {\"good_with\": [...], \"bad_with\": [...]}.\n"
    "- Each list contains short lowercase tags like 'children', 'cats', "
    "'other dogs', 'female dogs', 'male dogs', 'elderly', 'people', "
    "'first-time owners', 'apartments without garden', 'small spaces', "
    "'being left alone', 'hunting'.\n"
    "- Read BOTH explicit compatibility fields and natural-language phrases:\n"
    "  * 'Compatibility with Dogs: Good with females' -> good_with: 'female dogs'\n"
    "  * 'Cat Compatibility: Yes' -> good_with: 'cats'\n"
    "  * 'Cat Compatibility: No' -> bad_with: 'cats'\n"
    "  * 'Compatibility with Cats: To be evaluated' -> bad_with: 'cats' "
    "(treat 'to be evaluated' as a precaution, not a positive)\n"
    "  * 'Need for Outdoor Space: Yes' -> bad_with: 'apartments without garden'\n"
    "  * 'He gets along with X' -> good_with: 'X'\n"
    "  * 'NOT SUITABLE FOR HUNTING' -> bad_with: 'hunting'\n"
    "  * 'should not be left alone in a yard 24/7' -> bad_with: "
    "'being left alone'\n"
    "  * 'Being with people makes me happy' -> good_with: 'people'\n"
    "- A topic appears in EXACTLY ONE list. Never put the same tag in both.\n"
    "- If a topic is positive, do NOT also list it as negative (and vice versa).\n"
    "- Empty array if no signal for that side. Use lowercase tags."
)


def groq_extract_good_bad_with(description_en: str) -> tuple[list[str], list[str]]:
    """Extract good_with + bad_with as a single Groq call.

    Returns (good_with, bad_with). Both lists may be empty. Returns
    ([], []) when the description is empty or the model returns
    unparseable JSON.
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

    parsed = _try_parse_extract_json(raw)
    if parsed is None:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = _try_parse_extract_json(match.group())
    if parsed is None:
        logger.warning(f"Groq returned non-JSON for good/bad_with: {raw!r}")
        return [], []

    good = _coerce_string_list(parsed.get("good_with"))
    bad = _coerce_string_list(parsed.get("bad_with"))
    # Defensive dedup: if the model violated the exclusivity rule anyway,
    # keep good_with and drop the duplicate from bad_with.
    if good and bad:
        good_lower = {g.lower() for g in good}
        bad = [b for b in bad if b.lower() not in good_lower]
    return good, bad


def _coerce_string_list(value) -> list[str]:
    """Coerce a JSON value into a list[str], dropping non-strings/empties."""
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]


def _try_parse_extract_json(text: str) -> dict | None:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _coerce_extracted_value(
    field_name: str,
    value,
    value_type: str,
    allowed_values: list[str] | None,
) -> str | list[str] | None:
    """Validate the extracted value; return None on any mismatch."""
    if value is None:
        return None

    if value_type == "enum":
        if not isinstance(value, str):
            logger.warning(f"Extraction for {field_name}: expected str, got {type(value).__name__}")
            return None
        v = value.strip()
        if not v:
            return None
        if allowed_values and v not in allowed_values:
            logger.warning(
                f"Extraction for {field_name}: '{v}' not in allowed values; dropping"
            )
            return None
        return v

    if value_type == "list":
        if not isinstance(value, list):
            logger.warning(f"Extraction for {field_name}: expected list, got {type(value).__name__}")
            return None
        cleaned = [str(v).strip() for v in value if str(v).strip()]
        if allowed_values:
            cleaned = [v for v in cleaned if v in allowed_values]
        return cleaned  # may be empty

    # value_type == "string"
    if not isinstance(value, str):
        logger.warning(f"Extraction for {field_name}: expected str, got {type(value).__name__}")
        return None
    v = value.strip()
    return v or None


# ---------------------------------------------------------------------------
# Liveness probe (for /api/health)
# ---------------------------------------------------------------------------


def is_responsive(timeout: float = 5.0) -> bool:
    """Cheap probe — list available models with the configured key.

    The api.py health handler caches the result for 30 s to avoid hammering
    Groq on every health-check poll.
    """
    try:
        client = _get_client()
    except GroqError:
        return False
    try:
        client.with_options(timeout=timeout, max_retries=0).models.list()
    except (AuthenticationError, APIError, APIConnectionError) as e:
        logger.warning(f"Groq is_responsive probe failed: {e}")
        return False
    except Exception as e:  # noqa: BLE001 — defensive net for any SDK-internal error
        logger.warning(f"Groq is_responsive probe unexpected error: {e}")
        return False
    return True
