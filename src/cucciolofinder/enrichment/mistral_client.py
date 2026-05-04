"""Worker-side Mistral wrappers.

Mistral runs inside the API container (llama-cpp loads a GGUF). The
worker has no direct access to it, so each call is a short-lived HTTP
hop to the API. Mirrors the role `groq_client.py` plays for the Groq
backend: a thin client used by `enrichment/extract.py` and friends.

Translation already routes through `enrichment/translator.py`'s chunked
flow against `POST /api/translate/description`. This module covers the
per-field extraction path (`POST /api/extract/field`) that Stage 2 uses
when `EXTRACT_BACKEND=mistral`.
"""

import os

import requests
from loguru import logger

from .groq_client import _coerce_extracted_value


class MistralError(RuntimeError):
    """Raised when the Mistral extraction endpoint fails."""


def mistral_extract_field(
    description_en: str,
    field_name: str,
    *,
    value_type: str,
    allowed_values: list[str] | None = None,
    field_description: str = "",
    max_retries: int = 3,
    timeout: float = 120.0,
) -> str | list[str] | None:
    """Extract one field from an English description via the API's Mistral endpoint.

    Parallels `groq_extract_field`: same signature, same return contract.
    The actual prompt + JSON parsing happens on the API side; here we
    POST, retry on transport errors, and reuse Groq's coercion to
    validate the response against `allowed_values`.
    """
    if not description_en or not description_en.strip():
        return None
    if value_type not in ("enum", "list", "string"):
        raise ValueError(f"unknown value_type: {value_type}")
    if value_type == "enum" and not allowed_values:
        raise ValueError("enum requires allowed_values")

    api_url = os.environ.get("API_URL", "http://api:8000")
    payload = {
        "description": description_en.strip(),
        "field_name": field_name,
        "value_type": value_type,
        "allowed_values": allowed_values,
        "field_description": field_description,
    }

    # Log the request so the worker side has a trace too — the actual
    # llama-cpp inference logs land in the API container, which makes
    # debugging awkward when only the worker logs are available.
    desc_preview = payload["description"][:120].replace("\n", " ")
    logger.info(
        f"Mistral extract {field_name} ({value_type}) → POST {api_url}/api/extract/field"
        f" | desc={desc_preview!r}"
        + (f" | allowed={allowed_values}" if allowed_values else "")
    )

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            import time as _time
            t0 = _time.time()
            resp = requests.post(
                f"{api_url}/api/extract/field",
                json=payload,
                timeout=timeout,
            )
            elapsed = _time.time() - t0
            resp.raise_for_status()
            body = resp.json()
            raw_output = body.get("raw_output", "")
            value = body.get("value")
            coerced = _coerce_extracted_value(field_name, value, value_type, allowed_values)
            logger.info(
                f"Mistral extract {field_name} ← HTTP {resp.status_code} in {elapsed:.1f}s"
                f" | raw={raw_output!r} | parsed={value!r} | coerced={coerced!r}"
            )
            return coerced
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            logger.warning(
                f"Mistral extract {field_name} failed (attempt {attempt}/{max_retries}): {exc}"
            )
            if attempt < max_retries:
                import time

                wait = (15, 30, 60)[attempt - 1]
                time.sleep(wait)

    raise MistralError(f"Mistral extraction for {field_name} failed after {max_retries} attempts: {last_exc}")


def mistral_extract_good_bad_with(
    description_en: str,
    *,
    max_retries: int = 3,
    timeout: float = 180.0,
) -> tuple[list[str], list[str]]:
    """Combined good_with + bad_with extraction via the API's Mistral endpoint.

    Mirrors `groq_extract_good_bad_with`: returns (good, bad), both lists.
    The actual prompt + JSON parsing + dedup happens on the API side.
    """
    if not description_en or not description_en.strip():
        return [], []

    api_url = os.environ.get("API_URL", "http://api:8000")
    payload = {"description": description_en.strip()}

    desc_preview = payload["description"][:120].replace("\n", " ")
    logger.info(
        f"Mistral good/bad_with -> POST {api_url}/api/extract/good-bad-with"
        f" | desc={desc_preview!r}"
    )

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            import time as _time
            t0 = _time.time()
            resp = requests.post(
                f"{api_url}/api/extract/good-bad-with",
                json=payload,
                timeout=timeout,
            )
            elapsed = _time.time() - t0
            resp.raise_for_status()
            body = resp.json()
            good = body.get("good_with") or []
            bad = body.get("bad_with") or []
            raw_output = body.get("raw_output", "")
            logger.info(
                f"Mistral good/bad_with <- HTTP {resp.status_code} in {elapsed:.1f}s"
                f" | raw={raw_output!r} | good={good!r} | bad={bad!r}"
            )
            return list(good), list(bad)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            logger.warning(
                f"Mistral good/bad_with failed (attempt {attempt}/{max_retries}): {exc}"
            )
            if attempt < max_retries:
                import time

                wait = (15, 30, 60)[attempt - 1]
                time.sleep(wait)

    raise MistralError(f"Mistral good/bad_with failed after {max_retries} attempts: {last_exc}")
