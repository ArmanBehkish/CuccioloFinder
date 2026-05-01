"""Shared fixtures for identity / collision-prevention tests.

Each test gets a fresh temp-file SQLite database with the full schema. We
deliberately skip `init_db` so we don't need the AKC CSV present.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cucciolofinder.database.models import Base, Dog, DogImage


@pytest.fixture
def engine(tmp_path):
    db_path = tmp_path / "identity_test.db"
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


def make_dog(
    session,
    *,
    source_site: str,
    source_url: str,
    name: str,
    dog_uid: str,
    generation: int = 1,
    image_urls: list[str] | None = None,
    superseded_at=None,
    **fields,
) -> Dog:
    """Helper: insert a Dog (and optionally DogImage rows) and commit."""
    dog = Dog(
        source_site=source_site,
        source_url=source_url,
        name=name,
        dog_uid=dog_uid,
        generation=generation,
        superseded_at=superseded_at,
        **fields,
    )
    session.add(dog)
    session.flush()
    for i, url in enumerate(image_urls or []):
        session.add(DogImage(dog_id=dog.id, url=url, position=i))
    session.commit()
    return dog


@pytest.fixture
def make_dog_factory(session):
    def _factory(**kwargs):
        return make_dog(session, **kwargs)
    return _factory
