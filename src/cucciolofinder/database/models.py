from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Dog(Base):
    __tablename__ = "dogs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_site = Column(String, nullable=False)
    source_url = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)

    description = Column(Text)
    description_en = Column(Text)
    gender = Column(String)
    gender_en = Column(String)
    age = Column(String)
    age_en = Column(String)
    weight = Column(String)     # e.g., "30kg" or similar
    size = Column(String)
    size_en = Column(String)
    breed = Column(String)
    breed_en = Column(String)
    fur = Column(String)
    fur_en = Column(String)
    microchip = Column(String)
    microchip_en = Column(String)
    sterilization = Column(String)
    sterilization_en = Column(String)
    vaccine = Column(String)
    vaccine_en = Column(String)
    deworming = Column(String)
    deworming_en = Column(String)

    post_date = Column(Date)
    shelter_since = Column(String)      # may contain Italian date e.g, "7 Aprile 2021"

    good_with = Column(JSON)            # list
    good_with_en = Column(JSON)
    bad_with = Column(JSON)
    bad_with_en = Column(JSON)

    scraped_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    images = relationship("DogImage", back_populates="dog", cascade="all, delete-orphan")
    provenance = relationship(
        "FieldProvenance", back_populates="dog", cascade="all, delete-orphan"
    )


class DogImage(Base):
    __tablename__ = "dog_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dog_id = Column(Integer, ForeignKey("dogs.id", ondelete="CASCADE"), nullable=False)
    url = Column(String, nullable=False)
    local_path = Column(String)     # relative /data/images
    position = Column(Integer)      # keep order

    dog = relationship("Dog", back_populates="images")


class FieldProvenance(Base):
    __tablename__ = "field_provenance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dog_id = Column(Integer, ForeignKey("dogs.id", ondelete="CASCADE"), nullable=False)
    field_name = Column(String, nullable=False)
    method = Column(String, nullable=False)
    model_name = Column(String)
    confidence = Column(Float)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    dog = relationship("Dog", back_populates="provenance")

    __table_args__ = (
        UniqueConstraint("dog_id", "field_name", "method"),
    )
