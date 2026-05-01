"""Stage 2: extract `*_from_desc` fields from the English description.

Runs after Stage 1 (translation). For each active dog with a non-empty
`description_en`, fills any `<field>_from_desc` column that is currently
NULL. The structured-translation counterpart (`<field>_en` / `<field>`)
is NOT used as a gate — the two values are independent signals; display
preference (e.g. "show `_en`, fall back to `_from_desc`") happens at the
API/frontend layer.

One LLM call per field per dog (user choice — isolates a bad response to
a single column).

Backend-agnostic: routes through `_extract_field`, which dispatches on
`EXTRACT_BACKEND` (default `mistral`). Both `groq` (direct SDK call) and
`mistral` (worker→API HTTP hop, llama-cpp on the other side) are wired.
Add new providers by extending the dispatch table — the call sites do
not change.
"""

from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.database import Dog

from .backends import get_extract_backend, get_fallback_enabled
from .groq_client import GroqError, groq_extract_field
from .mistral_client import MistralError, mistral_extract_field

# (column, value_type, allowed_values, field_description)
_EXTRACTION_FIELDS: list[tuple[str, str, list[str] | None, str]] = [
    (
        "gender_from_desc", "enum",
        ["male", "female"],
        "the dog's gender",
    ),
    (
        "age_from_desc", "string",
        None,
        "the dog's age (free-form short phrase, e.g. '3 years', 'puppy', 'senior')",
    ),
    (
        "weight_from_desc", "string",
        None,
        "the dog's weight including units (e.g. '30kg', '12 kg'). "
        "If the description distinguishes current weight from adult / "
        "fully-grown weight (e.g. for a puppy), use the ADULT weight.",
    ),
    (
        "size_from_desc", "enum",
        ["small", "medium", "large", "giant"],
        "the dog's body size category. "
        "If the description distinguishes current size from adult / "
        "fully-grown size (e.g. 'currently small but will be large when "
        "fully grown'), use the ADULT size — adopters filter for the "
        "long-term dog, not the puppy stage.",
    ),
    (
        "breed_from_desc", "string",
        None,
        "the dog's breed as a SHORT free-form descriptive phrase. "
        "It does NOT need to match any canonical breed list — accept "
        "'mixed', 'Labrador mix', 'shepherd-type', 'pit bull mix', a "
        "single canonical name, etc. Use null only when the description "
        "gives no breed signal at all.",
    ),
    (
        "fur_from_desc", "enum",
        ["short", "medium", "long"],
        "the dog's fur length",
    ),
    (
        "microchip_from_desc", "enum",
        ["yes", "no"],
        "whether the dog has a microchip",
    ),
    (
        "sterilization_from_desc", "enum",
        ["yes", "no"],
        "whether the dog is sterilized / neutered / spayed",
    ),
    (
        "vaccine_from_desc", "enum",
        ["yes", "no"],
        "whether the dog is vaccinated",
    ),
    (
        "deworming_from_desc", "enum",
        ["yes", "no"],
        "whether the dog is dewormed",
    ),
    (
        "good_with_from_desc", "list",
        None,
        "things or beings the dog gets along well with "
        "(short tags like 'children', 'other dogs', 'cats')",
    ),
    (
        "bad_with_from_desc", "list",
        None,
        "things or beings the dog does NOT get along with "
        "(short tags like 'children', 'other dogs', 'cats')",
    ),
]


class ExtractionUnavailable(RuntimeError):
    """Raised when the configured backend is not available for extraction."""


def _extract_field(
    description_en: str,
    field_name: str,
    *,
    value_type: str,
    allowed_values: list[str] | None,
    field_description: str,
    backend: str,
) -> str | list[str] | None:
    """Backend dispatcher for a single field extraction call.

    On the Groq path, if Groq raises and `GROQ_FALLBACK_TO_MISTRAL=1`
    (default), fall through to the Mistral HTTP path. The API endpoint
    lazy-loads Mistral on first call, so this works even when both
    backends are otherwise configured for Groq.
    """
    if backend == "groq":
        try:
            return groq_extract_field(
                description_en,
                field_name=field_name,
                value_type=value_type,
                allowed_values=allowed_values,
                field_description=field_description,
            )
        except GroqError as exc:
            if get_fallback_enabled():
                logger.warning(
                    f"Groq extraction for {field_name} failed, falling back to Mistral: {exc}"
                )
                return mistral_extract_field(
                    description_en,
                    field_name=field_name,
                    value_type=value_type,
                    allowed_values=allowed_values,
                    field_description=field_description,
                )
            raise
    if backend == "mistral":
        return mistral_extract_field(
            description_en,
            field_name=field_name,
            value_type=value_type,
            allowed_values=allowed_values,
            field_description=field_description,
        )
    raise NotImplementedError(
        f"Extraction backend '{backend}' is not implemented. "
        f"Implement a client wrapper and add a branch in _extract_field."
    )


def enrich_from_desc(session: Session, limit: int | None = None) -> int:
    """Populate *_from_desc columns from description_en via LLM extraction.

    Returns the number of dogs that received at least one extracted field.
    """
    backend = get_extract_backend()
    logger.info(f"Description extraction backend: {backend}")

    query = (
        session.query(Dog)
        .filter(Dog.superseded_at.is_(None))
        .filter(Dog.description_en.isnot(None))
        .filter(Dog.description_en != "")
    )
    if limit:
        query = query.limit(limit)
    dogs = query.all()
    logger.info(f"Description extraction: {len(dogs)} candidate dogs")

    processed = 0
    for dog in dogs:
        wrote_any = False
        for column, value_type, allowed, field_desc in _EXTRACTION_FIELDS:
            if getattr(dog, column, None) is not None:
                continue  # already extracted

            try:
                value = _extract_field(
                    dog.description_en,
                    field_name=column.removesuffix("_from_desc"),
                    value_type=value_type,
                    allowed_values=allowed,
                    field_description=field_desc,
                    backend=backend,
                )
            except (GroqError, MistralError, ExtractionUnavailable) as exc:
                logger.warning(f"[{dog.name}] extract {column} failed: {exc}")
                continue

            if value is None:
                continue
            if value_type == "list" and not value:
                continue

            setattr(dog, column, value)
            wrote_any = True
            logger.info(f"[{dog.name}] {column} = {value!r}")

        if wrote_any:
            processed += 1

    session.commit()
    logger.info(f"Description extraction complete. Processed {processed} dogs.")
    return processed
