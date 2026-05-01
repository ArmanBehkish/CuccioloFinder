"""Shared fixtures for enrichment tests.

Each test gets a fresh temp-file SQLite database with the full schema.
We deliberately skip `init_db` so we don't need the AKC CSV present —
tests that need rows in `breeds` seed them explicitly.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cucciolofinder.database.models import Base, Dog


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "enrichment_test.db"
    eng = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def session(session_factory):
    with session_factory() as s:
        yield s


@pytest.fixture
def make_dog(session):
    """Insert a Dog row with sensible defaults; return the persisted instance."""
    counter = {"n": 0}

    def _factory(**fields) -> Dog:
        counter["n"] += 1
        n = counter["n"]
        defaults = {
            "source_site": "test",
            "source_url": f"https://example.com/dog/{n}",
            "dog_uid": f"uid{n:013d}",
            "generation": 1,
            "name": f"Dog{n}",
        }
        defaults.update(fields)
        dog = Dog(**defaults)
        session.add(dog)
        session.commit()
        return dog

    return _factory
