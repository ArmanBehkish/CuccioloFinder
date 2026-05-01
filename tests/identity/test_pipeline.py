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


# ---- description change invalidates description-derived signals only ----

def test_description_change_clears_from_desc_and_text_breeds_only(
    patch_pipeline_db, session_factory, spider
):
    """Description change → all `*_from_desc` cleared and description-
    derived `inferred_dog_breeds` rows deleted (e.g. `text_embedding`).
    Image-based rows (`image`, `image_2nd`) survive — they're derived
    from photos, not text. Image set unchanged → same dog (no
    supersession, same `dog_uid`)."""
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

    # Seed: every `*_from_desc` populated, plus one image row + one
    # text_embedding row in inferred_dog_breeds.
    with session_factory() as s:
        s.add(Breed(name="Labrador Retriever"))
        s.add(Breed(name="Poodle"))
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
        s.add(InferredDogBreed(
            dog_id=dog.id, method="text_embedding", value="Poodle",
            model_name="minilm", confidence=0.6,
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

        # Only description-derived inferred rows deleted; image row preserved.
        rows = s.query(InferredDogBreed).filter_by(dog_id=dog.id).all()
        methods = {r.method for r in rows}
        assert methods == {"image"}, (
            f"image-derived inferred breeds must survive description change, "
            f"got methods={methods}"
        )


def test_field_change_other_than_description_keeps_from_desc(
    patch_pipeline_db, session_factory, spider
):
    """Non-description field change must NOT clear `*_from_desc` or
    delete inferred breeds — that invalidation is description-specific."""
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
            dog_id=dog.id, method="text_embedding", value="Beagle",
            model_name="minilm", confidence=0.7,
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
        # All inferred rows preserved.
        methods = {
            r.method
            for r in s.query(InferredDogBreed).filter_by(dog_id=dog.id).all()
        }
        assert methods == {"image", "text_embedding"}


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
