"""Backend selection for the LLM workloads (translation + search extraction).

Two independent toggles chose between the local Mistral 7B (`llama-cpp-python`,
in-process inside the API container) and Groq's hosted Llama 3.3 70B:

    TRANSLATION_BACKEND = mistral | groq   (default: mistral)
    SEARCH_BACKEND      = mistral | groq   (default: mistral)

When *any* backend is `groq`, `GROQ_API_KEY` must be set. A third flag,
`GROQ_FALLBACK_TO_MISTRAL` (default `1`), falls back to
Mistral when Groq fails and Mistral is already loaded for the other
workload. See docs for the full decision table.
"""

import os
import sys

from loguru import logger

VALID_BACKENDS = {"mistral", "groq"}
_DEFAULT_BACKEND = "mistral"


def get_translation_backend() -> str:
    return (os.environ.get("TRANSLATION_BACKEND") or _DEFAULT_BACKEND).strip().lower()


def get_search_backend() -> str:
    return (os.environ.get("SEARCH_BACKEND") or _DEFAULT_BACKEND).strip().lower()


def get_extract_backend() -> str:
    """Backend for Stage-2 description-extraction calls."""
    return (os.environ.get("EXTRACT_BACKEND") or _DEFAULT_BACKEND).strip().lower()


def get_fallback_enabled() -> bool:
    raw = (os.environ.get("GROQ_FALLBACK_TO_MISTRAL") or "1").strip()
    return raw == "1"


def any_backend_uses_groq() -> bool:
    return get_translation_backend() == "groq" or get_search_backend() == "groq"


def any_backend_uses_mistral() -> bool:
    return get_translation_backend() == "mistral" or get_search_backend() == "mistral"


class BackendConfigError(RuntimeError):
    """Raised on unrecoverable misconfiguration of the backend env vars."""


def validate_backend_config(*, exit_on_error: bool = True) -> None:
    """Check env-var combinations; warn on confusing combos, exit on broken ones.

    Called once at startup from both the worker (`main.py`) and the API
    (`lifespan()`). When `exit_on_error=True` (worker default), hard-exits the
    process with code 1 on a fatal error. When False (API default), raises
    BackendConfigError so the caller can surface it appropriately.
    """
    errors: list[str] = []
    warnings: list[str] = []

    translation = get_translation_backend()
    search = get_search_backend()

    if translation not in VALID_BACKENDS:
        errors.append(
            f"TRANSLATION_BACKEND={translation!r} invalid — must be one of {sorted(VALID_BACKENDS)}"
        )
    if search not in VALID_BACKENDS:
        errors.append(
            f"SEARCH_BACKEND={search!r} invalid — must be one of {sorted(VALID_BACKENDS)}"
        )

    fallback_raw = (os.environ.get("GROQ_FALLBACK_TO_MISTRAL") or "").strip()
    if fallback_raw not in ("", "0", "1"):
        errors.append(
            f"GROQ_FALLBACK_TO_MISTRAL={fallback_raw!r} invalid — must be '0' or '1' (or unset)"
        )

    uses_groq = translation == "groq" or search == "groq"
    uses_mistral = translation == "mistral" or search == "mistral"

    if uses_groq and not (os.environ.get("GROQ_API_KEY") or "").strip():
        errors.append(
            "GROQ_API_KEY is empty but at least one backend is set to 'groq'"
        )

    fallback_set = fallback_raw != ""
    fallback_enabled = fallback_raw == "1"

    if fallback_enabled and not uses_mistral:
        warnings.append(
            "GROQ_FALLBACK_TO_MISTRAL=1 has no effect: no backend uses Mistral, "
            "so there is no fallback target."
        )
    if fallback_set and not uses_groq:
        warnings.append(
            "GROQ_FALLBACK_TO_MISTRAL is irrelevant: no backend uses Groq."
        )
    if (os.environ.get("GROQ_API_KEY") or "").strip() and not uses_groq:
        logger.info("GROQ_API_KEY is set but no backend uses Groq — key is dormant.")

    for w in warnings:
        logger.warning(w)

    if errors:
        for e in errors:
            logger.error(f"Backend config error: {e}")
        if exit_on_error:
            sys.exit(1)
        raise BackendConfigError("; ".join(errors))

    logger.info(
        f"Backend config OK: TRANSLATION_BACKEND={translation}, "
        f"SEARCH_BACKEND={search}, GROQ_FALLBACK_TO_MISTRAL={fallback_raw or '1 (default)'}"
    )
