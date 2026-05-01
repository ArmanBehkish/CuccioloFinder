from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.database import Dog

from .translator import TranslationService

# Fields that get translated (with _en counterparts)
SIMPLE_FIELDS = ["gender", "size", "fur", "microchip", "sterilization", "vaccine", "deworming"]
LIST_FIELDS = ["good_with", "bad_with"]
COMPLEX_FIELDS = ["description", "age"]

# Medical fields: normalize any positive/negative value to yes/no
MEDICAL_FIELDS = {"microchip", "sterilization", "vaccine", "deworming"}
_MEDICAL_YES = {"yes", "si", "sì", "microchipped", "sterilized", "vaccinated", "dewormed",
                "dotato di microchip", "sterilizzato", "vaccinato", "sverminato"}
_MEDICAL_NO = {"no", "not sterilized", "non sterilizzato"}

def _normalize_medical(value: str) -> str:
    v = value.strip().lower()
    if v in _MEDICAL_YES:
        return "yes"
    if v in _MEDICAL_NO:
        return "no"
    return v

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

    query = session.query(Dog).filter(Dog.superseded_at.is_(None))
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
                    value = _normalize_medical(translated) if field in MEDICAL_FIELDS else translated.lower()
                    setattr(dog, en_field, value)
                    updated = True

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

        # Complex fields: use translation model
        for field in COMPLEX_FIELDS:
            en_field = f"{field}_en"
            italian_value = getattr(dog, field, None)
            english_value = getattr(dog, en_field, None)

            if italian_value and english_value is None:
                try:
                    if field == "description":
                        translated = translator.translate_description(italian_value)
                    else:
                        # age — try static map first, then model
                        translated = translator.translate_field(italian_value)

                    if translated:
                        setattr(dog, en_field, translated)
                        updated = True
                except Exception as e:
                    logger.warning(f"[{dog.name}] Failed to translate {field}: {e}")

        if updated:
            processed_count += 1
            logger.info(f"Enriched translations for dog '{dog.name}' (id={dog.id})")

    session.commit()
    logger.info(f"Translation enrichment complete. Processed {processed_count} dogs.")
    return processed_count
