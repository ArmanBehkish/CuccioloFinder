import pytest
from loguru import logger
from sqlalchemy import and_, func, or_

from cucciolofinder.database import Dog

# Italian fields paired with their _en counterparts.
FIELD_PAIRS = [
    ("description", "description_en"),
    ("gender", "gender_en"),
    ("age", "age_en"),
    ("size", "size_en"),
    ("breed", "breed_en"),
    ("fur", "fur_en"),
    ("microchip", "microchip_en"),
    ("sterilization", "sterilization_en"),
    ("vaccine", "vaccine_en"),
    ("deworming", "deworming_en"),
    ("good_with", "good_with_en"),
    ("bad_with", "bad_with_en"),
]

# Fields with a `*_from_desc` LLM-extracted fallback. The display rule
# is `<field>_en ?? <field>_from_desc`, so a field is considered usable
# when at least one of the two columns is populated.
#
# `description` is intentionally absent — there is no
# `description_from_desc` (the description IS the source).
FROM_DESC_FIELDS = [
    "gender", "age", "weight", "size", "breed", "fur",
    "microchip", "sterilization", "vaccine", "deworming",
    "good_with", "bad_with",
]

# Fields with no English counterpart and no `*_from_desc` fallback.
SOLO_FIELDS = [
    "post_date",
    "shelter_since",
    "scraped_at",
]


@pytest.fixture(scope="session")
def total_dogs(db_session):
    return db_session.query(func.count(Dog.id)).scalar()


@pytest.fixture(scope="session")
def field_counts(db_session):
    """Count non-NULL values for every field, including `_from_desc`."""
    counts = {}
    for it_field, en_field in FIELD_PAIRS:
        it_col = getattr(Dog, it_field)
        en_col = getattr(Dog, en_field)
        counts[it_field] = db_session.query(func.count(Dog.id)).filter(it_col.isnot(None)).scalar()
        counts[en_field] = db_session.query(func.count(Dog.id)).filter(en_col.isnot(None)).scalar()
    for field in FROM_DESC_FIELDS:
        col = getattr(Dog, f"{field}_from_desc")
        counts[f"{field}_from_desc"] = (
            db_session.query(func.count(Dog.id)).filter(col.isnot(None)).scalar()
        )
    for field in SOLO_FIELDS:
        col = getattr(Dog, field)
        counts[field] = db_session.query(func.count(Dog.id)).filter(col.isnot(None)).scalar()
    return counts


def test_field_population_summary(total_dogs, field_counts):
    """Log a full population report for all fields."""
    logger.info(f"\nTotal dogs: {total_dogs}")

    # Paired fields
    logger.info(
        f"\n{'Field (IT)':<20} {'Count':>6} {'%':>6}   "
        f"{'Field (EN)':<20} {'Count':>6} {'%':>6}"
    )
    logger.info("-" * 72)
    for it_field, en_field in FIELD_PAIRS:
        it_count = field_counts[it_field]
        en_count = field_counts[en_field]
        it_pct = (it_count / total_dogs * 100) if total_dogs else 0
        en_pct = (en_count / total_dogs * 100) if total_dogs else 0
        logger.info(
            f"{it_field:<20} {it_count:>6} {it_pct:>5.1f}%   "
            f"{en_field:<20} {en_count:>6} {en_pct:>5.1f}%"
        )

    # `*_from_desc` fallbacks
    logger.info(f"\n{'Field (from_desc)':<25} {'Count':>6} {'%':>6}")
    logger.info("-" * 39)
    for field in FROM_DESC_FIELDS:
        count = field_counts[f"{field}_from_desc"]
        pct = (count / total_dogs * 100) if total_dogs else 0
        logger.info(f"{field + '_from_desc':<25} {count:>6} {pct:>5.1f}%")

    # Solo fields
    logger.info(f"\n{'Field':<20} {'Count':>6} {'%':>6}")
    logger.info("-" * 34)
    for field in SOLO_FIELDS:
        count = field_counts[field]
        pct = (count / total_dogs * 100) if total_dogs else 0
        logger.info(f"{field:<20} {count:>6} {pct:>5.1f}%")

    assert total_dogs > 0, "Database has no dogs"


@pytest.mark.parametrize("it_field,en_field", FIELD_PAIRS)
def test_italian_field_populated(it_field, en_field, field_counts):
    """Each Italian field should be populated for at least one dog."""
    count = field_counts[it_field]
    assert count > 0, f"Italian field '{it_field}' is NULL for every dog"


@pytest.mark.parametrize("it_field,en_field", FIELD_PAIRS)
def test_field_value_available(it_field, en_field, field_counts, db_session):
    """Each field must have a usable value (`_en` OR `_from_desc`) for ≥1 dog.

    `description` only has `description_en` — no `_from_desc` sibling.
    """
    if it_field == "description":
        count = field_counts[en_field]
        assert count > 0, (
            f"'{en_field}' is NULL for every dog — translation may not have run"
        )
        return

    en_col = getattr(Dog, en_field)
    fd_col = getattr(Dog, f"{it_field}_from_desc")
    # An empty-string / empty-list sentinel means "LLM tried, no signal" —
    # treat as no usable value for data-quality purposes.
    count = (
        db_session.query(func.count(Dog.id))
        .filter(
            or_(
                and_(en_col.isnot(None), en_col != ""),
                and_(fd_col.isnot(None), fd_col != ""),
            )
        )
        .scalar()
    )
    assert count > 0, (
        f"Neither '{en_field}' nor '{it_field}_from_desc' is populated for any dog "
        "— translation and description-extraction stages may not have run"
    )


@pytest.mark.parametrize("field", SOLO_FIELDS)
def test_solo_field_populated(field, field_counts):
    """Each solo field should be populated for at least one dog."""
    count = field_counts[field]
    assert count > 0, f"Field '{field}' is NULL for every dog"
