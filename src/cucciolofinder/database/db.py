import csv
import json
import os
from pathlib import Path

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from .models import Base, Breed, Dog, FieldProvenance

DEFAULT_DB_PATH = Path(os.environ.get("DB_PATH", "data/db/cucciolofinder.db"))
AKC_CSV = Path(os.environ.get("AKC_CSV_PATH", "data/datasets/akc-data-latest.csv"))
VIT_TO_AKC_JSON = Path(os.environ.get("VIT_TO_AKC_PATH", "data/datasets/vit_to_akc.json"))

# All translatable _en fields
TRANSLATION_FIELDS_EN = [
    "description_en", "gender_en", "age_en", "size_en", "breed_en",
    "fur_en", "microchip_en", "sterilization_en", "vaccine_en",
    "deworming_en", "good_with_en", "bad_with_en",
]


def get_engine(db_path: Path = DEFAULT_DB_PATH) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False, poolclass=NullPool)


def populate_breeds(engine: Engine) -> int:
    """Seed the breeds table from AKC CSV + ViT-to-AKC JSON mapping.

    Inserts all AKC breeds with canonical names. For those that have a
    ViT label mapping, also stores the vit_label. Skips existing rows.
    Returns the number of breeds inserted.
    """
    akc_breeds: list[str] = []
    if AKC_CSV.exists():
        with open(AKC_CSV, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                breed = row.get("", "").strip()
                if breed:
                    akc_breeds.append(breed)

    vit_to_akc: dict[str, str] = {}
    if VIT_TO_AKC_JSON.exists():
        with open(VIT_TO_AKC_JSON, encoding="utf-8") as fh:
            vit_to_akc = json.load(fh)

    akc_to_vit: dict[str, str] = {v: k for k, v in vit_to_akc.items()}

    session_factory = sessionmaker(bind=engine)
    inserted = 0
    with session_factory() as session:
        existing = {b.name for b in session.query(Breed).all()}
        for name in akc_breeds:
            if name in existing:
                continue
            session.add(Breed(name=name, vit_label=akc_to_vit.get(name)))
            inserted += 1
        session.commit()

    logger.info(f"Breeds table: {inserted} new, {len(akc_breeds)} total AKC breeds")
    return inserted


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    populate_breeds(engine)


def get_session(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)


def reset_translations(session: Session) -> int:
    #Reset all _en fields to NULL on active rows only
    dogs = session.query(Dog).filter(Dog.superseded_at.is_(None)).all()
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
