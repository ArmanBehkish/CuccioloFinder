import pytest

from cucciolofinder.database import get_engine, get_session, init_db


@pytest.fixture(scope="session")
def db_session():
    engine = get_engine()
    init_db(engine)
    Session = get_session(engine)
    with Session() as session:
        yield session
