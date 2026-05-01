"""Text-embedding breed inference sub-pipeline.

Wraps `breed_embedding` + `profile_builder`. For each dog with enough
text fields to build a profile, embeds the profile and finds the closest
AKC breed by cosine similarity. Writes one row per dog:

  - `method='text_embedding'` → (value, similarity)

This pipeline preserves the current behavior of the legacy
`enrich_breed_detection` text branch. Known accuracy issues
(template-dominated similarity, brittle missing-field gate) are tracked
separately and addressed in a follow-up.
"""

from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.database import Dog

from ..normalizers import normalize_fur, normalize_size, normalize_weight
from .breed_embedding import (
    DEFAULT_EMBED_MODEL,
    build_akc_index,
    embed_texts,
    find_closest_breeds,
    load_embedding_model,
)
from .profile_builder import (
    build_profile_text,
    classify_behavior,
    load_classifier,
)


def run(session: Session) -> int:
    """Run text-embedding breed inference for every active dog. Returns rows written."""
    from .dispatcher import upsert_inferred_breed

    logger.info("Loading zero-shot classifier...")
    zsc = load_classifier()

    logger.info("Loading embedding model...")
    tokenizer, embed_model = load_embedding_model()

    logger.info("Building AKC breed index...")
    breed_names, akc_embeddings = build_akc_index(tokenizer, embed_model)

    dogs = session.query(Dog).filter(Dog.superseded_at.is_(None)).all()
    logger.info(f"Text-embedding pipeline: processing {len(dogs)} dogs")

    rows_written = 0
    for dog in dogs:
        size = normalize_size(dog.size_en) or normalize_size(dog.size)
        fur = normalize_fur(dog.fur_en) or normalize_fur(dog.fur)
        weight = normalize_weight(dog.weight)

        behavior = classify_behavior(
            dog.description_en, dog.good_with_en, dog.bad_with_en, zsc
        )
        energy = behavior["energy_level"]
        train = behavior["trainability"]
        demeanor = behavior["demeanor"]
        temperament = behavior["temperament"]

        if not all([size, fur, weight, energy, train, demeanor, temperament]):
            logger.debug(f"[{dog.name}] text_embedding: insufficient fields, skipping")
            continue

        profile = build_profile_text(
            size=size, fur=fur, weight=weight,
            energy_level=energy, trainability=train,
            demeanor=demeanor, temperament=temperament,
        )
        dog_emb = embed_texts([profile], tokenizer, embed_model)[0]
        candidates = find_closest_breeds(dog_emb, akc_embeddings, breed_names, top_k=1)
        if not candidates:
            continue

        value, sim = candidates[0]
        upsert_inferred_breed(
            session,
            dog_id=dog.id,
            method="text_embedding",
            value=value,
            model_name=DEFAULT_EMBED_MODEL,
            confidence=float(sim),
        )
        rows_written += 1
        logger.info(f"[{dog.name}] text_embedding: {value} ({sim:.3f})")

    return rows_written
