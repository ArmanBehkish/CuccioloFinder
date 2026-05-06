"""Tests for `enrich_translations` (Stage 1) — focused on `breed_en`.

The other Stage 1 columns (gender_en, size_en, …) are dominated by the
static translation map and the model fallback path is exercised
indirectly. The `breed_en` path is special because it goes through an
LLM extract call that frequently returns None for non-breed inputs
("fluffy", "ball of joy"), which we want to mark with the empty-string
sentinel rather than leave NULL.
"""

from cucciolofinder.enrichment import enrich as enrich_module
from cucciolofinder.enrichment.enrich import enrich_translations


def test_breed_translation_null_writes_sentinel(monkeypatch, session, make_dog):
    """LLM returns None for the raw breed → breed_en becomes "" (sentinel)."""
    monkeypatch.setattr(enrich_module, "_translate_breed", lambda _raw: None)

    dog = make_dog(breed="ball of joy")
    enrich_translations(session)
    session.refresh(dog)

    assert dog.breed_en == "", (
        "non-breed phrase should land an empty-string sentinel, "
        "not stay NULL"
    )


def test_breed_translation_value_writes_through(monkeypatch, session, make_dog):
    """LLM returns a real breed string → that string lands in breed_en."""
    monkeypatch.setattr(enrich_module, "_translate_breed", lambda _raw: "Labrador Retriever")

    dog = make_dog(breed="Labrador")
    enrich_translations(session)
    session.refresh(dog)

    assert dog.breed_en == "Labrador Retriever"


def test_breed_sentinel_blocks_re_translation(monkeypatch, session, make_dog):
    """Second pass over a dog with breed_en="" makes 0 LLM calls."""
    calls: list[str] = []

    def fake_translate(raw):
        calls.append(raw)
        return None

    monkeypatch.setattr(enrich_module, "_translate_breed", fake_translate)

    dog = make_dog(breed="fluffy")

    enrich_translations(session)
    session.refresh(dog)
    assert dog.breed_en == ""
    assert len(calls) == 1, "first pass should call _translate_breed once"

    calls.clear()
    enrich_translations(session)
    session.refresh(dog)

    assert calls == [], (
        "sentinel should block re-translation; instead saw: " f"{calls}"
    )
    assert dog.breed_en == ""


def test_breed_translation_exception_leaves_null(monkeypatch, session, make_dog):
    """Translation exception → breed_en stays NULL so next run retries."""
    from cucciolofinder.enrichment.groq_client import GroqError

    def boom(_raw):
        raise GroqError("simulated transient failure")

    monkeypatch.setattr(enrich_module, "_translate_breed", boom)

    dog = make_dog(breed="Labrador")
    enrich_translations(session)
    session.refresh(dog)

    # NULL — not "" — so the next nightly run retries.
    assert dog.breed_en is None
