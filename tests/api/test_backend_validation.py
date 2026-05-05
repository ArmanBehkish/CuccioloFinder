"""Unit tests for backend env var validation.

Covers valid combinations across mistral / groq / openrouter, plus
invalid-value typo guards and missing-key errors.
"""

import pytest
from loguru import logger

from cucciolofinder.enrichment.backends import (
    BackendConfigError,
    get_fallback_enabled,
    get_search_backend,
    get_translation_backend,
    validate_backend_config,
)


@pytest.fixture
def loguru_records():
    """Capture loguru records for the duration of one test."""
    records: list = []
    sink_id = logger.add(lambda msg: records.append(msg.record), level="DEBUG")
    yield records
    logger.remove(sink_id)


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every backend-related var so each test starts from a known state."""
    for k in (
        "TRANSLATION_BACKEND",
        "SEARCH_BACKEND",
        "EXTRACT_BACKEND",
        "REMOTE_FALLBACK_TO_MISTRAL",
        "GROQ_FALLBACK_TO_MISTRAL",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _set(
    monkeypatch,
    translation,
    search,
    fallback,
    *,
    extract=None,
    groq_api_key="test-key",
    openrouter_api_key="test-key",
):
    """Apply a backend config to env."""
    if translation is not None:
        monkeypatch.setenv("TRANSLATION_BACKEND", translation)
    if search is not None:
        monkeypatch.setenv("SEARCH_BACKEND", search)
    if extract is not None:
        monkeypatch.setenv("EXTRACT_BACKEND", extract)
    if fallback is not None:
        monkeypatch.setenv("REMOTE_FALLBACK_TO_MISTRAL", fallback)
    if groq_api_key is not None:
        monkeypatch.setenv("GROQ_API_KEY", groq_api_key)
    if openrouter_api_key is not None:
        monkeypatch.setenv("OPENROUTER_API_KEY", openrouter_api_key)


# Defaults --------------------------------------------------------------


def test_defaults_are_mistral(clean_env):
    assert get_translation_backend() == "mistral"
    assert get_search_backend() == "mistral"
    assert get_fallback_enabled() is True


def test_fallback_zero_disables(clean_env):
    clean_env.setenv("REMOTE_FALLBACK_TO_MISTRAL", "0")
    assert get_fallback_enabled() is False


def test_legacy_fallback_flag_is_honored(clean_env):
    """Backwards-compat: GROQ_FALLBACK_TO_MISTRAL still works as an alias."""
    clean_env.setenv("GROQ_FALLBACK_TO_MISTRAL", "0")
    assert get_fallback_enabled() is False


def test_new_fallback_flag_wins_over_legacy(clean_env):
    """When both are set, the new name takes precedence."""
    clean_env.setenv("GROQ_FALLBACK_TO_MISTRAL", "0")
    clean_env.setenv("REMOTE_FALLBACK_TO_MISTRAL", "1")
    assert get_fallback_enabled() is True


# Combinations table ----------------------------------------------------


@pytest.mark.parametrize(
    "translation,search,fallback",
    [
        ("mistral", "mistral", "0"),
        ("mistral", "mistral", "1"),
        ("mistral", "groq", "0"),
        ("mistral", "groq", "1"),
        ("groq", "mistral", "0"),
        ("groq", "mistral", "1"),
        ("groq", "groq", "0"),
        ("groq", "groq", "1"),
        ("openrouter", "mistral", "0"),
        ("openrouter", "openrouter", "0"),
        ("groq", "openrouter", "1"),
        ("openrouter", "groq", "1"),
    ],
)
def test_valid_combinations_do_not_raise(clean_env, translation, search, fallback):
    _set(clean_env, translation, search, fallback)
    validate_backend_config(exit_on_error=False)


def test_extract_backend_openrouter_valid(clean_env):
    _set(clean_env, "groq", "openrouter", "1", extract="openrouter")
    validate_backend_config(exit_on_error=False)


# Hard-error cases ------------------------------------------------------


def test_invalid_translation_backend_raises(clean_env):
    _set(clean_env, "foobar", "mistral", "1")
    with pytest.raises(BackendConfigError, match="TRANSLATION_BACKEND"):
        validate_backend_config(exit_on_error=False)


def test_invalid_search_backend_raises(clean_env):
    _set(clean_env, "mistral", "qux", "1")
    with pytest.raises(BackendConfigError, match="SEARCH_BACKEND"):
        validate_backend_config(exit_on_error=False)


def test_invalid_extract_backend_raises(clean_env):
    _set(clean_env, "mistral", "mistral", "1", extract="bogus")
    with pytest.raises(BackendConfigError, match="EXTRACT_BACKEND"):
        validate_backend_config(exit_on_error=False)


def test_invalid_fallback_value_raises(clean_env):
    _set(clean_env, "mistral", "mistral", "2")
    with pytest.raises(BackendConfigError, match="REMOTE_FALLBACK_TO_MISTRAL"):
        validate_backend_config(exit_on_error=False)


def test_groq_backend_without_api_key_raises(clean_env):
    clean_env.setenv("TRANSLATION_BACKEND", "groq")
    clean_env.setenv("SEARCH_BACKEND", "mistral")
    # No GROQ_API_KEY set
    with pytest.raises(BackendConfigError, match="GROQ_API_KEY"):
        validate_backend_config(exit_on_error=False)


def test_search_groq_without_api_key_raises(clean_env):
    clean_env.setenv("SEARCH_BACKEND", "groq")
    with pytest.raises(BackendConfigError, match="GROQ_API_KEY"):
        validate_backend_config(exit_on_error=False)


def test_openrouter_backend_without_api_key_raises(clean_env):
    clean_env.setenv("SEARCH_BACKEND", "openrouter")
    # No OPENROUTER_API_KEY set
    with pytest.raises(BackendConfigError, match="OPENROUTER_API_KEY"):
        validate_backend_config(exit_on_error=False)


def test_extract_openrouter_without_api_key_raises(clean_env):
    clean_env.setenv("EXTRACT_BACKEND", "openrouter")
    with pytest.raises(BackendConfigError, match="OPENROUTER_API_KEY"):
        validate_backend_config(exit_on_error=False)


# Warning-only cases ----------------------------------------------------


def test_warns_when_fallback_set_but_no_mistral(clean_env, loguru_records):
    """All workloads remote + fallback=1 — no Mistral target, warn."""
    _set(clean_env, "groq", "groq", "1", extract="groq")
    validate_backend_config(exit_on_error=False)
    assert any(
        r["level"].name == "WARNING" and "no backend uses Mistral" in r["message"]
        for r in loguru_records
    )


def test_warns_when_fallback_set_but_no_remote(clean_env, loguru_records):
    """Fallback flag set but no remote backend — flag has nothing to govern."""
    _set(clean_env, "mistral", "mistral", "1")
    validate_backend_config(exit_on_error=False)
    assert any(
        r["level"].name == "WARNING"
        and "no backend uses Groq or OpenRouter" in r["message"]
        for r in loguru_records
    )


def test_legacy_fallback_flag_emits_deprecation_warning(clean_env, loguru_records):
    """Setting only the legacy flag should still work but log deprecation."""
    clean_env.setenv("TRANSLATION_BACKEND", "groq")
    clean_env.setenv("GROQ_API_KEY", "test-key")
    clean_env.setenv("GROQ_FALLBACK_TO_MISTRAL", "1")
    validate_backend_config(exit_on_error=False)
    assert any(
        r["level"].name == "WARNING" and "deprecated" in r["message"]
        for r in loguru_records
    )


def test_dormant_api_key_is_info_only(clean_env, loguru_records):
    """Key set but no remote backend — info-level only, no warning, no error."""
    _set(
        clean_env,
        "mistral",
        "mistral",
        None,
        groq_api_key="dormant-groq",
        openrouter_api_key="dormant-or",
    )
    validate_backend_config(exit_on_error=False)
    warn_msgs = [
        r["message"] for r in loguru_records if r["level"].name == "WARNING"
    ]
    assert not any("GROQ_API_KEY" in m for m in warn_msgs)
    assert not any("OPENROUTER_API_KEY" in m for m in warn_msgs)
