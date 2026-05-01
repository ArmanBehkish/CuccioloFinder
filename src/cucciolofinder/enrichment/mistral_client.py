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

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                f"{api_url}/api/extract/field",
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            value = resp.json().get("value")
            return _coerce_extracted_value(field_name, value, value_type, allowed_values)
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
