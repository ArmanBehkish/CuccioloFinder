"""Tests for `enrich_from_desc` (Stage 2: description extraction)."""

from cucciolofinder.enrichment import extract as extract_module
from cucciolofinder.enrichment.extract import enrich_from_desc


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
        "good_with": ["children", "other dogs"],
        "bad_with": ["cats"],
    }

    def fake_extract(description_en, *, field_name, **_):
        return fake_returns.get(field_name)

    monkeypatch.setattr(extract_module, "groq_extract_field", fake_extract)

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

    make_dog(
        description_en="something",
        gender_from_desc="male",  # pre-populated
    )

    enrich_from_desc(session)

    assert "gender" not in calls, "extractor should skip already-populated columns"
    assert "size" in calls and "breed" in calls


def test_extract_skips_dogs_without_description_en(monkeypatch, session, make_dog):
    """No description_en → dog skipped entirely; backend never called."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")

    called = []

    def fake_extract(*args, **kwargs):
        called.append(True)
        return "value"

    monkeypatch.setattr(extract_module, "groq_extract_field", fake_extract)

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

    dog = make_dog(description_en="Some text without any signal.")
    n = enrich_from_desc(session)

    assert n == 0
    session.refresh(dog)
    assert dog.gender_from_desc is None
    assert dog.size_from_desc is None
    assert dog.breed_from_desc is None


def test_extract_empty_list_leaves_column_null(monkeypatch, session, make_dog):
    """Empty list result for `good_with`/`bad_with` is treated as no signal."""
    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "groq")
    monkeypatch.setattr(
        extract_module,
        "groq_extract_field",
        lambda *_, field_name, **__: [] if field_name in {"good_with", "bad_with"} else None,
    )

    dog = make_dog(description_en="No social signals here.")
    enrich_from_desc(session)

    session.refresh(dog)
    assert dog.good_with_from_desc is None
    assert dog.bad_with_from_desc is None


def test_extract_unimplemented_backend_raises(monkeypatch, session, make_dog):
    """Backends without an implementation surface NotImplementedError."""
    import pytest

    monkeypatch.setattr(extract_module, "get_extract_backend", lambda: "mistral")
    make_dog(description_en="anything")

    with pytest.raises(NotImplementedError):
        enrich_from_desc(session)
