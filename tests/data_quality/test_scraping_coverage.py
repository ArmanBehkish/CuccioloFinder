"""Verify that each scraper has populated the database with dogs."""

import pytest
from loguru import logger
from sqlalchemy import func

from cucciolofinder.config import DISABLED_SHELTERS
from cucciolofinder.database import Dog
from cucciolofinder.scrapers.pipelines import SPIDER_SOURCE_MAP

# Derived from the spider→source_site mapping minus anything disabled in
# config.py. Auto-adapts when a shelter is toggled — no manual list edits.
EXPECTED_SOURCES = sorted(set(SPIDER_SOURCE_MAP.values()) - set(DISABLED_SHELTERS))


@pytest.fixture(scope="session")
def source_counts(db_session):
    """Query dog counts per source site once for all tests."""
    rows = (
        db_session.query(Dog.source_site, func.count(Dog.id))
        .group_by(Dog.source_site)
        .all()
    )
    return {site: count for site, count in rows}


def test_total_dogs(source_counts):
    """At least one dog exists in the database."""
    total = sum(source_counts.values())
    logger.info(f"\nTotal dogs: {total}")
    logger.info(f"\n{'Source':<20} {'Count':>6}")
    logger.info("-" * 28)
    for source in EXPECTED_SOURCES:
        count = source_counts.get(source, 0)
        logger.info(f"{source:<20} {count:>6}")
    assert total > 0, "Database has no dogs at all"


@pytest.mark.parametrize("source", EXPECTED_SOURCES)
def test_source_has_dogs(source, source_counts):
    """Each expected source should have at least one dog."""
    count = source_counts.get(source, 0)
    assert count > 0, f"Source '{source}' has 0 dogs — scraper may be broken"
