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
from .breed.profile_builder import (
    DEMEANOR_LABELS,
    ENERGY_LABELS,
    TEMPERAMENT_META,
    TRAINABILITY_LABELS,
)
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

    `max_tokens`: enums and short strings finish in well under 200 tokens,
    so a tight cap discourages the model from rambling. List fields like
    temperament need more headroom for the JSON array PLUS the chatty
    "show your work" prose remote Llama tends to emit before the final
    clean object — bumped to 400 for those.
    """
    kwargs = dict(
        field_name=field_name,
        value_type=value_type,
        allowed_values=allowed_values,
        field_description=field_description,
    )
    remote_max_tokens = 400 if value_type == "list" else 200

    if backend == "groq":
        try:
            return groq_extract_field(
                description_en, max_tokens=remote_max_tokens, **kwargs
            )
        except GroqError as exc:
            if get_fallback_enabled():
                logger.warning(
                    f"Groq extraction for {field_name} failed, falling back to Mistral: {exc}"
                )
                return mistral_extract_field(description_en, **kwargs)
            raise
    if backend == "openrouter":
        try:
            return openrouter_extract_field(
                description_en, max_tokens=remote_max_tokens, **kwargs
            )
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


# ---------------------------------------------------------------------------
# Behavior extraction for cat_similarity
# ---------------------------------------------------------------------------
#
# Four dimensions (energy_level, trainability, demeanor, temperament) used
# as inputs to the categorical-similarity breed inference. One LLM call per
# dimension per dog — kept separate (not combined) so each prompt can be
# tuned independently as we observe results. Input to every call is the
# description plus the shelter's structured compatibility lists (good_with_en,
# bad_with_en); description-derived `*_from_desc` lists are NOT included
# (they're already extracted FROM the description, would be redundant).

# (column, value_type, allowed_values, field_description)
_BEHAVIOR_FIELDS: list[tuple[str, str, list[str], str]] = [
    (
        "energy_level_from_desc", "enum", ENERGY_LABELS,
        "the dog's overall activity / energy level. Read both explicit "
        "statements ('high-energy', 'lazy') and indirect cues "
        "(needs long walks; loves to run; prefers lounging).",
    ),
    (
        "trainability_from_desc", "enum", TRAINABILITY_LABELS,
        "the dog's trainability disposition. Read explicit cues ('easy "
        "to train', 'stubborn') and behavioral hints (already knows "
        "commands; eager to learn; ignores instructions).",
    ),
    (
        "demeanor_from_desc", "enum", DEMEANOR_LABELS,
        "the dog's social demeanor toward people. Read tone and "
        "behavioral cues — friendly with everyone, watchful and alert, "
        "slow to warm up to strangers, etc.",
    ),
    (
        "temperament_from_desc", "list", TEMPERAMENT_META,
        "the dog's temperament traits. Pick 1 to 3 most fitting tags "
        "from the allowed list (verbatim), or empty list if no clear "
        "signal. Read tone and described behaviors.",
    ),
]


def _build_behavior_input(
    description_en: str,
    good_with_en: list[str] | None,
    bad_with_en: list[str] | None,
) -> str:
    """Combine description + structured compatibility info into one text."""
    parts = [f"Description:\n{description_en.strip()}"]
    if good_with_en:
        parts.append(f"Lives well with: {', '.join(good_with_en)}")
    if bad_with_en:
        parts.append(f"Does not live well with: {', '.join(bad_with_en)}")
    return "\n\n".join(parts)


def enrich_behavior_from_desc(session: Session, limit: int | None = None) -> int:
    """Populate the four behavior `*_from_desc` columns via per-dimension LLM calls.

    Returns the number of dogs that received at least one extracted field.
    Same NULL-gate semantics as `enrich_from_desc`: skips columns that
    already have a value (including the "" / [] sentinels).
    """
    backend = get_extract_backend()
    logger.info(f"Behavior extraction backend: {backend}")

    query = (
        session.query(Dog)
        .filter(Dog.superseded_at.is_(None))
        .filter(Dog.description_en.isnot(None))
        .filter(Dog.description_en != "")
    )
    if limit:
        query = query.limit(limit)
    dogs = query.all()
    logger.info(f"Behavior extraction: {len(dogs)} candidate dogs")

    processed = 0
    for dog in dogs:
        wrote_any = False
        combined_input: str | None = None

        for column, value_type, allowed, field_desc in _BEHAVIOR_FIELDS:
            if getattr(dog, column, None) is not None:
                continue

            if combined_input is None:
                combined_input = _build_behavior_input(
                    dog.description_en, dog.good_with_en, dog.bad_with_en
                )

            try:
                value = _extract_field(
                    combined_input,
                    field_name=column.removesuffix("_from_desc"),
                    value_type=value_type,
                    allowed_values=allowed,
                    field_description=field_desc,
                    backend=backend,
                )
            except (GroqError, OpenRouterError, MistralError, ExtractionUnavailable) as exc:
                logger.warning(f"[{dog.name}] behavior extract {column} failed: {exc}")
                continue

            if value is None:
                # Sentinel: [] for the temperament list, "" for the three scalars.
                setattr(dog, column, [] if value_type == "list" else "")
                wrote_any = True
                continue

            setattr(dog, column, value)
            wrote_any = True
            logger.info(f"[{dog.name}] {column} = {value!r}")

        if wrote_any:
            processed += 1

    session.commit()
    logger.info(f"Behavior extraction complete. Processed {processed} dogs.")
    return processed
