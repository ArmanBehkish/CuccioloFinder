"""Coverage report for breed-inference outputs.

Prints a per-source table showing how many active dogs have an `image`
breed inference and how many have a `cat_similarity` breed inference.
Run at the end of each worker run as a quick visibility check on
whether the breed pipelines produced output across the dataset.
"""

import pytest
from loguru import logger
from sqlalchemy import func

from cucciolofinder.database import Dog, InferredDogBreed

EXPECTED_SOURCES = [
    "quattrozampe",
    "empethy",
    "alberodimais",
    "enpatorino",
    "canileoasi",
]


@pytest.fixture(scope="session")
def inference_coverage(db_session):
    """Per-source counts of active dogs and active dogs with each method."""
    total_rows = (
        db_session.query(Dog.source_site, func.count(Dog.id))
        .filter(Dog.superseded_at.is_(None))
        .group_by(Dog.source_site)
        .all()
    )
    total = {site: count for site, count in total_rows}

    def per_source_for_method(method: str) -> dict[str, int]:
        rows = (
            db_session.query(Dog.source_site, func.count(func.distinct(Dog.id)))
            .join(InferredDogBreed, InferredDogBreed.dog_id == Dog.id)
            .filter(Dog.superseded_at.is_(None))
            .filter(InferredDogBreed.method == method)
            .group_by(Dog.source_site)
            .all()
        )
        return {site: count for site, count in rows}

    return {
        "total": total,
        "image": per_source_for_method("image"),
        "cat_similarity": per_source_for_method("cat_similarity"),
    }


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:5.1f}%" if whole else "   - "


def test_breed_inference_coverage_table(inference_coverage):
    """Print the per-source coverage table. Always passes — this is the
    reporting test; the assert tests below are the gates."""
    total = inference_coverage["total"]
    image = inference_coverage["image"]
    cat = inference_coverage["cat_similarity"]

    sources = sorted(set(EXPECTED_SOURCES) | set(total.keys()))
    sum_total = sum(total.get(s, 0) for s in sources)
    sum_image = sum(image.get(s, 0) for s in sources)
    sum_cat = sum(cat.get(s, 0) for s in sources)

    logger.info("\nBreed inference coverage (active dogs only):\n")
    logger.info(
        f"{'Source':<16} {'Total':>6}  "
        f"{'Image':>6} {'%img':>6}  {'CatSim':>6} {'%cat':>6}"
    )
    logger.info("-" * 56)
    for s in sources:
        n = total.get(s, 0)
        img = image.get(s, 0)
        c = cat.get(s, 0)
        logger.info(
            f"{s:<16} {n:>6}  "
            f"{img:>6} {_pct(img, n):>6}  {c:>6} {_pct(c, n):>6}"
        )
    logger.info("-" * 56)
    logger.info(
        f"{'TOTAL':<16} {sum_total:>6}  "
        f"{sum_image:>6} {_pct(sum_image, sum_total):>6}  "
        f"{sum_cat:>6} {_pct(sum_cat, sum_total):>6}"
    )


def test_image_breed_inference_present(inference_coverage):
    """At least one active dog should have an `image` breed inference."""
    total = sum(inference_coverage["image"].values())
    assert total > 0, (
        "No active dogs have an `image` breed inference — the image "
        "classifier may have failed or no dogs had downloadable photos"
    )


def test_cat_similarity_breed_inference_present(inference_coverage):
    """At least one active dog should have a `cat_similarity` breed inference."""
    total = sum(inference_coverage["cat_similarity"].values())
    assert total > 0, (
        "No active dogs have a `cat_similarity` breed inference — "
        "every dog may have been below CAT_SIMILARITY_MIN_COVERAGE, or "
        "the pipeline may not have run"
    )
