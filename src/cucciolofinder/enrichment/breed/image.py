"""Image-based breed inference sub-pipeline.

Wraps `cucciolofinder.enrichment.breed.image_classifier`. For each dog
with at least one image, runs the ViT classifier across all images,
resolves the top-2 ViT labels to canonical AKC names via
`vit_to_akc.json`, and writes two rows to `inferred_dog_breeds`:

  - `method='image'`     → top-1 (value, confidence)
  - `method='image_2nd'` → top-2 (value, confidence)

If only one valid candidate is returned, only the `'image'` row is written.
"""

import json
import os
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.database import Breed, Dog

from .image_classifier import (
    DEFAULT_IMAGE_MODEL,
    classify_breed,
    load_image_classifier,
)

IMAGES_DIR = Path(os.environ.get("IMAGES_PATH", "data/images"))
VIT_TO_AKC_JSON = Path(os.environ.get("VIT_TO_AKC_PATH", "data/datasets/vit_to_akc.json"))


def run(session: Session) -> int:
    """Run image classification for every active dog, write rows. Returns rows written."""
    from .dispatcher import upsert_inferred_breed

    vit_to_akc: dict[str, str] = {}
    if VIT_TO_AKC_JSON.exists():
        with open(VIT_TO_AKC_JSON, encoding="utf-8") as fh:
            vit_to_akc = json.load(fh)
    valid_vit_labels = set(vit_to_akc.keys())
    valid_breeds = {b.name for b in session.query(Breed).all()}
    logger.info(
        f"Image pipeline: {len(vit_to_akc)} ViT mappings, {len(valid_breeds)} valid breeds"
    )

    logger.info("Loading image classifier...")
    processor, img_model, _ = load_image_classifier()

    dogs = session.query(Dog).filter(Dog.superseded_at.is_(None)).all()
    logger.info(f"Image pipeline: processing {len(dogs)} dogs")

    rows_written = 0
    for dog in dogs:
        image_paths = [IMAGES_DIR / img.local_path for img in dog.images if img.local_path]
        if not image_paths:
            continue

        raw = classify_breed(image_paths, processor, img_model, valid_vit_labels)
        if not raw:
            continue

        # Resolve ViT labels → canonical AKC names; drop any without a mapping.
        canonical_pairs: list[tuple[str, float]] = []
        for label, prob in raw:
            canonical = vit_to_akc.get(label)
            if canonical and canonical in valid_breeds:
                canonical_pairs.append((canonical, prob))

        if not canonical_pairs:
            logger.debug(f"[{dog.name}] image: no mapping for ViT labels {[l for l, _ in raw]}")
            continue

        top_value, top_conf = canonical_pairs[0]
        upsert_inferred_breed(
            session,
            dog_id=dog.id,
            method="image",
            value=top_value,
            model_name=DEFAULT_IMAGE_MODEL,
            confidence=top_conf,
        )
        rows_written += 1
        logger.info(f"[{dog.name}] image: {top_value} ({top_conf:.2f})")

        if len(canonical_pairs) > 1:
            second_value, second_conf = canonical_pairs[1]
            upsert_inferred_breed(
                session,
                dog_id=dog.id,
                method="image_2nd",
                value=second_value,
                model_name=DEFAULT_IMAGE_MODEL,
                confidence=second_conf,
            )
            rows_written += 1
            logger.info(f"[{dog.name}] image_2nd: {second_value} ({second_conf:.2f})")

    return rows_written
