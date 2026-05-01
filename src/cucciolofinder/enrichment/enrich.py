from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.database import Dog

from .backends import get_fallback_enabled, get_translation_backend
from .groq_client import GroqError, groq_extract_field
from .mistral_client import MistralError, mistral_extract_field
from .translator import TranslationService

# Fields that get translated (with _en counterparts)
SIMPLE_FIELDS = ["gender", "size", "fur", "microchip", "sterilization", "vaccine", "deworming"]
LIST_FIELDS = ["good_with", "bad_with"]
COMPLEX_FIELDS = ["description", "age"]

# Breed translation: the shelter's structured `breed` field is short, free-form
# (Italian or English, sometimes mixed-language). We send it through an LLM so
# the output is a normalized English phrase — but liberal: "mixed", "Labrador
# mix", "shepherd-type" are all fine. No FK to the canonical AKC catalogue
# (that lives in `inferred_dog_breeds`); shelter inputs rarely line up with it.
_BREED_FIELD_DESCRIPTION = (
    "the dog's breed as a SHORT free-form descriptive phrase. "
    "It does NOT need to match any canonical breed list — accept "
    "'mixed', 'Labrador mix', 'shepherd-type', 'pit bull mix', a "
    "single canonical name, etc. Use null only when the input "
    "gives no breed signal at all."
)


def _translate_breed(raw_breed: str) -> str | None:
    """Translate a raw shelter `breed` value to a free-form English phrase.

    Backend-agnostic: dispatches on `TRANSLATION_BACKEND` and falls back
    to Mistral on Groq failure when `GROQ_FALLBACK_TO_MISTRAL=1` (default).
    Returns None if the LLM has no signal or all backends fail.
    """
    backend = get_translation_backend()
    kwargs = dict(
        field_name="breed",
        value_type="string",
        allowed_values=None,
        field_description=_BREED_FIELD_DESCRIPTION,
    )
    if backend == "groq":
        try:
            return groq_extract_field(raw_breed, **kwargs)
        except GroqError as exc:
            if get_fallback_enabled():
                logger.warning(f"Groq breed translation failed, falling back to Mistral: {exc}")
                return mistral_extract_field(raw_breed, **kwargs)
            raise
    if backend == "mistral":
        return mistral_extract_field(raw_breed, **kwargs)
    raise NotImplementedError(f"Translation backend '{backend}' not implemented for breed")

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

        # Breed: liberal LLM translation (no FK to AKC catalogue).
        if dog.breed and dog.breed_en is None:
            try:
                translated_breed = _translate_breed(dog.breed)
            except (GroqError, MistralError) as exc:
                logger.warning(f"[{dog.name}] breed translation failed: {exc}")
                translated_breed = None
            if translated_breed:
                dog.breed_en = translated_breed
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
