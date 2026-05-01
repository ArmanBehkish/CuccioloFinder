import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datetime import date
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import Engine, text

from .database.db import DEFAULT_DB_PATH, get_engine, get_session
from .database.models import DogImage
from .enrichment.backends import (
    BackendConfigError,
    any_backend_uses_groq,
    any_backend_uses_mistral,
    get_fallback_enabled,
    get_search_backend,
    get_translation_backend,
    validate_backend_config,
)

# Mistral 7B Instruct GGUF (4-bit quantized ~4.4GB)
SEARCH_MODEL_PATH = os.environ.get(
    "SEARCH_MODEL_PATH",
    "data/models/mistral-7b-instruct-v0.3.Q4_K_M.gguf",
)

#### App state

WORKER_BUSY_TIMEOUT = 3 * 3600  # auto-clear after 3 hours
WORKER_STATUS_FILE = Path(os.environ.get("WORKER_STATUS_FILE", "data/.worker_busy"))


@dataclass
class AppState:
    db_ok: bool = False
    search_model_ok: bool = False
    engine: Engine | None = None         # db engine
    search_model: Any = None             # loaded model
    enums_cache: dict = field(default_factory=dict)
    stats_cache: dict = field(default_factory=dict)


_state = AppState()

##### Startup / shutdown

def _reconnect_db() -> bool:
    """Dispose old engine, create a fresh one, verify tables are reachable.

    Called by _probe_db at startup and by endpoints that detect a broken DB.
    Returns True if the DB is now reachable, False otherwise.
    """
    try:
        _state.engine = get_engine(DEFAULT_DB_PATH)
        SessionLocal = get_session(_state.engine)
        with SessionLocal() as session:
            session.execute(text("SELECT 1 FROM dogs LIMIT 1"))
        _state.db_ok = True
        return True
    except Exception as exc:
        logger.warning(f"DB reconnection failed: {exc}")
        _state.db_ok = False
        return False


def _probe_db() -> None:
    """Blocking: create engine, verify DB is reachable and tables exist."""
    if not _reconnect_db():
        raise RuntimeError("DB unreachable at startup")


def _load_search_model() -> None:
    """Blocking: load Mistral 7B GGUF via llama-cpp-python."""
    from llama_cpp import Llama

    model_path = Path(SEARCH_MODEL_PATH)
    if not model_path.exists():
        raise FileNotFoundError(f"GGUF model not found at {model_path}")

    _state.search_model = Llama(
        model_path=str(model_path),
        n_ctx=2048,
        n_threads=2,
        verbose=False,
    )
    _state.search_model_ok = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """only for context manager send blockings to threads"""
    # Startup: validate backend env vars first; misconfig should prevent startup.
    try:
        validate_backend_config(exit_on_error=False)
    except BackendConfigError as exc:
        logger.error(f"Backend config invalid: {exc}")
        raise

    try:
        await asyncio.to_thread(_probe_db)
        logger.info("DB connection OK")
    except Exception as exc:
        logger.warning(f"DB not reachable at startup: {exc}")
        _state.db_ok = False

    if any_backend_uses_mistral():
        try:
            await asyncio.to_thread(_load_search_model)
            logger.info(f"Search model loaded OK: {SEARCH_MODEL_PATH}")
        except Exception as exc:
            logger.warning(f"Search model not loaded at startup: {exc}")
            _state.search_model_ok = False
    else:
        logger.info("Skipping Mistral load — both backends point at Groq")

    if _state.db_ok:
        try:
            await asyncio.to_thread(_reload_caches)
        except Exception as exc:
            logger.warning(f"Cache load failed at startup: {exc}")

    yield

    # Shutdown
    if _state.search_model is not None:
        _state.search_model = None
        _state.search_model_ok = False
        logger.info("Search model released from memory")


##### FastAPI app


CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
IMAGES_DIR = os.environ.get("IMAGES_PATH", "data/images")

app = FastAPI(title="CuccioloFinder API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Path(IMAGES_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
##### Cache helpers (/api/enums, /api/stats, /api/stats/refresh)

def _reload_caches() -> int:
    """Re-query the DB and refresh both in-memory caches. Returns total dogs."""
    import json
    from sqlalchemy import distinct, func, select

    from .database.models import Breed, Dog
    from .enrichment.normalizers import normalize_age, normalize_weight

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    # TODO: remove debug logging after cache issue is resolved
    logger.info(f"_reload_caches: engine={engine.url}, _state.engine set={_state.engine is not None}")
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        # TODO: remove debug logging after cache issue is resolved
        raw_count = session.execute(text("SELECT COUNT(*) FROM dogs")).scalar()
        logger.info(f"_reload_caches: raw SQL count={raw_count}")

        # enums cache
        enums: dict = {}

        def distinct_non_null(col):
            rows = session.execute(
                select(distinct(col))
                .where(col.isnot(None), Dog.superseded_at.is_(None))
                .order_by(col)
            ).scalars().all()
            return [r for r in rows if r]

        enums["source_site"] = distinct_non_null(Dog.source_site)
        enums["gender_en"] = distinct_non_null(Dog.gender_en)
        enums["size_en"] = distinct_non_null(Dog.size_en)
        # Breed dropdown sources the canonical AKC catalogue (not distinct
        # values from `dogs.breed_en`), so users can filter on any approved
        # breed even when the dataset doesn't currently contain it.
        enums["breed_en"] = [
            b for (b,) in session.execute(
                select(Breed.name).order_by(Breed.name)
            ).all() if b
        ]
        enums["age_en"] = distinct_non_null(Dog.age_en)
        enums["fur_en"] = distinct_non_null(Dog.fur_en)
        enums["microchip_en"] = distinct_non_null(Dog.microchip_en)
        enums["sterilization_en"] = distinct_non_null(Dog.sterilization_en)
        enums["vaccine_en"] = distinct_non_null(Dog.vaccine_en)
        enums["deworming_en"] = distinct_non_null(Dog.deworming_en)

        # age_category: derived from age_en
        age_cats: set[str] = set()
        for (age_en,) in session.execute(
            select(Dog.age_en).where(Dog.age_en.isnot(None), Dog.superseded_at.is_(None))
        ).all():
            cat = normalize_age(age_en)
            if cat:
                age_cats.add(cat)
        enums["age_category"] = sorted(age_cats)

        # weight categories: derived from weight column
        weight_cats: set[str] = set()
        for (w,) in session.execute(
            select(Dog.weight).where(Dog.weight.isnot(None), Dog.superseded_at.is_(None))
        ).all():
            cat = normalize_weight(w)
            if cat:
                weight_cats.add(cat)
        enums["weight"] = sorted(weight_cats)

        # good_with_en / bad_with_en: flatten JSON arrays
        def flatten_json_array(col):
            values: set[str] = set()
            for (arr,) in session.execute(
                select(col).where(col.isnot(None), Dog.superseded_at.is_(None))
            ).all():
                if isinstance(arr, list):
                    for v in arr:
                        if v:
                            values.add(v)
                elif isinstance(arr, str):
                    try:
                        parsed = json.loads(arr)
                        for v in parsed:
                            if v:
                                values.add(v)
                    except (json.JSONDecodeError, TypeError):
                        pass
            return sorted(values)

        enums["good_with_en"] = flatten_json_array(Dog.good_with_en)
        enums["bad_with_en"] = flatten_json_array(Dog.bad_with_en)

        # Top-N most frequent breeds — used as a soft hint in the extraction
        # prompt so the model recognizes common breeds without restricting output.
        top_breed_rows = session.execute(
            select(Dog.breed_en, func.count(Dog.id))
            .where(Dog.breed_en.isnot(None), Dog.superseded_at.is_(None))
            .group_by(Dog.breed_en)
            .order_by(func.count(Dog.id).desc())
            .limit(20)
        ).all()
        enums["breed_en_top"] = [b for b, _ in top_breed_rows if b]

        # date ranges
        min_post, max_post = session.execute(
            select(func.min(Dog.post_date), func.max(Dog.post_date)).where(
                Dog.superseded_at.is_(None)
            )
        ).one()
        enums["post_date"] = {
            "min": str(min_post) if min_post else None,
            "max": str(max_post) if max_post else None,
        }

        min_ss, max_ss = session.execute(
            select(func.min(Dog.shelter_since), func.max(Dog.shelter_since)).where(
                Dog.shelter_since.isnot(None), Dog.superseded_at.is_(None)
            )
        ).one()
        enums["shelter_since"] = {
            "min": min_ss,
            "max": max_ss,
        }

        # populate enums cache
        _state.enums_cache = enums

        # stats cache
        dogs_rows = session.execute(
            select(Dog).where(Dog.superseded_at.is_(None))
        ).scalars().all()
        # TODO: remove debug logging after cache issue is resolved
        logger.info(f"_reload_caches: ORM dog count={len(dogs_rows)}")

        dog_list = []
        for dog in dogs_rows:
            dog_list.append({
                "id": dog.id,
                "source_site": dog.source_site,
                "name": dog.name,
                "gender": dog.gender,
                "gender_en": dog.gender_en,
                "age": dog.age,
                "age_en": dog.age_en,
                "age_category": normalize_age(dog.age_en),
                "size": dog.size,
                "size_en": dog.size_en,
                "breed": dog.breed,
                "breed_en": dog.breed_en,
                "fur": dog.fur,
                "fur_en": dog.fur_en,
                "weight": dog.weight,
                "weight_category": normalize_weight(dog.weight),
                "description": dog.description,
                "description_en": dog.description_en,
                "microchip": dog.microchip,
                "microchip_en": dog.microchip_en,
                "sterilization": dog.sterilization,
                "sterilization_en": dog.sterilization_en,
                "vaccine": dog.vaccine,
                "vaccine_en": dog.vaccine_en,
                "deworming": dog.deworming,
                "deworming_en": dog.deworming_en,
                "good_with": dog.good_with,
                "good_with_en": dog.good_with_en,
                "bad_with": dog.bad_with,
                "bad_with_en": dog.bad_with_en,
                "post_date": str(dog.post_date) if dog.post_date else None,
                "shelter_since": dog.shelter_since,
            })

        # populate stats cache
        _state.stats_cache = {"total": len(dog_list), "dogs": dog_list}

    return len(dog_list)

#### GET /api/enums

@app.get("/api/enums")
def enums():
    """Return distinct values for every filterable field, served from cache."""
    if not _state.enums_cache:
        raise HTTPException(status_code=503, detail="Enums not available — DB unreachable or cache never refreshed after a failed start")
    return {k: v for k, v in _state.enums_cache.items() if k != "breed_en_top"}


#### GET /api/stats

@app.get("/api/stats")
def stats():
    """Return row-level summary data for all dogs, served from cache."""
    if not _state.stats_cache:
        raise HTTPException(status_code=503, detail="Stats not available — DB unreachable or cache never refreshed after a failed start")
    return _state.stats_cache


#### POST /api/stats/refresh

@app.post("/api/stats/refresh")
def stats_refresh():
    """Reload enums + stats caches from the DB. Call after a scrape cycle."""
    from datetime import datetime, timezone

    if not _state.db_ok:
        logger.info("DB marked unreachable, attempting reconnection...")
        if not _reconnect_db():
            raise HTTPException(status_code=503, detail="Database unreachable")
        logger.info("DB reconnection successful")

    try:
        total = _reload_caches()
    except Exception as exc:
        # DB may have gone bad since last check — try reconnecting once
        logger.warning(f"Cache reload failed ({exc}), attempting DB reconnection...")
        if not _reconnect_db():
            raise HTTPException(status_code=503, detail="Database unreachable after reconnection attempt") from exc
        try:
            total = _reload_caches()
        except Exception as exc2:
            raise HTTPException(status_code=500, detail=f"Cache reload failed after reconnection: {exc2}") from exc2

    return {
        "status": "ok",
        "total_dogs": total,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }


#### GET /api/filter-dogs

class FilterDogsParams(BaseModel):
    source_site: str | None = None
    gender: str | None = None
    size: str | None = None
    breed: str | None = None
    age: str | None = None
    fur: str | None = None
    microchip: str | None = None
    sterilization: str | None = None
    vaccine: str | None = None
    deworming: str | None = None
    good_with: str | None = None
    bad_with: str | None = None
    weight: str | None = None
    post_date_from: date | None = None
    post_date_to: date | None = None
    shelter_since_from: date | None = None
    shelter_since_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


def _image_url(img: DogImage) -> str:
    """Return the locally-served URL when the image is downloaded, else the original URL."""
    if img.local_path:
        return f"/images/{img.local_path}"
    return img.url


def _try_parse_date(value: str | None) -> date | None:
    """Best-effort ISO date parse for shelter_since strings."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


@app.get("/api/filter-dogs")
def filter_dogs(params: FilterDogsParams = Depends()):
    """Structured search with optional filters. All filters are AND'd."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .database.models import Dog
    from .enrichment.normalizers import normalize_age, normalize_weight

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        q = select(Dog).options(
            selectinload(Dog.images),
            selectinload(Dog.inferred_breeds),
        ).where(Dog.superseded_at.is_(None))

        # SQL-level filters
        if params.source_site:
            q = q.where(Dog.source_site == params.source_site)
        if params.gender:
            q = q.where(Dog.gender_en == params.gender)
        if params.size:
            q = q.where(Dog.size_en == params.size)
        if params.breed:
            q = q.where(Dog.breed_en.ilike(f"%{params.breed}%"))
        if params.fur:
            q = q.where(Dog.fur_en == params.fur)
        if params.microchip:
            q = q.where(Dog.microchip_en == params.microchip)
        if params.sterilization:
            q = q.where(Dog.sterilization_en == params.sterilization)
        if params.vaccine:
            q = q.where(Dog.vaccine_en == params.vaccine)
        if params.deworming:
            q = q.where(Dog.deworming_en == params.deworming)
        if params.good_with:
            q = q.where(Dog.good_with_en.like(f'%"{params.good_with}"%'))
        if params.bad_with:
            q = q.where(Dog.bad_with_en.like(f'%"{params.bad_with}"%'))
        if params.post_date_from:
            q = q.where(Dog.post_date >= params.post_date_from)
        if params.post_date_to:
            q = q.where(Dog.post_date <= params.post_date_to)

        dogs = session.execute(q).scalars().all()

        # Python post-filters (fields derived at runtime, not stored in DB)
        if params.age:
            dogs = [d for d in dogs if normalize_age(d.age_en) == params.age]
        if params.weight:
            dogs = [d for d in dogs if normalize_weight(d.weight) == params.weight]
        if params.shelter_since_from or params.shelter_since_to:
            filtered = []
            for d in dogs:
                parsed = _try_parse_date(d.shelter_since)
                if parsed is None:
                    continue
                if params.shelter_since_from and parsed < params.shelter_since_from:
                    continue
                if params.shelter_since_to and parsed > params.shelter_since_to:
                    continue
                filtered.append(d)
            dogs = filtered

        total = len(dogs)
        offset = (params.page - 1) * params.page_size

        page_dogs = dogs[offset : offset + params.page_size]

        dog_list = []
        for dog in page_dogs:
            thumbnail = None
            if dog.images:
                first = min(
                    dog.images,
                    key=lambda img: img.position if img.position is not None else 999,
                )
                thumbnail = _image_url(first)
            top = _top_inferred_breed(dog)
            dog_list.append({
                "id": dog.id,
                "name": dog.name,
                "source_site": dog.source_site,
                "gender_en": dog.gender_en,
                "gender_from_desc": dog.gender_from_desc,
                "age_en": dog.age_en,
                "age_from_desc": dog.age_from_desc,
                "size_en": dog.size_en,
                "size_from_desc": dog.size_from_desc,
                "breed_en": dog.breed_en,
                "breed_from_desc": dog.breed_from_desc,
                "inferred_breed_top": top.model_dump() if top else None,
                "fur_en": dog.fur_en,
                "fur_from_desc": dog.fur_from_desc,
                "weight": dog.weight,
                "weight_from_desc": dog.weight_from_desc,
                "thumbnail": thumbnail,
            })

    return {
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "dogs": dog_list,
    }


#### GET /api/dogs/{id}

class DogImageOut(BaseModel):
    url: str
    position: int | None


class InferredBreedOut(BaseModel):
    method: str
    value: str
    confidence: float | None
    model_name: str | None


class DogProfileOut(BaseModel):
    id: int
    dog_uid: str
    name: str
    source_site: str
    source_url: str
    description_en: str | None
    gender_en: str | None
    gender_from_desc: str | None
    age_en: str | None
    age_from_desc: str | None
    size_en: str | None
    size_from_desc: str | None
    breed_en: str | None
    breed_from_desc: str | None
    inferred_breeds: list[InferredBreedOut]
    fur_en: str | None
    fur_from_desc: str | None
    weight: str | None
    weight_from_desc: str | None
    microchip_en: str | None
    microchip_from_desc: str | None
    sterilization_en: str | None
    sterilization_from_desc: str | None
    vaccine_en: str | None
    vaccine_from_desc: str | None
    deworming_en: str | None
    deworming_from_desc: str | None
    good_with_en: list[str] | None
    good_with_from_desc: list[str] | None
    bad_with_en: list[str] | None
    bad_with_from_desc: list[str] | None
    post_date: str | None
    shelter_since: str | None
    images: list[DogImageOut]


@app.get("/api/dogs/{dog_id}", response_model=DogProfileOut)
def get_dog(dog_id: int):
    """Return the full profile for a single dog, including all images."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .database.models import Dog

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        dog = session.execute(
            select(Dog)
            .where(Dog.id == dog_id, Dog.superseded_at.is_(None))
            .options(
                selectinload(Dog.images),
                selectinload(Dog.inferred_breeds),
            )
        ).scalar_one_or_none()

        if dog is None:
            raise HTTPException(status_code=404, detail=f"Dog {dog_id} not found")

        inferred = [
            InferredBreedOut(
                method=ib.method,
                value=ib.value,
                confidence=ib.confidence,
                model_name=ib.model_name,
            )
            for ib in dog.inferred_breeds
        ]

        return DogProfileOut(
            id=dog.id,
            dog_uid=dog.dog_uid,
            name=dog.name,
            source_site=dog.source_site,
            source_url=dog.source_url,
            description_en=dog.description_en,
            gender_en=dog.gender_en,
            gender_from_desc=dog.gender_from_desc,
            age_en=dog.age_en,
            age_from_desc=dog.age_from_desc,
            size_en=dog.size_en,
            size_from_desc=dog.size_from_desc,
            breed_en=dog.breed_en,
            breed_from_desc=dog.breed_from_desc,
            inferred_breeds=inferred,
            fur_en=dog.fur_en,
            fur_from_desc=dog.fur_from_desc,
            weight=dog.weight,
            weight_from_desc=dog.weight_from_desc,
            microchip_en=dog.microchip_en,
            microchip_from_desc=dog.microchip_from_desc,
            sterilization_en=dog.sterilization_en,
            sterilization_from_desc=dog.sterilization_from_desc,
            vaccine_en=dog.vaccine_en,
            vaccine_from_desc=dog.vaccine_from_desc,
            deworming_en=dog.deworming_en,
            deworming_from_desc=dog.deworming_from_desc,
            good_with_en=dog.good_with_en,
            good_with_from_desc=dog.good_with_from_desc,
            bad_with_en=dog.bad_with_en,
            bad_with_from_desc=dog.bad_with_from_desc,
            post_date=str(dog.post_date) if dog.post_date else None,
            shelter_since=dog.shelter_since,
            images=[
                DogImageOut(url=_image_url(img), position=img.position)
                for img in sorted(dog.images, key=lambda img: img.position if img.position is not None else 999)
            ],
        )


#### POST /api/dogs/search

# Stable canonical fields — domain-defined, not data-defined.
_VALID_VALUES: dict[str, set[str]] = {
    "size": {"small", "medium", "large", "giant"},
    "gender": {"male", "female"},
    "fur": {"short", "medium", "long"},
    "weight": {"light", "medium", "heavy"},
    "age": {"puppy", "young", "adult", "senior"},
}

_STRIP_VALUES = {"any", "all", "none", "unknown", "n/a", ""}

# Used when the enums cache is empty (first start, no dogs yet).
_GOOD_BAD_WITH_FALLBACK = ["children", "elderly", "cats", "dogs"]


def _build_extraction_system_prompt(
    good_with: list[str],
    bad_with: list[str],
    common_breeds: list[str],
) -> str:
    """Build the filter-extraction system prompt body (no [INST] wrappers).

    `common_breeds` MUST be empty for the Mistral call site — n_ctx=2048 on
    the CPU-only 8 GB VPS makes long breed enumerations expensive (RAM +
    latency). Pass the top-N list only on the Groq call site.
    """
    gw = ", ".join(good_with) if good_with else ", ".join(_GOOD_BAD_WITH_FALLBACK)
    bw = ", ".join(bad_with) if bad_with else ", ".join(_GOOD_BAD_WITH_FALLBACK)

    if common_breeds:
        breed_line = (
            f"- breed: the OUTPUT must be EXACTLY one of these allowed values (verbatim): {', '.join(common_breeds)}. "
            "If the user mentions a breed using a loose, partial, or related name (e.g. \"bulldog\", \"lab\", \"shepherd\"), use your judgment to pick the closest match from this list. "
            "If no value in the list reasonably matches the user's intent, OMIT the breed field entirely. NEVER output a breed name that is not in this list."
        )
        breed_rule = (
            "- breed: the output value MUST be copied verbatim from the allowed list above. "
            "You may interpret loose user phrasing to find the best-matching list entry, but the field value itself must be from the list — or omitted entirely. Never invent or substitute a name outside the list.\n"
        )
    else:
        breed_line = "- breed: any breed name (e.g. \"German Shepherd\", \"Golden Retriever\")"
        breed_rule = ""

    return (
        "You are a dog search assistant. Extract search filters from the user's text and return ONLY a JSON object. No explanation, no extra text.\n"
        "\n"
        "Valid keys and values:\n"
        "- size: small, medium, large, giant\n"
        "- gender: male, female\n"
        "- fur: short, medium, long\n"
        "- weight: light, medium, heavy\n"
        "- age: puppy, young, adult, senior\n"
        f"{breed_line}\n"
        f"- good_with: list from: {gw}\n"
        f"- bad_with: list from: {bw}\n"
        "\n"
        "Rules:\n"
        "- Include every attribute that is mentioned or implied. Do not skip any.\n"
        "- If the user says \"any\" for a field, do NOT include that field.\n"
        "- \"not good with X\" means bad_with, NOT good_with.\n"
        "- good_with and bad_with values must be lists.\n"
        f"{breed_rule}"
        "- Return ONLY the JSON object, nothing else.\n"
        "\n"
        "Examples:\n"
        "\n"
        "Text: \"big male dog with long fur, maybe a German Shepherd, good with elderly but not with cats\"\n"
        "{\"size\": \"large\", \"gender\": \"male\", \"fur\": \"long\", \"breed\": \"German Shepherd\", \"good_with\": [\"elderly\"], \"bad_with\": [\"cats\"]}\n"
        "\n"
        "Text: \"lightweight puppy good with kids and elderly\"\n"
        "{\"weight\": \"light\", \"age\": \"puppy\", \"good_with\": [\"children\", \"elderly\"]}\n"
        "\n"
        "Text: \"small female puppy that likes cats\"\n"
        "{\"size\": \"small\", \"gender\": \"female\", \"age\": \"puppy\", \"good_with\": [\"cats\"]}"
    )


def _validate_breed(breed_input: str) -> str | None:
    """Validate LLM-extracted breed against the breeds table.

    Returns canonical name on exact or single partial match.
    Returns None if no match, multiple matches, or sentinel value.
    """
    from .database.models import Breed

    if not breed_input or breed_input.strip().lower() in _STRIP_VALUES | {"mixed", "mutt"}:
        return None

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    session_factory = get_session(engine)
    with session_factory() as session:
        exact = session.query(Breed).filter(Breed.name.ilike(breed_input.strip())).first()
        if exact:
            return exact.name
        matches = session.query(Breed).filter(Breed.name.ilike(f"%{breed_input.strip()}%")).all()
        if len(matches) == 1:
            return matches[0].name
    return None


def _postprocess_filters(
    raw_filters: dict,
    good_with_valid: set[str],
    bad_with_valid: set[str],
) -> dict:
    """Validate and normalize LLM-extracted filters.

    `good_with_valid`/`bad_with_valid` are derived from the same enum source
    used to build the prompt, so prompt and validator stay in sync.
    """
    cleaned: dict[str, Any] = {}
    list_field_valid = {"good_with": good_with_valid, "bad_with": bad_with_valid}

    for key, value in raw_filters.items():
        if key == "breed":
            validated = _validate_breed(value if isinstance(value, str) else "")
            if validated:
                cleaned[key] = validated
        elif key in list_field_valid:
            valid_set = list_field_valid[key]
            if isinstance(value, str):
                value = [value]
            if isinstance(value, list):
                filtered = [v.strip().lower() for v in value
                            if isinstance(v, str) and v.strip().lower() in valid_set]
                if filtered:
                    cleaned[key] = filtered
        elif key in _VALID_VALUES:
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in _STRIP_VALUES:
                    continue
                if normalized in _VALID_VALUES[key]:
                    cleaned[key] = normalized
        else:
            cleaned[key] = value

    return cleaned


_EXTRACTION_VALID_KEYS = {
    "size", "gender", "fur", "weight", "age", "breed", "good_with", "bad_with",
}


def _extract_filters_mistral(query: str, system_prompt: str) -> tuple[dict, str]:
    """Run Mistral on the query and return (raw_filters_dict, raw_output)."""
    import json
    import re

    prompt = f"[INST] {system_prompt}\n\nText: \"{query}\" [/INST]"
    llm = _state.search_model
    output = llm(prompt, max_tokens=200, stop=["\n\n"], temperature=0.0)
    raw = output["choices"][0]["text"].strip()
    logger.info(f"Mistral search raw output: {raw!r}")

    def _try_parse(text: str) -> dict | None:
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return {k: v for k, v in obj.items() if k in _EXTRACTION_VALID_KEYS}
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    result = _try_parse(raw)
    if result is None:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = _try_parse(match.group())

    return result or {}, raw


def _extract_filters(query: str) -> tuple[dict, str]:
    """Dispatch filter extraction to the configured backend.

    Reads dynamic enum values from the cache, builds the shared system prompt
    (with a top-N breed hint only on the Groq path — Mistral's context budget
    can't afford the extra tokens), and post-processes against the same enum
    sets used to build the prompt.
    """
    enums = _state.enums_cache or {}
    good_with = enums.get("good_with_en") or list(_GOOD_BAD_WITH_FALLBACK)
    bad_with = enums.get("bad_with_en") or list(_GOOD_BAD_WITH_FALLBACK)

    backend = get_search_backend()
    common_breeds = enums.get("breed_en_top", []) if backend == "groq" else []
    logger.info(f"Search extraction: backend={backend}, common_breeds={common_breeds}")

    system_prompt = _build_extraction_system_prompt(good_with, bad_with, common_breeds)

    if backend == "groq":
        from .enrichment.groq_client import GroqError, groq_extract_filters
        try:
            raw_filters, raw_output = groq_extract_filters(query, system_prompt)
        except GroqError as exc:
            if get_fallback_enabled() and _state.search_model_ok:
                logger.warning(f"Groq extraction failed, falling back to Mistral: {exc}")
                # Mistral fallback: rebuild prompt without the breed hint to
                # respect Mistral's prompt-size constraint.
                mistral_prompt = _build_extraction_system_prompt(good_with, bad_with, [])
                raw_filters, raw_output = _extract_filters_mistral(query, mistral_prompt)
            else:
                raise
    else:
        raw_filters, raw_output = _extract_filters_mistral(query, system_prompt)

    cleaned = _postprocess_filters(raw_filters, set(good_with), set(bad_with))
    return cleaned, raw_output


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)


class DogSummaryOut(BaseModel):
    id: int
    name: str
    source_site: str
    gender_en: str | None
    gender_from_desc: str | None
    age_en: str | None
    age_from_desc: str | None
    size_en: str | None
    size_from_desc: str | None
    breed_en: str | None
    breed_from_desc: str | None
    # Highest-confidence row from `inferred_dog_breeds` (or None). The full
    # candidate list lives on /api/dogs/{id} — kept off the summary to
    # keep list payloads small.
    inferred_breed_top: InferredBreedOut | None
    fur_en: str | None
    fur_from_desc: str | None
    weight: str | None
    weight_from_desc: str | None
    thumbnail: str | None


def _top_inferred_breed(dog) -> InferredBreedOut | None:
    """Return the highest-confidence inferred breed row, or None.

    Rows with `confidence is None` are sorted last so they only win if no
    confidence-bearing row exists.
    """
    if not dog.inferred_breeds:
        return None
    best = max(
        dog.inferred_breeds,
        key=lambda ib: (ib.confidence is not None, ib.confidence or 0.0),
    )
    return InferredBreedOut(
        method=best.method,
        value=best.value,
        confidence=best.confidence,
        model_name=best.model_name,
    )


class SearchResponse(BaseModel):
    query: str
    extracted_filters: dict
    raw_model_output: str  # TEMPORARY — remove after testing
    total: int
    dogs: list[DogSummaryOut]


@app.post("/api/dogs/search", response_model=SearchResponse)
def search_dogs(req: SearchRequest):
    """Natural language search: extract filters via LLM then query the DB."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .database.models import Dog
    from .enrichment.normalizers import normalize_age, normalize_weight

    backend = get_search_backend()
    if backend == "mistral" and not _state.search_model_ok:
        raise HTTPException(status_code=503, detail="Search model not available")

    from .enrichment.groq_client import GroqError
    try:
        extracted, raw_output = _extract_filters(req.query)
    except GroqError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Groq extraction failed: {exc}",
        ) from exc

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        q = select(Dog).options(
            selectinload(Dog.images),
            selectinload(Dog.inferred_breeds),
        ).where(Dog.superseded_at.is_(None))

        # SQL-level filters from extracted fields
        if gender := extracted.get("gender"):
            q = q.where(Dog.gender_en == gender)
        if size := extracted.get("size"):
            q = q.where(Dog.size_en == size)
        if breed := extracted.get("breed"):
            q = q.where(Dog.breed_en.ilike(f"%{breed}%"))
        if fur := extracted.get("fur"):
            q = q.where(Dog.fur_en == fur)
        # good_with / bad_with may be lists or strings — AND condition for each value
        gw_val = extracted.get("good_with") or []
        if isinstance(gw_val, str):
            gw_val = [gw_val]
        for gw in gw_val:
            q = q.where(Dog.good_with_en.like(f'%"{gw}"%'))
        bw_val = extracted.get("bad_with") or []
        if isinstance(bw_val, str):
            bw_val = [bw_val]
        for bw in bw_val:
            q = q.where(Dog.bad_with_en.like(f'%"{bw}"%'))

        dogs = session.execute(q).scalars().all()

        # post-filters
        if age := extracted.get("age"):
            dogs = [d for d in dogs if normalize_age(d.age_en) == age]
        if weight := extracted.get("weight"):
            dogs = [d for d in dogs if normalize_weight(d.weight) == weight]

        dogs = dogs[: req.limit]

        dog_list = []
        for dog in dogs:
            thumbnail = None
            if dog.images:
                first = min(
                    dog.images,
                    key=lambda img: img.position if img.position is not None else 999,
                )
                thumbnail = _image_url(first)
            dog_list.append(DogSummaryOut(
                id=dog.id,
                name=dog.name,
                source_site=dog.source_site,
                gender_en=dog.gender_en,
                gender_from_desc=dog.gender_from_desc,
                age_en=dog.age_en,
                age_from_desc=dog.age_from_desc,
                size_en=dog.size_en,
                size_from_desc=dog.size_from_desc,
                breed_en=dog.breed_en,
                breed_from_desc=dog.breed_from_desc,
                inferred_breed_top=_top_inferred_breed(dog),
                fur_en=dog.fur_en,
                fur_from_desc=dog.fur_from_desc,
                weight=dog.weight,
                weight_from_desc=dog.weight_from_desc,
                thumbnail=thumbnail,
            ))

    return SearchResponse(
        query=req.query,
        extracted_filters=extracted,
        raw_model_output=raw_output,
        total=len(dog_list),
        dogs=dog_list,
    )


#### POST /api/debug/prompt (TEMPORARY — remove after testing)

class DebugPromptRequest(BaseModel):
    prompt: str

@app.post("/api/debug/prompt")
def debug_prompt(req: DebugPromptRequest):
    """Temporary: send a raw prompt to the search model and return the raw output."""
    if not _state.search_model_ok:
        raise HTTPException(status_code=503, detail="Search model not available")
    llm = _state.search_model
    output = llm(req.prompt, max_tokens=200, stop=["\n\n"], temperature=0.0)
    raw = output["choices"][0]["text"].strip()
    return {"raw_output": raw}


#### POST /api/translate/description

_TRANSLATION_PROMPT = """\
[INST] You are translating an Italian dog shelter adoption listing into English.

Rules:
- Translate the full text naturally, preserving the warm and hopeful tone typical of adoption listings.
- Keep the meaning accurate but use natural English phrasing, not word-for-word translation.
- Shelter-specific terms: "canile" = shelter, "box" = kennel, "adottabile" = available for adoption, "staffetta" = transport relay.
- Preserve any names, dates, locations, and identification numbers exactly as written.
- Return ONLY the English translation, nothing else.
- Do NOT add notes, comments, explanations, or repeat the translation.
- Do NOT prefix with "Translation:" or similar headers.

Italian text:
{text}
[/INST]"""


class TranslateRequest(BaseModel):
    text: str


@app.post("/api/translate/description")
def translate_description(req: TranslateRequest):
    """Translate Italian dog description to English using Mistral."""
    if not _state.search_model_ok:
        raise HTTPException(status_code=503, detail="Search model not available")

    if not req.text or not req.text.strip():
        return {"translation": ""}

    logger.info(f"Translation request ({len(req.text)} chars): {req.text.strip()[:200]}...")

    text = req.text.strip()
    prompt = _TRANSLATION_PROMPT.replace("{text}", text)
    llm = _state.search_model
    max_tokens = max(50, len(text) // 3)
    t0 = time.time()
    output = llm(prompt, max_tokens=max_tokens, stop=["[INST]"], temperature=0.2, repeat_penalty=1.3)
    elapsed = time.time() - t0
    translation = output["choices"][0]["text"].strip()

    logger.info(f"Translation done in {elapsed:.1f}s ({len(translation)} chars): {translation[:200]}...")
    return {"translation": translation}


#### Worker status

class WorkerStatusRequest(BaseModel):
    busy: bool


@app.post("/api/worker/status")
def set_worker_status(req: WorkerStatusRequest):
    """Called by worker to signal pipeline start/end. Persisted to file."""
    if req.busy:
        WORKER_STATUS_FILE.write_text(str(time.time()))
        logger.info("Worker status: busy (file written)")
    else:
        WORKER_STATUS_FILE.unlink(missing_ok=True)
        logger.info("Worker status: ready (file removed)")
    return {"ok": True}


@app.get("/api/worker/status")
def get_worker_status():
    """Check if worker pipeline is running. Reads from file, auto-clears after timeout."""
    if not WORKER_STATUS_FILE.exists():
        return {"busy": False}
    try:
        busy_since = float(WORKER_STATUS_FILE.read_text().strip())
    except (ValueError, OSError):
        return {"busy": False}
    if (time.time() - busy_since) > WORKER_BUSY_TIMEOUT:
        WORKER_STATUS_FILE.unlink(missing_ok=True)
        logger.info("Worker busy status auto-cleared (timeout)")
        return {"busy": False}
    return {"busy": True}


#### GET /api/health

# 30 s in-memory cache for the Groq liveness probe. Health endpoints get
# polled aggressively (load balancers, monitoring, frontend banner) — we
# don't want each poll triggering an outbound HTTPS call to Groq.
_GROQ_PROBE_CACHE_TTL = 30.0
_groq_probe_cache: dict[str, float | bool] = {"at": 0.0, "responsive": False}


def _groq_responsive_cached() -> bool:
    """Cached `is_responsive()` probe — refreshed at most once per 30 s."""
    from .enrichment.groq_client import is_responsive

    now = time.time()
    if (now - float(_groq_probe_cache["at"])) < _GROQ_PROBE_CACHE_TTL:
        return bool(_groq_probe_cache["responsive"])

    result = is_responsive()
    _groq_probe_cache["at"] = now
    _groq_probe_cache["responsive"] = result
    return result


@app.get("/api/health")
def health():
    """Health check: DB + per-model readiness + active backend echo.

    If the DB is unreachable, attempts to reconnect so the API can
    self-heal after OOM restarts.
    """
    db_ok = False
    try:
        engine = _state.engine or get_engine(DEFAULT_DB_PATH)
        SessionLocal = get_session(engine)
        with SessionLocal() as session:
            session.execute(text("SELECT 1 FROM dogs LIMIT 1"))
        db_ok = True
    except Exception:
        db_ok = _reconnect_db()

    _state.db_ok = db_ok

    search_backend = get_search_backend()
    translation_backend = get_translation_backend()
    groq_in_use = any_backend_uses_groq()
    groq_configured = bool((os.environ.get("GROQ_API_KEY") or "").strip())

    # Only probe Groq when at least one backend actually uses it — otherwise
    # don't make outbound calls the operator didn't ask for.
    if groq_in_use and groq_configured:
        groq_responsive: bool | None = _groq_responsive_cached()
    elif groq_in_use:
        groq_responsive = False  # backend=groq but key missing
    else:
        groq_responsive = None

    # Active search backend usable?
    if search_backend == "mistral":
        search_ok = _state.search_model_ok
    else:
        search_ok = groq_configured and bool(groq_responsive)

    all_ok = _state.db_ok and search_ok
    return {
        "status": "ok" if all_ok else "degraded",
        "db": _state.db_ok,
        "models": {
            "mistral": {"loaded": _state.search_model_ok},
            "groq": {
                "configured": groq_configured,
                "responsive": groq_responsive,
            },
        },
        "backends": {
            "search": search_backend,
            "translation": translation_backend,
        },
    }
