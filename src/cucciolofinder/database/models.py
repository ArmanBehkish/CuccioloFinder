from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Breed(Base):
    __tablename__ = "breeds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    vit_label = Column(String, unique=True, nullable=True)


class Dog(Base):
    __tablename__ = "dogs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_site = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    dog_uid = Column(String(16), nullable=False, unique=True, index=True)
    generation = Column(Integer, nullable=False, default=1)
    superseded_at = Column(DateTime, nullable=True)
    name = Column(String, nullable=False)

    description = Column(Text)
    description_en = Column(Text)

    # For each field below: `*` is the raw Italian value scraped from a
    # structured field, `*_en` is its English translation (no detection),
    # and `*_from_desc` is the LLM-extracted value from the free-text
    # description (in canonical English) used as fallback when no
    # structured field was present.
    gender = Column(String)
    gender_en = Column(String)
    gender_from_desc = Column(String)
    age = Column(String)
    age_en = Column(String)
    age_from_desc = Column(String)
    weight = Column(String)     # e.g., "30kg" or similar
    weight_from_desc = Column(String)
    size = Column(String)
    size_en = Column(String)
    size_from_desc = Column(String)
    # `breed` is the structured field from the shelter (Italian or English).
    # `breed_en` is its LLM translation — liberal free-form ("mixed",
    # "Labrador mix", "German Shepherd", etc.). Not FK-constrained: the
    # shelter's free-text inputs rarely match the canonical AKC catalogue,
    # and forcing them to would mostly produce NULLs. The canonical
    # catalogue is still used by `inferred_dog_breeds` (image / text-LLM /
    # clustering pipelines), which DO have FK to `breeds.name`.
    # `breed_from_desc` is the same shape as `breed_en` but extracted from
    # the description rather than the structured field.
    breed = Column(String)
    breed_en = Column(String, nullable=True)
    breed_from_desc = Column(String, nullable=True)
    fur = Column(String)
    fur_en = Column(String)
    fur_from_desc = Column(String)
    microchip = Column(String)
    microchip_en = Column(String)
    microchip_from_desc = Column(String)
    sterilization = Column(String)
    sterilization_en = Column(String)
    sterilization_from_desc = Column(String)
    vaccine = Column(String)
    vaccine_en = Column(String)
    vaccine_from_desc = Column(String)
    deworming = Column(String)
    deworming_en = Column(String)
    deworming_from_desc = Column(String)

    post_date = Column(Date)
    shelter_since = Column(String)      # may contain Italian date e.g, "7 Aprile 2021"

    good_with = Column(JSON)            # list
    good_with_en = Column(JSON)
    good_with_from_desc = Column(JSON)  # list, LLM-extracted from description
    bad_with = Column(JSON)
    bad_with_en = Column(JSON)
    bad_with_from_desc = Column(JSON)   # list, LLM-extracted from description

    scraped_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    images = relationship("DogImage", back_populates="dog", cascade="all, delete-orphan")
    inferred_breeds = relationship(
        "InferredDogBreed", back_populates="dog", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_dog_active_url",
            "source_site",
            "source_url",
            unique=True,
            sqlite_where=text("superseded_at IS NULL"),
        ),
    )


class DogImage(Base):
    __tablename__ = "dog_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dog_id = Column(Integer, ForeignKey("dogs.id", ondelete="CASCADE"), nullable=False)
    url = Column(String, nullable=False)
    local_path = Column(String)     # relative /data/images
    position = Column(Integer)      # keep order

    dog = relationship("Dog", back_populates="images")


class InferredDogBreed(Base):
    """Breed values inferred for a dog by various methods.

    One row per (dog, method). Holds candidates from image classification,
    text LLM, clustering, and any future methods. The primary breed for
    display is selected from these rows by the API/enrichment layer; the
    `dogs.breed_en` column is *translation-only* and never written from
    inference.
    """

    __tablename__ = "inferred_dog_breeds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dog_id = Column(Integer, ForeignKey("dogs.id", ondelete="CASCADE"), nullable=False)
    method = Column(String, nullable=False)         # 'image' | 'text_llm' | 'clustering' | ...
    value = Column(String, ForeignKey("breeds.name"), nullable=False)
    model_name = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    dog = relationship("Dog", back_populates="inferred_breeds")

    __table_args__ = (
        UniqueConstraint("dog_id", "method"),
    )
