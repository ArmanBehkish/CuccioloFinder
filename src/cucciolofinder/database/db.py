from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_DB_PATH = Path("data/db/cucciolofinder.db")


def get_engine(db_path: Path = DEFAULT_DB_PATH) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def get_session(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
