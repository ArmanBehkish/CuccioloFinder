"""Backend selection for the LLM workloads (translation + search extraction + per-field extraction).

Three independent toggles select between the local Mistral 7B
(`llama-cpp-python`, in-process inside the API container), Groq's hosted
Llama 3.3 70B (free tier), and OpenRouter's hosted Llama 3.3 70B (paid):

    TRANSLATION_BACKEND = mistral | groq | openrouter   (default: mistral)
    SEARCH_BACKEND      = mistral | groq | openrouter   (default: mistral)
    EXTRACT_BACKEND     = mistral | groq | openrouter   (default: mistral)

When *any* backend is `groq`, `GROQ_API_KEY` must be set; when any is
`openrouter`, `OPENROUTER_API_KEY` must be set.

`REMOTE_FALLBACK_TO_MISTRAL` (default `1`) governs the opportunistic
fallback to Mistral when EITHER remote backend (Groq or OpenRouter)
fails AND Mistral is loaded for some other workload. The legacy name
`GROQ_FALLBACK_TO_MISTRAL` is still read as a backwards-compat alias
(emits a deprecation warning if it's the only one set).
"""

import os
import sys

from loguru import logger

VALID_BACKENDS = {"mistral", "groq", "openrouter"}
REMOTE_BACKENDS = {"groq", "openrouter"}
_DEFAULT_BACKEND = "mistral"


def get_translation_backend() -> str:
    return (os.environ.get("TRANSLATION_BACKEND") or _DEFAULT_BACKEND).strip().lower()


def get_search_backend() -> str:
    return (os.environ.get("SEARCH_BACKEND") or _DEFAULT_BACKEND).strip().lower()


def get_extract_backend() -> str:
    """Backend for Stage-2 description-extraction calls."""
    return (os.environ.get("EXTRACT_BACKEND") or _DEFAULT_BACKEND).strip().lower()


def _read_fallback_raw() -> tuple[str, str | None]:
    """Return the raw fallback value and the env-var name it came from.

    Prefers the new `REMOTE_FALLBACK_TO_MISTRAL`. Falls back to the legacy
    `GROQ_FALLBACK_TO_MISTRAL` name for one release. Returns ("", None)
    when nothing is set (caller treats that as the default-on case).
    """
    new_raw = (os.environ.get("REMOTE_FALLBACK_TO_MISTRAL") or "").strip()
    if new_raw != "":
        return new_raw, "REMOTE_FALLBACK_TO_MISTRAL"
    legacy_raw = (os.environ.get("GROQ_FALLBACK_TO_MISTRAL") or "").strip()
    if legacy_raw != "":
        return legacy_raw, "GROQ_FALLBACK_TO_MISTRAL"
    return "", None


def get_fallback_enabled() -> bool:
    raw, _ = _read_fallback_raw()
    if raw == "":
        return True  # default-on
    return raw == "1"


def any_backend_uses_groq() -> bool:
    return (
        get_translation_backend() == "groq"
        or get_search_backend() == "groq"
        or get_extract_backend() == "groq"
    )


def any_backend_uses_openrouter() -> bool:
    return (
        get_translation_backend() == "openrouter"
        or get_search_backend() == "openrouter"
        or get_extract_backend() == "openrouter"
    )


def any_backend_uses_remote() -> bool:
    return any_backend_uses_groq() or any_backend_uses_openrouter()


def any_backend_uses_mistral() -> bool:
    return (
        get_translation_backend() == "mistral"
        or get_search_backend() == "mistral"
        or get_extract_backend() == "mistral"
    )


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
    extract = get_extract_backend()

    for var, value in (
        ("TRANSLATION_BACKEND", translation),
        ("SEARCH_BACKEND", search),
        ("EXTRACT_BACKEND", extract),
    ):
        if value not in VALID_BACKENDS:
            errors.append(
                f"{var}={value!r} invalid — must be one of {sorted(VALID_BACKENDS)}"
            )

    fallback_raw, fallback_source = _read_fallback_raw()
    if fallback_raw not in ("", "0", "1"):
        var_name = fallback_source or "REMOTE_FALLBACK_TO_MISTRAL"
        errors.append(
            f"{var_name}={fallback_raw!r} invalid — must be '0' or '1' (or unset)"
        )

    uses_groq = any_backend_uses_groq()
    uses_openrouter = any_backend_uses_openrouter()
    uses_remote = uses_groq or uses_openrouter
    uses_mistral = any_backend_uses_mistral()

    if uses_groq and not (os.environ.get("GROQ_API_KEY") or "").strip():
        errors.append(
            "GROQ_API_KEY is empty but at least one backend is set to 'groq'"
        )
    if uses_openrouter and not (os.environ.get("OPENROUTER_API_KEY") or "").strip():
        errors.append(
            "OPENROUTER_API_KEY is empty but at least one backend is set to 'openrouter'"
        )

    fallback_set = fallback_raw != ""
    fallback_enabled = fallback_raw == "1"

    if fallback_enabled and not uses_mistral:
        warnings.append(
            "REMOTE_FALLBACK_TO_MISTRAL=1 has no effect: no backend uses Mistral, "
            "so there is no fallback target."
        )
    if fallback_set and not uses_remote:
        warnings.append(
            "REMOTE_FALLBACK_TO_MISTRAL is irrelevant: no backend uses Groq or OpenRouter."
        )
    if fallback_source == "GROQ_FALLBACK_TO_MISTRAL":
        warnings.append(
            "GROQ_FALLBACK_TO_MISTRAL is deprecated — rename to REMOTE_FALLBACK_TO_MISTRAL "
            "(same semantics, also covers OpenRouter)."
        )
    if (os.environ.get("GROQ_API_KEY") or "").strip() and not uses_groq:
        logger.info("GROQ_API_KEY is set but no backend uses Groq — key is dormant.")
    if (os.environ.get("OPENROUTER_API_KEY") or "").strip() and not uses_openrouter:
        logger.info("OPENROUTER_API_KEY is set but no backend uses OpenRouter — key is dormant.")

    for w in warnings:
        logger.warning(w)

    if errors:
        for e in errors:
            logger.error(f"Backend config error: {e}")
        if exit_on_error:
            sys.exit(1)
        raise BackendConfigError("; ".join(errors))

    fallback_display = fallback_raw or "1 (default)"
    logger.info(
        f"Backend config OK: TRANSLATION_BACKEND={translation}, "
        f"SEARCH_BACKEND={search}, EXTRACT_BACKEND={extract}, "
        f"REMOTE_FALLBACK_TO_MISTRAL={fallback_display}"
    )
