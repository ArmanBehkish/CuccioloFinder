"""Stable identity for dog records.

`dog_uid` is the long-term unique identifier for a row. It is derived from
(source_site, source_url, generation) so that re-scrapes of the same
listing always produce the same UID, while a URL recycled to a different
physical dog produces a fresh UID via a generation bump.
"""

import hashlib
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Dog, DogImage


@dataclass(frozen=True)
class Identity:
    dog_uid: str
    generation: int
    supersede_id: int | None  # id of the row to mark superseded, if any


def compute_dog_uid(source_site: str, source_url: str, generation: int) -> str:
    """sha256(site|url|generation), truncated to 16 hex chars."""
    payload = f"{source_site}|{source_url}|{generation}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def resolve_dog_identity(
    session: Session,
    source_site: str,
    source_url: str,
    image_urls: list[str],
) -> Identity:
    """Decide what UID + generation a freshly-scraped item should carry.

    - No active row at this URL -> fresh dog, generation=1.
    - Active row exists, image URL set overlaps -> same physical dog,
      reuse existing UID/generation.
    - Active row exists, image URL set disjoint -> URL recycled to a new
      dog; bump generation and flag the existing row for supersession.
    """
    existing = (
        session.query(Dog)
        .filter_by(
            source_site=source_site,
            source_url=source_url,
            superseded_at=None,
        )
        .first()
    )

    if existing is None:
        return Identity(
            dog_uid=compute_dog_uid(source_site, source_url, 1),
            generation=1,
            supersede_id=None,
        )

    existing_image_urls = {
        img.url
        for img in session.query(DogImage).filter_by(dog_id=existing.id).all()
    }
    new_image_urls = set(image_urls or [])

    if existing_image_urls & new_image_urls:
        return Identity(
            dog_uid=existing.dog_uid,
            generation=existing.generation,
            supersede_id=None,
        )

    next_gen = existing.generation + 1
    return Identity(
        dog_uid=compute_dog_uid(source_site, source_url, next_gen),
        generation=next_gen,
        supersede_id=existing.id,
    )
