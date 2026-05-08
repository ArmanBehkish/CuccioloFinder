"""Integration tests for the IdentityPipeline + DatabasePipeline flow.

We simulate a sequence of scrapes by feeding items through the pipelines
and verify that:
- A fresh URL produces a gen=1 row.
- A re-scrape with overlapping images leaves the row alone (or updates
  it only on actual changes).
- A re-scrape with disjoint images supersedes the old row and inserts
  a new one with a fresh dog_uid and generation+1.
"""

from types import SimpleNamespace

import pytest
from scrapy.exceptions import DropItem

from cucciolofinder.database.models import Breed, Dog, InferredDogBreed
from cucciolofinder.scrapers import pipelines as pipelines_module
from cucciolofinder.scrapers.pipelines import (
    FROM_DESC_COLUMNS,
    DatabasePipeline,
    IdentityPipeline,
)


@pytest.fixture
def patch_pipeline_db(monkeypatch, engine, session_factory):
    """Make IdentityPipeline / DatabasePipeline use the test engine."""
    monkeypatch.setattr(pipelines_module, "get_engine", lambda: engine)
    monkeypatch.setattr(pipelines_module, "init_db", lambda eng: None)
    monkeypatch.setattr(pipelines_module, "get_session", lambda eng: session_factory)


@pytest.fixture
def spider():
    return SimpleNamespace(name="EnpaTorinoSpider")


def _run_pipelines(item, spider, identity, database):
    item = identity.process_item(item, spider)
    return database.process_item(item, spider)


def _read_active_dogs(session_factory, source_url):
    with session_factory() as s:
        return (
            s.query(Dog)
            .filter_by(source_url=source_url, superseded_at=None)
            .all()
        )


def _read_all_dogs(session_factory, source_url):
    with session_factory() as s:
        return s.query(Dog).filter_by(source_url=source_url).order_by(Dog.id).all()


# ---- fresh URL ----

def test_fresh_url_inserts_gen_1(patch_pipeline_db, session_factory, spider):
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    item = {
        "source_url": "https://x.com/dogs/bobby",
        "name": "Bobby",
        "description": "A friendly dog",
        "image_urls": ["img1.jpg", "img2.jpg"],
        "images": [],  # no downloaded image metadata in tests
    }
    _run_pipelines(item, spider, identity, database)

    active = _read_active_dogs(session_factory, "https://x.com/dogs/bobby")
    assert len(active) == 1
    assert active[0].name == "Bobby"
    assert active[0].generation == 1
    assert active[0].dog_uid


# ---- same dog re-scraped, no changes ----

def test_unchanged_rescrape_drops_item(patch_pipeline_db, session_factory, spider):
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    item = {
        "source_url": "https://x.com/dogs/bobby",
        "name": "Bobby",
        "description": "A friendly dog",
        "image_urls": ["img1.jpg", "img2.jpg"],
        "images": [],
    }
    _run_pipelines(item, spider, identity, database)
    original = _read_active_dogs(session_factory, "https://x.com/dogs/bobby")[0]
    original_uid = original.dog_uid

    # Second run with identical data — should be dropped.
    item2 = dict(item)  # fresh dict; pipelines mutate it
    item2["image_urls"] = list(item["image_urls"])
    with pytest.raises(DropItem):
        _run_pipelines(item2, spider, identity, database)

    # Still exactly one active row, same UID.
    after = _read_active_dogs(session_factory, "https://x.com/dogs/bobby")
    assert len(after) == 1
    assert after[0].dog_uid == original_uid


# ---- same dog re-scraped, field changed ----

def test_field_change_updates_existing_row(patch_pipeline_db, session_factory, spider):
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    item = {
        "source_url": "https://x.com/dogs/bobby",
        "name": "Bobby",
        "description": "Old description",
        "image_urls": ["img1.jpg"],
        "images": [],
    }
    _run_pipelines(item, spider, identity, database)
    original_uid = _read_active_dogs(session_factory, "https://x.com/dogs/bobby")[0].dog_uid

    item2 = {
        "source_url": "https://x.com/dogs/bobby",
        "name": "Bobby",
        "description": "Updated description",  # changed
        "image_urls": ["img1.jpg"],
        "images": [],
    }
    _run_pipelines(item2, spider, identity, database)

    active = _read_active_dogs(session_factory, "https://x.com/dogs/bobby")
    assert len(active) == 1
    assert active[0].description == "Updated description"
    # Same UID — same physical dog.
    assert active[0].dog_uid == original_uid


# ---- collision: image-disjoint re-scrape ----

def test_image_disjoint_supersedes_and_inserts_new_generation(
    patch_pipeline_db, session_factory, spider
):
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    # Scrape 1: original Bobby.
    item1 = {
        "source_url": "https://x.com/dogs/bobby",
        "name": "Bobby",
        "description": "Original Bobby",
        "image_urls": ["bobby1.jpg", "bobby2.jpg"],
        "images": [],
    }
    _run_pipelines(item1, spider, identity, database)
    old = _read_active_dogs(session_factory, "https://x.com/dogs/bobby")[0]
    old_id = old.id
    old_uid = old.dog_uid

    # Scrape 2: shelter recycled the URL for a different dog.
    item2 = {
        "source_url": "https://x.com/dogs/bobby",
        "name": "Bobby",  # same name by coincidence
        "description": "A different dog now",
        "image_urls": ["other1.jpg", "other2.jpg"],  # zero overlap
        "images": [],
    }
    _run_pipelines(item2, spider, identity, database)

    # Two rows total.
    all_rows = _read_all_dogs(session_factory, "https://x.com/dogs/bobby")
    assert len(all_rows) == 2

    # Old row is superseded.
    superseded = next(r for r in all_rows if r.id == old_id)
    assert superseded.superseded_at is not None
    assert superseded.generation == 1

    # New row is active with gen=2 and a fresh UID.
    active = _read_active_dogs(session_factory, "https://x.com/dogs/bobby")
    assert len(active) == 1
    new_row = active[0]
    assert new_row.id != old_id
    assert new_row.generation == 2
    assert new_row.dog_uid != old_uid
    assert new_row.description == "A different dog now"


# ---- description change clears *_from_desc, preserves inferred breeds ----

def test_description_change_clears_from_desc_only(
    patch_pipeline_db, session_factory, spider
):
    """Description change → all `*_from_desc` cleared so Stage 2 re-extracts.
    Inferred-breed rows are NOT touched here — each method has its own
    invalidation rule keyed on its actual inputs (e.g. image set for
    `image`/`image_2nd`). Image set unchanged → same dog (no supersession,
    same `dog_uid`)."""
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    item = {
        "source_url": "https://x.com/dogs/bobby",
        "name": "Bobby",
        "description": "Old description",
        "image_urls": ["img1.jpg"],
        "images": [],
    }
    _run_pipelines(item, spider, identity, database)

    # Seed: every `*_from_desc` populated, plus an image inferred row.
    with session_factory() as s:
        s.add(Breed(name="Labrador Retriever"))
        s.flush()
        dog = (
            s.query(Dog)
            .filter_by(source_url="https://x.com/dogs/bobby", superseded_at=None)
            .first()
        )
        list_cols = {"good_with_from_desc", "bad_with_from_desc"}
        for col in FROM_DESC_COLUMNS:
            setattr(dog, col, ["seeded"] if col in list_cols else "seeded")
        s.add(InferredDogBreed(
            dog_id=dog.id, method="image", value="Labrador Retriever",
            model_name="vit", confidence=0.9,
        ))
        s.commit()
        seeded_id = dog.id
        seeded_uid = dog.dog_uid

    # Re-scrape with a CHANGED description, same image set.
    item2 = {
        "source_url": "https://x.com/dogs/bobby",
        "name": "Bobby",
        "description": "Updated description",
        "image_urls": ["img1.jpg"],
        "images": [],
    }
    _run_pipelines(item2, spider, identity, database)

    with session_factory() as s:
        dog = (
            s.query(Dog)
            .filter_by(source_url="https://x.com/dogs/bobby", superseded_at=None)
            .first()
        )
        # Same row — image set unchanged means no supersession.
        assert dog.id == seeded_id
        assert dog.dog_uid == seeded_uid
        assert dog.description == "Updated description"

        # All `*_from_desc` columns cleared.
        for col in FROM_DESC_COLUMNS:
            assert getattr(dog, col) is None, (
                f"{col} should be NULL after description change, "
                f"got {getattr(dog, col)!r}"
            )

        # Inferred breed rows are NOT deleted by description change.
        rows = s.query(InferredDogBreed).filter_by(dog_id=dog.id).all()
        methods = {r.method for r in rows}
        assert methods == {"image"}, (
            f"description change must not delete inferred breed rows, "
            f"got methods={methods}"
        )


def test_field_change_other_than_description_keeps_from_desc(
    patch_pipeline_db, session_factory, spider
):
    """Non-description field change preserves `*_from_desc` (description
    unchanged → no Stage 2 re-run) and image inferred rows (image set
    unchanged), but does delete cat_similarity rows since cat_similarity
    reads many fields and any change could shift the score."""
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    item = {
        "source_url": "https://x.com/dogs/rex",
        "name": "Rex",
        "description": "Same description",
        "gender": "maschio",
        "image_urls": ["rex1.jpg"],
        "images": [],
    }
    _run_pipelines(item, spider, identity, database)

    with session_factory() as s:
        s.add(Breed(name="Beagle"))
        s.flush()
        dog = (
            s.query(Dog)
            .filter_by(source_url="https://x.com/dogs/rex", superseded_at=None)
            .first()
        )
        dog.gender_from_desc = "male"
        dog.size_from_desc = "medium"
        s.add(InferredDogBreed(
            dog_id=dog.id, method="image", value="Beagle",
            model_name="vit", confidence=0.8,
        ))
        s.add(InferredDogBreed(
            dog_id=dog.id, method="cat_similarity", value="Beagle",
            model_name="cat-v1", confidence=0.7,
        ))
        s.commit()

    item2 = dict(item)
    item2["gender"] = "femmina"  # change a non-description field
    item2["image_urls"] = list(item["image_urls"])
    _run_pipelines(item2, spider, identity, database)

    with session_factory() as s:
        dog = (
            s.query(Dog)
            .filter_by(source_url="https://x.com/dogs/rex", superseded_at=None)
            .first()
        )
        assert dog.gender == "femmina"
        # `*_from_desc` preserved (description unchanged).
        assert dog.gender_from_desc == "male"
        assert dog.size_from_desc == "medium"
        # Image rows preserved (images unchanged); cat_similarity deleted
        # because any dog-field change invalidates it.
        methods = {
            r.method
            for r in s.query(InferredDogBreed).filter_by(dog_id=dog.id).all()
        }
        assert methods == {"image"}


# ---- sentinel invalidation (Option A: from_desc/breed_en sentinels) ----

def test_description_change_clears_sentinel_from_desc_columns(
    patch_pipeline_db, session_factory, spider
):
    """`*_from_desc` columns holding the empty-string / empty-list sentinels
    (from a previous successful-but-no-signal LLM call) must clear back to
    NULL on description change so the next enrichment run retries them."""
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    item = {
        "source_url": "https://x.com/dogs/sentinel",
        "name": "Sentinel",
        "description": "Old description",
        "image_urls": ["s1.jpg"],
        "images": [],
    }
    _run_pipelines(item, spider, identity, database)

    list_cols = {"good_with_from_desc", "bad_with_from_desc"}
    with session_factory() as s:
        dog = (
            s.query(Dog)
            .filter_by(source_url="https://x.com/dogs/sentinel", superseded_at=None)
            .first()
        )
        # Seed with sentinels (what a real Stage-2 no-signal pass would write).
        for col in FROM_DESC_COLUMNS:
            setattr(dog, col, [] if col in list_cols else "")
        s.commit()

    item2 = dict(item)
    item2["description"] = "Updated description"
    item2["image_urls"] = list(item["image_urls"])
    _run_pipelines(item2, spider, identity, database)

    with session_factory() as s:
        dog = (
            s.query(Dog)
            .filter_by(source_url="https://x.com/dogs/sentinel", superseded_at=None)
            .first()
        )
        for col in FROM_DESC_COLUMNS:
            assert getattr(dog, col) is None, (
                f"sentinel {col} must clear to NULL after description change "
                f"so next run retries; got {getattr(dog, col)!r}"
            )


def test_breed_change_clears_sentinel_breed_en(
    patch_pipeline_db, session_factory, spider
):
    """`breed_en` holding the empty-string sentinel must clear to NULL
    when the raw `breed` field changes — same pattern as `*_from_desc`."""
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    item = {
        "source_url": "https://x.com/dogs/sentinel-breed",
        "name": "Pal",
        "description": "Same desc",
        "breed": "fluffy",
        "image_urls": ["p1.jpg"],
        "images": [],
    }
    _run_pipelines(item, spider, identity, database)

    with session_factory() as s:
        dog = (
            s.query(Dog)
            .filter_by(source_url="https://x.com/dogs/sentinel-breed", superseded_at=None)
            .first()
        )
        # Seed sentinel — what a non-breed phrase ("fluffy") would land
        # in breed_en after a Stage-1 successful-but-no-signal call.
        dog.breed_en = ""
        s.commit()

    item2 = dict(item)
    item2["breed"] = "Labrador"  # actual breed name now
    item2["image_urls"] = list(item["image_urls"])
    _run_pipelines(item2, spider, identity, database)

    with session_factory() as s:
        dog = (
            s.query(Dog)
            .filter_by(source_url="https://x.com/dogs/sentinel-breed", superseded_at=None)
            .first()
        )
        assert dog.breed == "Labrador"
        assert dog.breed_en is None, (
            "sentinel breed_en must clear to NULL when raw breed changes"
        )


# ---- multiple-generation chain (URL recycled twice) ----

def test_multiple_generations_chain(patch_pipeline_db, session_factory, spider):
    identity = IdentityPipeline()
    database = DatabasePipeline()
    identity.open_spider(spider)
    database.open_spider(spider)

    sets = [
        ["dog_a_1.jpg", "dog_a_2.jpg"],
        ["dog_b_1.jpg", "dog_b_2.jpg"],
        ["dog_c_1.jpg", "dog_c_2.jpg"],
    ]
    for i, urls in enumerate(sets):
        item = {
            "source_url": "https://x.com/dogs/bobby",
            "name": f"Bobby-{i}",
            "description": f"Dog #{i}",
            "image_urls": urls,
            "images": [],
        }
        _run_pipelines(item, spider, identity, database)

    all_rows = _read_all_dogs(session_factory, "https://x.com/dogs/bobby")
    assert len(all_rows) == 3
    assert [r.generation for r in all_rows] == [1, 2, 3]
    assert all(r.superseded_at is not None for r in all_rows[:-1])
    assert all_rows[-1].superseded_at is None
    # All three UIDs distinct.
    uids = {r.dog_uid for r in all_rows}
    assert len(uids) == 3
