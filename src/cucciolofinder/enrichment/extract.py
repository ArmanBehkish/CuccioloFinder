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
`EXTRACT_BACKEND` (default `mistral`). `groq` (direct SDK), `openrouter`
(direct SDK against an OpenAI-compatible endpoint), and `mistral`
(worker→API HTTP hop, llama-cpp on the other side) are wired. Add new
providers by extending the dispatch table — the call sites do not change.
"""

from datetime import date

from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.database import Dog

from .backends import get_extract_backend, get_fallback_enabled
from .groq_client import GroqError, groq_extract_field, groq_extract_good_bad_with
from .mistral_client import (
    MistralError,
    mistral_extract_field,
    mistral_extract_good_bad_with,
)
from .openrouter_client import (
    OpenRouterError,
    openrouter_extract_field,
    openrouter_extract_good_bad_with,
)

# (column, value_type, allowed_values, field_description)
# `age_from_desc` carries today's date so the LLM can resolve DOB phrases —
# build the list per run via `_build_extraction_fields(today)`.
def _build_extraction_fields(today: date) -> list[tuple[str, str, list[str] | None, str]]:
    return [
    (
        "gender_from_desc", "enum",
        ["male", "female"],
        "the dog's gender",
    ),
    (
        "age_from_desc", "string",
        None,
        "the dog's age. Output a short free-form phrase like '3 years', "
        "'6 months', '3.5 years', '2 weeks'. "
        "If the description gives a date of birth instead of an age "
        "(e.g. 'DOB 01/01/22', 'born in 2021', 'date of birth: March 2023', "
        "'born approximately at the beginning of November 2024'), "
        f"compute the dog's age from it relative to today ({today.isoformat()}) "
        "and output the computed age (e.g. '4 years', '6 months'). "
        "If only a year is given, assume mid-year. Two-digit years (e.g. '22') "
        "refer to the 2000s. Use null only when the description gives "
        "neither an age nor a date of birth.",
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
        "the dog's breed — a recognizable breed name or a short "
        "breed-typed phrase. A breed refers to ancestry/lineage, NOT "
        "appearance or character. "
        "Accept: a canonical name ('Labrador Retriever', 'Beagle'), "
        "a mix phrase ('Labrador mix', 'shepherd-type', 'pit bull mix'), "
        "or 'mixed' / 'mixed-breed' for unknown ancestry. "
        "Return null for: pure size adjectives ('large', 'small', 'tiny', "
        "'medium-sized'), coat or appearance adjectives ('fluffy', 'soft', "
        "'all fluff and softness', 'short-haired'), color words, "
        "temperament words ('friendly', 'energetic'), and any "
        "poetic/metaphorical phrase that doesn't name a breed type "
        "(e.g. 'ball of joy', 'a true gentleman'). "
        "If the description only describes the dog's looks or character "
        "without mentioning ancestry, return null.",
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
    # good_with_from_desc + bad_with_from_desc are extracted together via
    # `_extract_good_bad_with` (single LLM call, mutually exclusive lists).
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

    On a remote path (Groq or OpenRouter), if the call raises and
    `REMOTE_FALLBACK_TO_MISTRAL=1` (default), fall through to the Mistral
    HTTP path. The API endpoint lazy-loads Mistral on first call, so this
    works even when both backends are otherwise configured for a remote.
    """
    kwargs = dict(
        field_name=field_name,
        value_type=value_type,
        allowed_values=allowed_values,
        field_description=field_description,
    )
    if backend == "groq":
        try:
            return groq_extract_field(description_en, **kwargs)
        except GroqError as exc:
            if get_fallback_enabled():
                logger.warning(
                    f"Groq extraction for {field_name} failed, falling back to Mistral: {exc}"
                )
                return mistral_extract_field(description_en, **kwargs)
            raise
    if backend == "openrouter":
        try:
            return openrouter_extract_field(description_en, **kwargs)
        except OpenRouterError as exc:
            if get_fallback_enabled():
                logger.warning(
                    f"OpenRouter extraction for {field_name} failed, falling back to Mistral: {exc}"
                )
                return mistral_extract_field(description_en, **kwargs)
            raise
    if backend == "mistral":
        return mistral_extract_field(description_en, **kwargs)
    raise NotImplementedError(
        f"Extraction backend '{backend}' is not implemented. "
        f"Implement a client wrapper and add a branch in _extract_field."
    )


def _extract_good_bad_with(
    description_en: str,
    backend: str,
) -> tuple[list[str], list[str]]:
    """Combined good_with + bad_with dispatcher.

    Mirrors `_extract_field`'s backend dispatch and remote → Mistral
    fallback semantics, but for the joint extraction of both
    compatibility lists in one LLM call.
    """
    if backend == "groq":
        try:
            return groq_extract_good_bad_with(description_en)
        except GroqError as exc:
            if get_fallback_enabled():
                logger.warning(
                    f"Groq good/bad_with failed, falling back to Mistral: {exc}"
                )
                return mistral_extract_good_bad_with(description_en)
            raise
    if backend == "openrouter":
        try:
            return openrouter_extract_good_bad_with(description_en)
        except OpenRouterError as exc:
            if get_fallback_enabled():
                logger.warning(
                    f"OpenRouter good/bad_with failed, falling back to Mistral: {exc}"
                )
                return mistral_extract_good_bad_with(description_en)
            raise
    if backend == "mistral":
        return mistral_extract_good_bad_with(description_en)
    raise NotImplementedError(
        f"Extraction backend '{backend}' is not implemented for good/bad_with."
    )


def enrich_from_desc(session: Session, limit: int | None = None) -> int:
    """Populate *_from_desc columns from description_en via LLM extraction.

    Returns the number of dogs that received at least one extracted field.
    """
    backend = get_extract_backend()
    logger.info(f"Description extraction backend: {backend}")

    fields = _build_extraction_fields(date.today())

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
        for column, value_type, allowed, field_desc in fields:
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
            except (GroqError, OpenRouterError, MistralError, ExtractionUnavailable) as exc:
                # Transient failure: leave column NULL so next run retries.
                logger.warning(f"[{dog.name}] extract {column} failed: {exc}")
                continue

            # Successful call. None == "no signal" — write the empty-string
            # sentinel so the gate above (`is not None`) skips this column on
            # subsequent runs and we don't pay the LLM call again. NULL is
            # reserved for "never tried OR was just invalidated" (the
            # DatabasePipeline clears columns to NULL when description
            # changes, which correctly retriggers extraction).
            if value is None:
                setattr(dog, column, "")
                wrote_any = True
                continue

            setattr(dog, column, value)
            wrote_any = True
            logger.info(f"[{dog.name}] {column} = {value!r}")

        # Combined good_with + bad_with extraction (single call, mutually
        # exclusive). Skip if both columns are already populated; if only
        # one is None, still call so the dog gets symmetric coverage.
        if dog.good_with_from_desc is None or dog.bad_with_from_desc is None:
            call_failed = False
            try:
                good, bad = _extract_good_bad_with(dog.description_en, backend)
            except (GroqError, OpenRouterError, MistralError, ExtractionUnavailable) as exc:
                # Transient failure: leave both columns NULL for retry.
                logger.warning(f"[{dog.name}] good/bad_with extraction failed: {exc}")
                call_failed = True

            if not call_failed:
                # Empty list `[]` is the success-with-no-signal sentinel,
                # symmetric to `""` for scalars.
                if dog.good_with_from_desc is None:
                    dog.good_with_from_desc = good
                    wrote_any = True
                    logger.info(f"[{dog.name}] good_with_from_desc = {good!r}")
                if dog.bad_with_from_desc is None:
                    dog.bad_with_from_desc = bad
                    wrote_any = True
                    logger.info(f"[{dog.name}] bad_with_from_desc = {bad!r}")

        if wrote_any:
            processed += 1

    session.commit()
    logger.info(f"Description extraction complete. Processed {processed} dogs.")
    return processed
