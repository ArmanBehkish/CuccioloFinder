"""Breed inference dispatcher.

Each sub-pipeline writes its own rows to `inferred_dog_breeds` keyed by a
distinct `method`. There is no write-time winner; the displayed breed is
chosen at API/frontend read time from the candidate rows.

Sub-pipelines are independent: each loads its own models, iterates over
the active-dog set, and upserts on `(dog_id, method)`. Re-running one
sub-pipeline overwrites only its own rows.

Which sub-pipelines run is controlled by `BREED_DETECTION_PIPELINES` in
`cucciolofinder.config`.
"""

from collections.abc import Callable

from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.config import BREED_DETECTION_PIPELINES
from cucciolofinder.database import InferredDogBreed

# Sub-pipeline runners are loaded lazily — `breed/image.py` pulls in
# torch / transformers, which are worker-only deps. Importing this
# module from the API container or from test code that doesn't exercise
# inference must stay lightweight.
PIPELINES: dict[str, Callable[[Session], int]] = {}


def _load_default_pipelines() -> None:
    """Populate `PIPELINES` from the real sub-pipeline modules.

    Called lazily by `enrich_breed_detection`. Tests that want to bypass
    the heavy imports populate `PIPELINES` themselves before calling the
    dispatcher — this function is a no-op when `PIPELINES` is already
    non-empty.
    """
    if PIPELINES:
        return
    from . import cat_similarity as cat_similarity_pipeline
    from . import image as image_pipeline

    PIPELINES["image"] = image_pipeline.run
    PIPELINES["cat_similarity"] = cat_similarity_pipeline.run


def upsert_inferred_breed(
    session: Session,
    dog_id: int,
    method: str,
    value: str,
    model_name: str | None = None,
    confidence: float | None = None,
) -> None:
    """Upsert a single (dog_id, method) row in inferred_dog_breeds."""
    existing = (
        session.query(InferredDogBreed)
        .filter_by(dog_id=dog_id, method=method)
        .first()
    )
    if existing:
        existing.value = value
        existing.model_name = model_name
        existing.confidence = confidence
    else:
        session.add(
            InferredDogBreed(
                dog_id=dog_id,
                method=method,
                value=value,
                model_name=model_name,
                confidence=confidence,
            )
        )


def enrich_breed_detection(session: Session) -> int:
    """Run the breed-inference sub-pipelines listed in BREED_DETECTION_PIPELINES.

    Returns the total number of inferred-breed rows written across all
    enabled sub-pipelines. Each sub-pipeline manages its own model
    loading and iteration over dogs.
    """
    _load_default_pipelines()
    total = 0
    for name in BREED_DETECTION_PIPELINES:
        runner = PIPELINES.get(name)
        if runner is None:
            logger.warning(f"Unknown breed-detection sub-pipeline '{name}', skipping")
            continue
        logger.info(f"Breed inference: {name} sub-pipeline")
        total += runner(session)

    session.commit()
    logger.info(f"Breed inference complete. Total rows written: {total}")
    return total
