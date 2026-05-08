"""Tests for Stage 3 (breed inference) dispatcher and upsert helper.

The image / cat_similarity sub-pipelines themselves load heavy models, so
these tests stub them out and only exercise the orchestration layer:
- dispatcher iterates the configured sub-pipelines
- each writes its own rows to `inferred_dog_breeds`
- re-running a sub-pipeline overwrites only its own method rows
- different methods coexist on the same dog
"""

from cucciolofinder.database.models import Breed, InferredDogBreed
from cucciolofinder.enrichment.breed import dispatcher as dispatcher_module
from cucciolofinder.enrichment.breed.dispatcher import (
    enrich_breed_detection,
    upsert_inferred_breed,
)


def _seed_breeds(session, names: list[str]) -> None:
    for name in names:
        session.add(Breed(name=name))
    session.commit()


def test_dispatcher_runs_only_configured_pipelines(monkeypatch, session, make_dog):
    """`BREED_DETECTION_PIPELINES` controls which sub-pipelines run."""
    _seed_breeds(session, ["Labrador Retriever", "Poodle"])
    dog = make_dog(description_en="anything")

    calls: list[str] = []

    def make_runner(method: str, value: str, conf: float):
        def runner(s):
            calls.append(method)
            upsert_inferred_breed(
                s, dog_id=dog.id, method=method, value=value,
                model_name=f"{method}-model", confidence=conf,
            )
            return 1
        return runner

    monkeypatch.setattr(
        dispatcher_module,
        "PIPELINES",
        {
            "image": make_runner("image", "Labrador Retriever", 0.9),
            "cat_similarity": make_runner("cat_similarity", "Poodle", 0.7),
        },
    )
    monkeypatch.setattr(
        dispatcher_module, "BREED_DETECTION_PIPELINES", ["image"]
    )

    total = enrich_breed_detection(session)

    assert calls == ["image"]
    assert total == 1
    rows = session.query(InferredDogBreed).filter_by(dog_id=dog.id).all()
    assert {r.method for r in rows} == {"image"}


def test_dispatcher_writes_one_row_per_method_per_dog(monkeypatch, session, make_dog):
    """Each enabled sub-pipeline writes its own row keyed by `method`."""
    _seed_breeds(session, ["Labrador Retriever", "Poodle"])
    dog = make_dog(description_en="anything")

    def image_runner(s):
        upsert_inferred_breed(
            s, dog_id=dog.id, method="image", value="Labrador Retriever",
            model_name="vit", confidence=0.91,
        )
        return 1

    def cat_runner(s):
        upsert_inferred_breed(
            s, dog_id=dog.id, method="cat_similarity", value="Poodle",
            model_name="cat-v1", confidence=0.73,
        )
        return 1

    monkeypatch.setattr(
        dispatcher_module,
        "PIPELINES",
        {"image": image_runner, "cat_similarity": cat_runner},
    )
    monkeypatch.setattr(
        dispatcher_module,
        "BREED_DETECTION_PIPELINES",
        ["image", "cat_similarity"],
    )

    total = enrich_breed_detection(session)
    assert total == 2

    rows = session.query(InferredDogBreed).filter_by(dog_id=dog.id).all()
    by_method = {r.method: r for r in rows}
    assert set(by_method) == {"image", "cat_similarity"}
    assert by_method["image"].value == "Labrador Retriever"
    assert by_method["image"].confidence == 0.91
    assert by_method["cat_similarity"].value == "Poodle"


def test_dispatcher_rerun_overwrites_same_method(monkeypatch, session, make_dog):
    """Re-running a sub-pipeline overwrites that method's row, not others."""
    _seed_breeds(session, ["Labrador Retriever", "Poodle", "Beagle"])
    dog = make_dog(description_en="anything")

    # Seed a cat_similarity row from a "previous run".
    upsert_inferred_breed(
        session, dog_id=dog.id, method="cat_similarity", value="Beagle",
        model_name="old-model", confidence=0.5,
    )
    session.commit()

    # Now run image (writes new row) + cat_similarity (overwrites the seed row).
    def image_runner(s):
        upsert_inferred_breed(
            s, dog_id=dog.id, method="image", value="Labrador Retriever",
            model_name="vit", confidence=0.95,
        )
        return 1

    def cat_runner(s):
        upsert_inferred_breed(
            s, dog_id=dog.id, method="cat_similarity", value="Poodle",
            model_name="cat-v1", confidence=0.8,
        )
        return 1

    monkeypatch.setattr(
        dispatcher_module,
        "PIPELINES",
        {"image": image_runner, "cat_similarity": cat_runner},
    )
    monkeypatch.setattr(
        dispatcher_module,
        "BREED_DETECTION_PIPELINES",
        ["image", "cat_similarity"],
    )

    enrich_breed_detection(session)

    rows = session.query(InferredDogBreed).filter_by(dog_id=dog.id).all()
    assert len(rows) == 2  # image + cat_similarity — no duplicates
    by_method = {r.method: r for r in rows}
    assert by_method["cat_similarity"].value == "Poodle"
    assert by_method["cat_similarity"].model_name == "cat-v1"
    assert by_method["cat_similarity"].confidence == 0.8


def test_dispatcher_skips_unknown_pipeline_name(monkeypatch, session):
    """Misconfigured pipeline names log a warning and are skipped.

    `PIPELINES` is patched non-empty so `_load_default_pipelines()` is a
    no-op (otherwise it would pull in torch).
    """
    monkeypatch.setattr(
        dispatcher_module, "PIPELINES", {"image": lambda s: 0}
    )
    monkeypatch.setattr(
        dispatcher_module, "BREED_DETECTION_PIPELINES", ["nonexistent"]
    )

    total = enrich_breed_detection(session)
    assert total == 0


def test_upsert_inserts_then_updates(session, make_dog):
    """`upsert_inferred_breed` inserts when missing, updates when present."""
    _seed_breeds(session, ["Labrador Retriever", "Poodle"])
    dog = make_dog(description_en="x")

    upsert_inferred_breed(
        session, dog_id=dog.id, method="image", value="Labrador Retriever",
        model_name="vit", confidence=0.5,
    )
    session.commit()

    rows = session.query(InferredDogBreed).filter_by(dog_id=dog.id, method="image").all()
    assert len(rows) == 1 and rows[0].value == "Labrador Retriever"

    upsert_inferred_breed(
        session, dog_id=dog.id, method="image", value="Poodle",
        model_name="vit-v2", confidence=0.9,
    )
    session.commit()

    rows = session.query(InferredDogBreed).filter_by(dog_id=dog.id, method="image").all()
    assert len(rows) == 1
    assert rows[0].value == "Poodle"
    assert rows[0].model_name == "vit-v2"
    assert rows[0].confidence == 0.9
