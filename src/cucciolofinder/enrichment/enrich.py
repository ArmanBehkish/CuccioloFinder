from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.database import Dog, FieldProvenance

from .translator import TranslationService

# Fields that get translated (with _en counterparts)
SIMPLE_FIELDS = ["gender", "size", "fur", "microchip", "sterilization", "vaccine", "deworming"]
LIST_FIELDS = ["good_with", "bad_with"]
COMPLEX_FIELDS = ["description", "age"]

def enrich_translations(session: Session, limit: int | None = None) -> int:
    """
    Translate Italian fields to English for dogs with NULL _en fields.

    Args:
        session: SQLAlchemy session
        limit: Max number of dogs to process (None = all)

    Returns the number of dogs processed.
    """
    translator = TranslationService()
    processed_count = 0

    query = session.query(Dog)
    if limit:
        query = query.limit(limit)
    dogs = query.all()

    for dog in dogs:
        updated = False

        # Simple fields: use static mapping (with model fallback)
        for field in SIMPLE_FIELDS:
            en_field = f"{field}_en"
            italian_value = getattr(dog, field, None)
            english_value = getattr(dog, en_field, None)

            if italian_value and english_value is None:
                translated = translator.translate_field(italian_value)
                if translated:
                    setattr(dog, en_field, translated)
                    updated = True
                    # logger.debug(f"[{dog.name}] {field} Translation: IT: ' {italian_value}' → EN: '{translated}'")

        # List fields: translate each item
        for field in LIST_FIELDS:
            en_field = f"{field}_en"
            italian_list = getattr(dog, field, None)
            english_list = getattr(dog, en_field, None)

            if italian_list and english_list is None:
                translated_list = translator.translate_list(italian_list)
                if translated_list:
                    setattr(dog, en_field, translated_list)
                    updated = True
                    # logger.debug(f"[{dog.name}] {field} Translation: IT: {italian_list} → EN: {translated_list}")

        # Complex fields: use translation model
        for field in COMPLEX_FIELDS:
            en_field = f"{field}_en"
            italian_value = getattr(dog, field, None)
            english_value = getattr(dog, en_field, None)

            if italian_value and english_value is None:
                try:
                    if field == "description":
                        # logger.debug(f"TRASNLATING DESCRIPTION: {italian_value}")
                        translated = translator.translate_description(italian_value)
                    else:
                        # age — try static map first, then model
                        translated = translator.translate_field(italian_value)

                    if translated:
                        setattr(dog, en_field, translated)
                        updated = True
                        # logger.debug(f"[{dog.name}] {field}: '{italian_value[:50]}...' → '{translated[:50]}...'")

                        # Record provenance for model-translated fields
                        _upsert_provenance(
                            session,
                            dog_id=dog.id,
                            field_name=en_field,
                            method="llm",
                            model_name=translator.model_name,
                        )
                except Exception as e:
                    logger.warning(f"[{dog.name}] Failed to translate {field}: {e}")

        if updated:
            processed_count += 1
            logger.info(f"Enriched translations for dog '{dog.name}' (id={dog.id})")

    session.commit()
    logger.info(f"Translation enrichment complete. Processed {processed_count} dogs.")
    return processed_count


def _upsert_provenance(
    session: Session,
    dog_id: int,
    field_name: str,
    method: str,
    model_name: str | None = None,
    confidence: float | None = None,
) -> None:
    """Insert or update a provenance record for a field."""
    existing = (
        session.query(FieldProvenance)
        .filter_by(dog_id=dog_id, field_name=field_name, method=method)
        .first()
    )

    if existing:
        existing.model_name = model_name
        existing.confidence = confidence
    else:
        session.add(
            FieldProvenance(
                dog_id=dog_id,
                field_name=field_name,
                method=method,
                model_name=model_name,
                confidence=confidence,
            )
        )
