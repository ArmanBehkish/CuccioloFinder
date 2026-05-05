"""Tests for `enrich_from_desc` (Stage 2: description extraction)."""

from cucciolofinder.enrichment import extract as extract_module
from cucciolofinder.enrichment.extract import enrich_from_desc


def _stub_good_bad(monkeypatch, good=(), bad=()):
    """Default stub for the combined good/bad_with extractor.

    Tests that don't specifically exercise good/bad use this to keep the
    extractor offline. Returns plain tuples; tests can override per-call.
    """
    monkeypatch.setattr(
        extract_module,
        "groq_extract_good_bad_with",
        lambda _desc: (list(good), list(bad)),
    )
    monkeypatch.setattr(
        extract_module,
        "openrouter_extract_good_bad_with",
        lambda _desc: (list(good), list(bad)),
    )
    monkeypatch.setattr(
        extract_module,
        "mistral_extract_good_bad_with",
        lambda _desc: (list(good), list(bad)),
    )


def test_extract_populates_from_desc_columns(monkeypatch, session, make_dog):
    """Mocked LLM returns a value → that column gets populated."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")

    fake_returns = {
        "gender": "female",
        "age": "3 years",
        "weight": "20kg",
        "size": "medium",
        "breed": "Labrador mix",
        "fur": "short",
        "microchip": "yes",
        "sterilization": "yes",
        "vaccine": "yes",
        "deworming": "yes",
    }

    def fake_extract(description_en, *, field_name, **_):
        return fake_returns.get(field_name)

    monkeypatch.setattr(extract_module, "groq_extract_field", fake_extract)
    _stub_good_bad(monkeypatch, good=["children", "other dogs"], bad=["cats"])

    dog = make_dog(
        description_en="A friendly female labrador-mix dog who loves children.",
    )

    n = enrich_from_desc(session)
    assert n == 1

    session.refresh(dog)
    assert dog.gender_from_desc == "female"
    assert dog.size_from_desc == "medium"
    assert dog.breed_from_desc == "Labrador mix"
    assert dog.good_with_from_desc == ["children", "other dogs"]
    assert dog.bad_with_from_desc == ["cats"]
    # Translation column never touched.
    assert dog.gender_en is None


def test_extract_skips_already_populated_columns(monkeypatch, session, make_dog):
    """Columns that already have a value are not re-extracted."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")

    calls = []

    def fake_extract(description_en, *, field_name, **_):
        calls.append(field_name)
        return None

    monkeypatch.setattr(extract_module, "groq_extract_field", fake_extract)
    _stub_good_bad(monkeypatch)

    make_dog(
        description_en="something",
        gender_from_desc="male",  # pre-populated
    )

    enrich_from_desc(session)

    assert "gender" not in calls, "extractor should skip already-populated columns"
    assert "size" in calls and "breed" in calls
    # good_with / bad_with no longer go through the per-field path.
    assert "good_with" not in calls and "bad_with" not in calls


def test_extract_skips_dogs_without_description_en(monkeypatch, session, make_dog):
    """No description_en → dog skipped entirely; backend never called."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")

    called = []

    def fake_extract(*args, **kwargs):
        called.append(("field",))
        return "value"

    def fake_good_bad(*args, **kwargs):
        called.append(("good_bad",))
        return [], []

    monkeypatch.setattr(extract_module, "groq_extract_field", fake_extract)
    monkeypatch.setattr(extract_module, "groq_extract_good_bad_with", fake_good_bad)

    make_dog(description_en=None)
    make_dog(description_en="")

    n = enrich_from_desc(session)
    assert n == 0
    assert called == []


def test_extract_independent_of_en_columns(monkeypatch, session, make_dog):
    """Per `feedback_from_desc_independence`: extraction runs even when
    `<field>_en` is already populated. Both signals coexist."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")
    monkeypatch.setattr(
        extract_module,
        "groq_extract_field",
        lambda *_, field_name, **__: "female" if field_name == "gender" else None,
    )
    _stub_good_bad(monkeypatch)

    dog = make_dog(
        description_en="She is a wonderful dog.",
        gender="femmina",
        gender_en="female",  # already translated
    )

    enrich_from_desc(session)
    session.refresh(dog)
    assert dog.gender_en == "female"
    assert dog.gender_from_desc == "female"


def test_extract_null_response_leaves_column_null(monkeypatch, session, make_dog):
    """When the LLM returns None, the column stays NULL (no sentinel)."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")
    monkeypatch.setattr(
        extract_module, "groq_extract_field", lambda *_, **__: None
    )
    _stub_good_bad(monkeypatch)

    dog = make_dog(description_en="Some text without any signal.")
    n = enrich_from_desc(session)

    assert n == 0
    session.refresh(dog)
    assert dog.gender_from_desc is None
    assert dog.size_from_desc is None
    assert dog.breed_from_desc is None


def test_extract_empty_list_leaves_column_null(monkeypatch, session, make_dog):
    """Empty `good_with`/`bad_with` from the combined call leaves columns NULL."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")
    monkeypatch.setattr(
        extract_module, "groq_extract_field", lambda *_, **__: None
    )
    _stub_good_bad(monkeypatch, good=[], bad=[])

    dog = make_dog(description_en="No social signals here.")
    enrich_from_desc(session)

    session.refresh(dog)
    assert dog.good_with_from_desc is None
    assert dog.bad_with_from_desc is None


def test_extract_combined_good_bad_with_populates_both(monkeypatch, session, make_dog):
    """Combined extractor returns two non-empty lists → both columns written."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")
    monkeypatch.setattr(extract_module, "groq_extract_field", lambda *_, **__: None)
    _stub_good_bad(monkeypatch, good=["children", "female dogs"], bad=["cats"])

    dog = make_dog(description_en="Loves kids and lady dogs, hates cats.")
    enrich_from_desc(session)
    session.refresh(dog)

    assert dog.good_with_from_desc == ["children", "female dogs"]
    assert dog.bad_with_from_desc == ["cats"]


def test_extract_combined_call_skipped_when_both_already_populated(
    monkeypatch, session, make_dog
):
    """If both good_with_from_desc and bad_with_from_desc are pre-populated,
    the combined call is not made (the dog has no work for that side)."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")
    monkeypatch.setattr(extract_module, "groq_extract_field", lambda *_, **__: None)

    calls: list[str] = []

    def boom(_desc):
        calls.append("called")
        return [], []

    monkeypatch.setattr(extract_module, "groq_extract_good_bad_with", boom)

    make_dog(
        description_en="something",
        good_with_from_desc=["children"],
        bad_with_from_desc=["cats"],
    )
    enrich_from_desc(session)

    assert calls == [], "combined call should be skipped when both columns are populated"


def test_extract_mistral_backend_dispatches_to_mistral_client(
    monkeypatch, session, make_dog
):
    """When EXTRACT_BACKEND=mistral, dispatch goes through Mistral client functions."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "mistral")

    calls: list[str] = []

    def fake_mistral_field(description_en, *, field_name, **_):
        calls.append(field_name)
        return "female" if field_name == "gender" else None

    def fake_mistral_good_bad(_desc):
        calls.append("good_bad")
        return ["people"], []

    # Groq must NOT be called on the mistral path.
    def fail_groq(*args, **kwargs):
        raise AssertionError("groq_extract_field should not run on mistral path")

    def fail_groq_good_bad(*args, **kwargs):
        raise AssertionError("groq_extract_good_bad_with should not run on mistral path")

    monkeypatch.setattr(extract_module, "mistral_extract_field", fake_mistral_field)
    monkeypatch.setattr(
        extract_module, "mistral_extract_good_bad_with", fake_mistral_good_bad
    )
    monkeypatch.setattr(extract_module, "groq_extract_field", fail_groq)
    monkeypatch.setattr(extract_module, "groq_extract_good_bad_with", fail_groq_good_bad)

    dog = make_dog(description_en="A female dog.")
    enrich_from_desc(session)
    session.refresh(dog)

    assert dog.gender_from_desc == "female"
    assert "gender" in calls and "size" in calls and "good_bad" in calls
    assert dog.good_with_from_desc == ["people"]


def test_extract_groq_falls_back_to_mistral_on_failure(
    monkeypatch, session, make_dog
):
    """Groq raising + fallback enabled → Mistral is tried (loaded on demand by API).

    Covers BOTH the per-field Groq error and the combined good/bad_with Groq error.
    """
    from cucciolofinder.enrichment.groq_client import GroqError

    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")
    monkeypatch.setattr(extract_module, "get_fallback_enabled", lambda: True)

    def boom_groq_field(*args, **kwargs):
        raise GroqError("simulated outage")

    def boom_groq_good_bad(*_args, **_kwargs):
        raise GroqError("simulated outage")

    fallback_field_calls: list[str] = []
    fallback_good_bad_calls: list[bool] = []

    def fake_mistral_field(description_en, *, field_name, **_):
        fallback_field_calls.append(field_name)
        return "female" if field_name == "gender" else None

    def fake_mistral_good_bad(_desc):
        fallback_good_bad_calls.append(True)
        return ["children"], ["cats"]

    monkeypatch.setattr(extract_module, "groq_extract_field", boom_groq_field)
    monkeypatch.setattr(extract_module, "groq_extract_good_bad_with", boom_groq_good_bad)
    monkeypatch.setattr(extract_module, "mistral_extract_field", fake_mistral_field)
    monkeypatch.setattr(
        extract_module, "mistral_extract_good_bad_with", fake_mistral_good_bad
    )

    dog = make_dog(description_en="A female dog.")
    enrich_from_desc(session)
    session.refresh(dog)

    assert dog.gender_from_desc == "female"
    assert "gender" in fallback_field_calls
    assert fallback_good_bad_calls == [True]
    assert dog.good_with_from_desc == ["children"]
    assert dog.bad_with_from_desc == ["cats"]


def test_extract_openrouter_backend_dispatches_to_openrouter_client(
    monkeypatch, session, make_dog
):
    """When EXTRACT_BACKEND=openrouter, dispatch goes through OpenRouter client functions."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "openrouter")

    calls: list[str] = []

    def fake_or_field(description_en, *, field_name, **_):
        calls.append(field_name)
        return "female" if field_name == "gender" else None

    def fake_or_good_bad(_desc):
        calls.append("good_bad")
        return ["people"], []

    def fail_groq(*args, **kwargs):
        raise AssertionError("groq_extract_field should not run on openrouter path")

    def fail_groq_good_bad(*args, **kwargs):
        raise AssertionError(
            "groq_extract_good_bad_with should not run on openrouter path"
        )

    def fail_mistral(*args, **kwargs):
        raise AssertionError("mistral_extract_field should not run on openrouter path")

    def fail_mistral_good_bad(*args, **kwargs):
        raise AssertionError(
            "mistral_extract_good_bad_with should not run on openrouter path"
        )

    monkeypatch.setattr(extract_module, "openrouter_extract_field", fake_or_field)
    monkeypatch.setattr(
        extract_module, "openrouter_extract_good_bad_with", fake_or_good_bad
    )
    monkeypatch.setattr(extract_module, "groq_extract_field", fail_groq)
    monkeypatch.setattr(extract_module, "groq_extract_good_bad_with", fail_groq_good_bad)
    monkeypatch.setattr(extract_module, "mistral_extract_field", fail_mistral)
    monkeypatch.setattr(
        extract_module, "mistral_extract_good_bad_with", fail_mistral_good_bad
    )

    dog = make_dog(description_en="A female dog.")
    enrich_from_desc(session)
    session.refresh(dog)

    assert dog.gender_from_desc == "female"
    assert "gender" in calls and "size" in calls and "good_bad" in calls
    assert dog.good_with_from_desc == ["people"]


def test_extract_openrouter_falls_back_to_mistral_on_failure(
    monkeypatch, session, make_dog
):
    """OpenRouter raising + fallback enabled → Mistral is tried."""
    from cucciolofinder.enrichment.openrouter_client import OpenRouterError

    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "openrouter")
    monkeypatch.setattr(extract_module, "get_fallback_enabled", lambda: True)

    def boom_or_field(*args, **kwargs):
        raise OpenRouterError("simulated outage")

    def boom_or_good_bad(*_args, **_kwargs):
        raise OpenRouterError("simulated outage")

    fallback_field_calls: list[str] = []
    fallback_good_bad_calls: list[bool] = []

    def fake_mistral_field(description_en, *, field_name, **_):
        fallback_field_calls.append(field_name)
        return "female" if field_name == "gender" else None

    def fake_mistral_good_bad(_desc):
        fallback_good_bad_calls.append(True)
        return ["children"], ["cats"]

    monkeypatch.setattr(extract_module, "openrouter_extract_field", boom_or_field)
    monkeypatch.setattr(
        extract_module, "openrouter_extract_good_bad_with", boom_or_good_bad
    )
    monkeypatch.setattr(extract_module, "mistral_extract_field", fake_mistral_field)
    monkeypatch.setattr(
        extract_module, "mistral_extract_good_bad_with", fake_mistral_good_bad
    )

    dog = make_dog(description_en="A female dog.")
    enrich_from_desc(session)
    session.refresh(dog)

    assert dog.gender_from_desc == "female"
    assert "gender" in fallback_field_calls
    assert fallback_good_bad_calls == [True]
    assert dog.good_with_from_desc == ["children"]
    assert dog.bad_with_from_desc == ["cats"]


def test_extract_unknown_backend_raises(monkeypatch, session, make_dog):
    """Unknown backend names surface NotImplementedError."""
    import pytest

    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "anthropic")
    _stub_good_bad(monkeypatch)
    make_dog(description_en="anything")

    with pytest.raises(NotImplementedError):
        enrich_from_desc(session)
