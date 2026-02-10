import os
from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Dog, FieldProvenance

DEFAULT_DB_PATH = Path(os.environ.get("DB_PATH", "data/db/cucciolofinder.db"))

# All translatable _en fields
TRANSLATION_FIELDS_EN = [
    "description_en", "gender_en", "age_en", "size_en", "breed_en",
    "fur_en", "microchip_en", "sterilization_en", "vaccine_en",
    "deworming_en", "good_with_en", "bad_with_en",
]


def get_engine(db_path: Path = DEFAULT_DB_PATH) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def get_session(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)


def reset_translations(session: Session) -> int:
    #Reset all _en fields to NULL
    dogs = session.query(Dog).all()
    count = 0

    for dog in dogs:
        updated = False
        for field in TRANSLATION_FIELDS_EN:
            if getattr(dog, field, None) is not None:
                setattr(dog, field, None)
                updated = True

        if updated:
            count += 1

    # Clear translation provenance records
    deleted = session.query(FieldProvenance).filter(
        FieldProvenance.method == "llm"
    ).delete()

    session.commit()
    logger.info(f"Reset translations for {count} dogs, deleted {deleted} provenance records")
    return count
