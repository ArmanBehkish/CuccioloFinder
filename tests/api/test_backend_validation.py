"""Unit tests for backend env var validation.

Covers the 8-row combinations table plus invalid-value typo guards.
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
        "GROQ_FALLBACK_TO_MISTRAL",
        "GROQ_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _set(monkeypatch, translation, search, fallback, api_key="test-key"):
    """Apply a backend config to env."""
    if translation is not None:
        monkeypatch.setenv("TRANSLATION_BACKEND", translation)
    if search is not None:
        monkeypatch.setenv("SEARCH_BACKEND", search)
    if fallback is not None:
        monkeypatch.setenv("GROQ_FALLBACK_TO_MISTRAL", fallback)
    if api_key is not None:
        monkeypatch.setenv("GROQ_API_KEY", api_key)


# Defaults --------------------------------------------------------------


def test_defaults_are_mistral(clean_env):
    assert get_translation_backend() == "mistral"
    assert get_search_backend() == "mistral"
    assert get_fallback_enabled() is True


def test_fallback_zero_disables(clean_env):
    clean_env.setenv("GROQ_FALLBACK_TO_MISTRAL", "0")
    assert get_fallback_enabled() is False


# 8-row combinations table ----------------------------------------------


@pytest.mark.parametrize(
    "translation,search,fallback",
    [
        ("mistral", "mistral", "0"),  # row 1
        ("mistral", "mistral", "1"),  # row 2
        ("mistral", "groq", "0"),     # row 3
        ("mistral", "groq", "1"),     # row 4
        ("groq", "mistral", "0"),     # row 5
        ("groq", "mistral", "1"),     # row 6
        ("groq", "groq", "0"),        # row 7
        ("groq", "groq", "1"),        # row 8
    ],
)
def test_valid_combinations_do_not_raise(clean_env, translation, search, fallback):
    _set(clean_env, translation, search, fallback)
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


def test_invalid_fallback_value_raises(clean_env):
    _set(clean_env, "mistral", "mistral", "2")
    with pytest.raises(BackendConfigError, match="GROQ_FALLBACK_TO_MISTRAL"):
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


# Warning-only cases ----------------------------------------------------


def test_warns_when_fallback_set_but_no_mistral(clean_env, loguru_records):
    """Row #8: both groq + fallback=1 — no Mistral target, warn."""
    _set(clean_env, "groq", "groq", "1")
    validate_backend_config(exit_on_error=False)
    assert any(
        r["level"].name == "WARNING" and "no backend uses Mistral" in r["message"]
        for r in loguru_records
    )


def test_warns_when_fallback_set_but_no_groq(clean_env, loguru_records):
    """Rows #1, #2: fallback flag set but no groq backend."""
    _set(clean_env, "mistral", "mistral", "1")
    validate_backend_config(exit_on_error=False)
    assert any(
        r["level"].name == "WARNING" and "no backend uses Groq" in r["message"]
        for r in loguru_records
    )


def test_dormant_api_key_is_info_only(clean_env, loguru_records):
    """Key set but no groq backend — info-level only, no warning, no error."""
    _set(clean_env, "mistral", "mistral", None, api_key="dormant-key")
    validate_backend_config(exit_on_error=False)
    warn_msgs = [
        r["message"] for r in loguru_records if r["level"].name == "WARNING"
    ]
    assert not any("GROQ_API_KEY" in m for m in warn_msgs)
