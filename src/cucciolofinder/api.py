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
    any_backend_uses_openrouter,
    get_extract_backend,
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


def _ensure_search_model_loaded() -> None:
    """Lazy-load Mistral if not already loaded.

    Used on the extraction-fallback path: when both backends are set to
    Groq, Mistral is skipped at startup to save RAM. The worker only
    triggers Mistral when Groq fails, and we load on demand here. The
    worker is expected to call `/api/search-model/unload` once Stage 2/3
    finishes, so Mistral doesn't sit in RAM between runs.
    """
    if _state.search_model_ok:
        return
    logger.info("Loading Mistral on demand (was skipped at startup)…")
    _load_search_model()
    logger.info(f"Mistral loaded on demand: {SEARCH_MODEL_PATH}")


def _unload_search_model() -> None:
    """Drop the Mistral model and free its memory."""
    import gc

    if _state.search_model is None:
        return
    _state.search_model = None
    _state.search_model_ok = False
    gc.collect()
    logger.info("Mistral unloaded — memory released")


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

    from .database.models import Dog, InferredDogBreed
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

        # `breed_claimed` — union of distinct non-empty values from the
        # two claim columns. `breed_en` is the shelter's structured breed
        # translated; `breed_from_desc` is LLM-extracted from description.
        # Sibling sources, not primary/fallback — dropdown shows every
        # breed string the shelters have actually used.
        claimed: set[str] = set()
        for col in (Dog.breed_en, Dog.breed_from_desc):
            for (val,) in session.execute(
                select(col).where(
                    col.isnot(None), col != "", Dog.superseded_at.is_(None)
                ).distinct()
            ).all():
                if val and val.strip():
                    claimed.add(val.strip())
        enums["breed_claimed"] = sorted(claimed)

        # `breed_detected` — distinct AKC names written to inferred_dog_breeds
        # by any of the four detection methods, restricted to active dogs.
        # Explicit method list so future inference methods don't bleed in
        # without an opt-in.
        enums["breed_detected"] = sorted({
            val
            for (val,) in session.execute(
                select(InferredDogBreed.value)
                .join(Dog, Dog.id == InferredDogBreed.dog_id)
                .where(
                    Dog.superseded_at.is_(None),
                    InferredDogBreed.method.in_(
                        ("image", "image_2nd", "cat_similarity", "cat_similarity_2nd")
                    ),
                )
                .distinct()
            ).all()
            if val
        })
        enums["age_en"] = distinct_non_null(Dog.age_en)
        enums["fur_en"] = distinct_non_null(Dog.fur_en)
        enums["microchip_en"] = distinct_non_null(Dog.microchip_en)
        enums["sterilization_en"] = distinct_non_null(Dog.sterilization_en)
        enums["vaccine_en"] = distinct_non_null(Dog.vaccine_en)
        enums["deworming_en"] = distinct_non_null(Dog.deworming_en)

        # age_category: union of normalize_age(age_en or age_from_desc) across
        # active dogs. Pulling both columns means categories that only show
        # up via LLM extraction still appear in the dropdown.
        age_cats: set[str] = set()
        for (age_en, age_fd) in session.execute(
            select(Dog.age_en, Dog.age_from_desc).where(Dog.superseded_at.is_(None))
        ).all():
            cat = normalize_age(age_en or age_fd)
            if cat:
                age_cats.add(cat)
        enums["age_category"] = sorted(age_cats)

        # weight categories: same fallback rule as age_category. `weight` is
        # the raw IT scrape; `weight_from_desc` is the LLM extraction.
        weight_cats: set[str] = set()
        for (w, w_fd) in session.execute(
            select(Dog.weight, Dog.weight_from_desc).where(Dog.superseded_at.is_(None))
        ).all():
            cat = normalize_weight(w or w_fd)
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

        # `breed_allowed` — the verbatim-allowed list fed to the smart-search
        # LLM prompt. Union of breed strings that actually exist on active
        # dogs: claimed breeds (breed_en ∪ breed_from_desc) plus AI-detected
        # breeds from the image classifier. We exclude the 2nd-choice and
        # cat_similarity rows so the candidate list reflects what a human
        # would call "what the photo most clearly shows" plus what shelters
        # claim — not every weakly-related guess.
        #
        # The same list is reused by `_validate_breed` as the membership
        # gate, so prompt and validator can't drift. Mistral's call site
        # ignores it (n_ctx=2048 budget).
        breed_allowed: set[str] = set(enums["breed_claimed"])
        for (val,) in session.execute(
            select(InferredDogBreed.value)
            .join(Dog, Dog.id == InferredDogBreed.dog_id)
            .where(
                Dog.superseded_at.is_(None),
                InferredDogBreed.method == "image",
            )
            .distinct()
        ).all():
            if val:
                breed_allowed.add(val)
        enums["breed_allowed"] = sorted(breed_allowed)

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

        # Which shelters actually populate each date column. Used by the
        # frontend to hide the date filters for shelters that never expose
        # them. Auto-discovered from the data: any spider that starts
        # emitting a date will show up here after the next cache refresh.
        post_date_sources = session.execute(
            select(distinct(Dog.source_site)).where(
                Dog.post_date.isnot(None), Dog.superseded_at.is_(None)
            )
        ).scalars().all()
        shelter_since_sources = session.execute(
            select(distinct(Dog.source_site)).where(
                Dog.shelter_since.isnot(None),
                Dog.shelter_since != "",
                Dog.superseded_at.is_(None),
            )
        ).scalars().all()
        enums["date_support"] = {
            "post_date": sorted(s for s in post_date_sources if s),
            "shelter_since": sorted(s for s in shelter_since_sources if s),
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
            # `*_from_desc` columns are the LLM-extracted fallbacks from the
            # description. They're emitted independently of `*_en` — the
            # merge policy (which one wins, how to badge it) is a frontend
            # display concern, not something the API decides.
            dog_list.append({
                "id": dog.id,
                "source_site": dog.source_site,
                "name": dog.name,
                "gender": dog.gender,
                "gender_en": dog.gender_en,
                "gender_from_desc": dog.gender_from_desc,
                "age": dog.age,
                "age_en": dog.age_en,
                "age_from_desc": dog.age_from_desc,
                # Derived from whichever source carries the value. `_en` wins
                # when present (literal translation of the structured field);
                # we fall back to `_from_desc` so dogs whose shelter doesn't
                # expose age structurally still bucket into a category.
                "age_category": normalize_age(dog.age_en or dog.age_from_desc),
                "size": dog.size,
                "size_en": dog.size_en,
                "size_from_desc": dog.size_from_desc,
                "breed": dog.breed,
                "breed_en": dog.breed_en,
                "breed_from_desc": dog.breed_from_desc,
                "fur": dog.fur,
                "fur_en": dog.fur_en,
                "fur_from_desc": dog.fur_from_desc,
                "weight": dog.weight,
                "weight_from_desc": dog.weight_from_desc,
                # Same fallback rule as age_category — see note above.
                "weight_category": normalize_weight(dog.weight or dog.weight_from_desc),
                "description": dog.description,
                "description_en": dog.description_en,
                "microchip": dog.microchip,
                "microchip_en": dog.microchip_en,
                "microchip_from_desc": dog.microchip_from_desc,
                "sterilization": dog.sterilization,
                "sterilization_en": dog.sterilization_en,
                "sterilization_from_desc": dog.sterilization_from_desc,
                "vaccine": dog.vaccine,
                "vaccine_en": dog.vaccine_en,
                "vaccine_from_desc": dog.vaccine_from_desc,
                "deworming": dog.deworming,
                "deworming_en": dog.deworming_en,
                "deworming_from_desc": dog.deworming_from_desc,
                "good_with": dog.good_with,
                "good_with_en": dog.good_with_en,
                "good_with_from_desc": dog.good_with_from_desc,
                "bad_with": dog.bad_with,
                "bad_with_en": dog.bad_with_en,
                "bad_with_from_desc": dog.bad_with_from_desc,
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
    return {k: v for k, v in _state.enums_cache.items() if k != "breed_allowed"}


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
    # Claimed breed — matches Dog.breed_en OR Dog.breed_from_desc
    # (case-insensitive substring). Independent of `breed_detected`.
    breed: str | None = None
    # Detected breed — exact AKC name match across all four AI methods
    # (image, image_2nd, cat_similarity, cat_similarity_2nd).
    breed_detected: str | None = None
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


def _eq_resolved(col_en, col_fd, value):
    """SQL clause matching `resolve(col_en, col_fd) == value`.

    Mirrors the frontend's merge rule (prefer `_en` when truthy, fall back to
    `_from_desc`). Used so filter endpoints agree with the stats page:

      - If `_en` carries a value, that wins. The dog matches iff `col_en == value`.
      - Only if `_en` is null/empty does `_from_desc` get consulted.

    A naive `or_(col_en == v, col_fd == v)` would over-match on conflicts
    (e.g. _en='medium', _from_desc='large' would appear in both buckets).
    """
    from sqlalchemy import and_, or_
    return or_(
        col_en == value,
        and_(or_(col_en.is_(None), col_en == ''), col_fd == value),
    )


def _like_resolved(col_en, col_fd, pattern):
    """LIKE variant of `_eq_resolved` for substring / JSON-array matching."""
    from sqlalchemy import and_, or_
    return or_(
        col_en.like(pattern),
        and_(or_(col_en.is_(None), col_en == '', col_en == '[]'), col_fd.like(pattern)),
    )


def _ilike_resolved(col_en, col_fd, pattern):
    """Case-insensitive LIKE variant — used for the claimed-breed search."""
    from sqlalchemy import and_, or_
    return or_(
        col_en.ilike(pattern),
        and_(or_(col_en.is_(None), col_en == ''), col_fd.ilike(pattern)),
    )


@app.get("/api/filter-dogs")
def filter_dogs(params: FilterDogsParams = Depends()):
    """Structured search with optional filters. All filters are AND'd."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .database.models import Dog, InferredDogBreed
    from .enrichment.normalizers import normalize_age, normalize_weight

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        q = select(Dog).options(
            selectinload(Dog.images),
            selectinload(Dog.inferred_breeds),
        ).where(Dog.superseded_at.is_(None))

        # SQL-level filters. Fields with a `_from_desc` sibling go through
        # `_eq_resolved` so the merge rule (prefer `_en`, fall back to
        # `_from_desc`) matches what the stats page does — otherwise the
        # filter count and the stats count disagree for the same value.
        if params.source_site:
            q = q.where(Dog.source_site == params.source_site)
        if params.gender:
            q = q.where(_eq_resolved(Dog.gender_en, Dog.gender_from_desc, params.gender))
        if params.size:
            q = q.where(_eq_resolved(Dog.size_en, Dog.size_from_desc, params.size))
        if params.breed:
            # Claimed breed: substring search routed through the merge rule.
            pat = f"%{params.breed}%"
            q = q.where(_ilike_resolved(Dog.breed_en, Dog.breed_from_desc, pat))
        if params.breed_detected:
            # Detected breed: any of the AI-inference methods matched
            # this canonical AKC name. `exists()` avoids row duplication
            # when multiple methods agree on the same breed.
            q = q.where(
                select(InferredDogBreed.id).where(
                    InferredDogBreed.dog_id == Dog.id,
                    InferredDogBreed.value == params.breed_detected,
                    InferredDogBreed.method.in_(
                        ("image", "image_2nd", "cat_similarity", "cat_similarity_2nd")
                    ),
                ).exists()
            )
        if params.fur:
            q = q.where(_eq_resolved(Dog.fur_en, Dog.fur_from_desc, params.fur))
        if params.microchip:
            q = q.where(_eq_resolved(Dog.microchip_en, Dog.microchip_from_desc, params.microchip))
        if params.sterilization:
            q = q.where(_eq_resolved(Dog.sterilization_en, Dog.sterilization_from_desc, params.sterilization))
        if params.vaccine:
            q = q.where(_eq_resolved(Dog.vaccine_en, Dog.vaccine_from_desc, params.vaccine))
        if params.deworming:
            q = q.where(_eq_resolved(Dog.deworming_en, Dog.deworming_from_desc, params.deworming))
        if params.good_with:
            # JSON arrays stored as text — `'%"value"%'` finds the value
            # whether it sits at the start, middle, or end of the list.
            pat = f'%"{params.good_with}"%'
            q = q.where(_like_resolved(Dog.good_with_en, Dog.good_with_from_desc, pat))
        if params.bad_with:
            pat = f'%"{params.bad_with}"%'
            q = q.where(_like_resolved(Dog.bad_with_en, Dog.bad_with_from_desc, pat))
        if params.post_date_from:
            q = q.where(Dog.post_date >= params.post_date_from)
        if params.post_date_to:
            q = q.where(Dog.post_date <= params.post_date_to)

        dogs = session.execute(q).scalars().all()

        # Python post-filters (derived from `normalize_*`, can't be pushed to SQL).
        # Same merge rule as the SQL filters above: `_en`/raw wins, fall back
        # to `_from_desc`. Matches the stats cache's derived categories.
        if params.age:
            dogs = [d for d in dogs if normalize_age(d.age_en or d.age_from_desc) == params.age]
        if params.weight:
            dogs = [d for d in dogs if normalize_weight(d.weight or d.weight_from_desc) == params.weight]
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
            inferred_breeds = _inferred_breeds_list(dog)
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
                "inferred_breed_top": top.model_dump(),
                "inferred_breeds": [b.model_dump() for b in inferred_breeds],
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


class InferredBreedTop(BaseModel):
    """Top breed per method group — keyed explicitly so the frontend
    doesn't have to compare incomparable confidence scales (image =
    softmax probability, cat_similarity = coverage).

    `image` is the `method='image'` row (top-1 from ViT, always higher
    than `image_2nd`). `cat_similarity` is the `method='cat_similarity'`
    row (top-1 from categorical scoring; same coverage as `_2nd` but the
    primary). Either may be `null` when its pipeline produced no row.
    """
    image: InferredBreedOut | None
    cat_similarity: InferredBreedOut | None


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
    allowed_breeds: list[str],
) -> str:
    """Build the filter-extraction system prompt body (no [INST] wrappers).

    `allowed_breeds` MUST be empty for the Mistral call site — n_ctx=2048 on
    the CPU-only 8 GB VPS makes long breed enumerations expensive (RAM +
    latency). Pass the breed list only on the Groq / OpenRouter call sites.
    The list reflects the breeds that actually exist in the DB (claimed +
    image-detected) so the LLM's output always corresponds to dogs the
    user can find.
    """
    gw = ", ".join(good_with) if good_with else ", ".join(_GOOD_BAD_WITH_FALLBACK)
    bw = ", ".join(bad_with) if bad_with else ", ".join(_GOOD_BAD_WITH_FALLBACK)

    if allowed_breeds:
        breed_line = (
            f"- breed: a JSON ARRAY (not a string) of every entry from this allowed list that could plausibly match the user's intent (verbatim): {', '.join(allowed_breeds)}. "
            "Include synonyms, abbreviations, mixes, and canonical-vs-short forms of the same breed (e.g. \"lab\" → both \"Labrador Retriever\" and \"Labrador\", \"golden\" → both \"Golden Retriever\" and \"golden\" if present). "
            "Do NOT include unrelated breeds just because they share a group (e.g. don't add \"Labrador Retriever\" when the user asked for \"Golden Retriever\" just because both are retrievers). "
            "If no entry in the list plausibly matches, output an empty array [] or OMIT the field. NEVER output a breed name that is not in the allowed list."
        )
        breed_rule = (
            "- breed: a JSON array of zero or more values, each copied verbatim from the allowed list above. "
            "You may interpret loose phrasing to nominate multiple list entries that describe the same breed, but every value must be in the list — or the array must be empty.\n"
        )
    else:
        breed_line = (
            "- breed: a JSON ARRAY of one or more breed names (e.g. [\"Golden Retriever\", \"golden\"]). "
            "Include canonical and short/mix variants so downstream search can match both. Empty array or omit if no breed is mentioned."
        )
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
        "{\"size\": \"large\", \"gender\": \"male\", \"fur\": \"long\", \"breed\": [\"German Shepherd\", \"German Shepherd Dog\", \"German Shepherd mix\"], \"good_with\": [\"elderly\"], \"bad_with\": [\"cats\"]}\n"
        "\n"
        "Text: \"lightweight puppy good with kids and elderly\"\n"
        "{\"weight\": \"light\", \"age\": \"puppy\", \"good_with\": [\"children\", \"elderly\"]}\n"
        "\n"
        "Text: \"a golden retriever that's good with elderly\"\n"
        "{\"breed\": [\"Golden Retriever\", \"golden\", \"golden-mix\"], \"good_with\": [\"elderly\"]}\n"
        "\n"
        "Text: \"small female puppy that likes cats\"\n"
        "{\"size\": \"small\", \"gender\": \"female\", \"age\": \"puppy\", \"good_with\": [\"cats\"]}"
    )


def _validate_breed(breed_input, allowed: set[str]) -> list[str]:
    """Membership gate: keep only LLM-emitted breed candidates that are
    verbatim in the prompt's allowed list (case-insensitive). Returns a
    deduped list preserving the LLM's emission order.

    `breed_input` may be a string (legacy single-pick) or a list (current
    multi-pick design). `allowed` is the same set used to render the
    prompt — `breed_allowed` from the enums cache: claimed breeds ∪
    image-detected breeds. Sentinel values ("any", "mixed", "mutt", …)
    are dropped. Anything outside the list is dropped — the SQL filter
    would otherwise return nothing or, worse, the wrong dogs.
    """
    if not breed_input:
        return []
    if isinstance(breed_input, str):
        candidates: list[str] = [breed_input]
    elif isinstance(breed_input, list):
        candidates = [c for c in breed_input if isinstance(c, str)]
    else:
        return []

    allowed_lower = {a.lower(): a for a in allowed}
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        s = c.strip()
        if not s or s.lower() in _STRIP_VALUES | {"mixed", "mutt"}:
            continue
        canonical = allowed_lower.get(s.lower())
        if canonical and canonical not in seen:
            out.append(canonical)
            seen.add(canonical)
    return out


def _postprocess_filters(
    raw_filters: dict,
    good_with_valid: set[str],
    bad_with_valid: set[str],
    allowed_breeds: set[str],
) -> dict:
    """Validate and normalize LLM-extracted filters.

    `good_with_valid`/`bad_with_valid`/`allowed_breeds` are derived from
    the same enum source used to build the prompt, so prompt and validator
    stay in sync. The breed field becomes a list of candidates — see
    `_validate_breed` for the shape.
    """
    cleaned: dict[str, Any] = {}
    list_field_valid = {"good_with": good_with_valid, "bad_with": bad_with_valid}

    for key, value in raw_filters.items():
        if key == "breed":
            validated_list = _validate_breed(value, allowed_breeds)
            if validated_list:
                cleaned[key] = validated_list
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
    (with the breed allowed-list on remote paths — Mistral's context budget
    can't afford the extra tokens), and post-processes against the same enum
    sets used to build the prompt.
    """
    enums = _state.enums_cache or {}
    good_with = enums.get("good_with_en") or list(_GOOD_BAD_WITH_FALLBACK)
    bad_with = enums.get("bad_with_en") or list(_GOOD_BAD_WITH_FALLBACK)

    backend = get_search_backend()
    # The full allowed-list always feeds the *validator* (gate vs. real DB
    # breeds, runs in Python after inference). The *prompt* only receives
    # it on remote backends — Mistral's n_ctx=2048 budget can't carry the
    # extra tokens, so its prompt body stays lean ("any breed name").
    breed_allowed = enums.get("breed_allowed", [])
    breeds_for_prompt = breed_allowed if backend in ("groq", "openrouter") else []
    logger.info(
        f"Search extraction: backend={backend}, "
        f"allowed_breeds_count={len(breed_allowed)}, "
        f"in_prompt={len(breeds_for_prompt) > 0}"
    )

    system_prompt = _build_extraction_system_prompt(good_with, bad_with, breeds_for_prompt)

    if backend == "groq":
        from .enrichment.groq_client import GroqError, groq_extract_filters
        try:
            raw_filters, raw_output = groq_extract_filters(query, system_prompt)
        except GroqError as exc:
            if get_fallback_enabled() and _state.search_model_ok:
                logger.warning(f"Groq extraction failed, falling back to Mistral: {exc}")
                # Mistral fallback: rebuild prompt without the breed list
                # to respect Mistral's prompt-size constraint. The validator
                # still runs against the full `breed_allowed` set below.
                mistral_prompt = _build_extraction_system_prompt(good_with, bad_with, [])
                raw_filters, raw_output = _extract_filters_mistral(query, mistral_prompt)
            else:
                raise
    elif backend == "openrouter":
        from .enrichment.openrouter_client import (
            OpenRouterError,
            openrouter_extract_filters,
        )
        try:
            raw_filters, raw_output = openrouter_extract_filters(query, system_prompt)
        except OpenRouterError as exc:
            if get_fallback_enabled() and _state.search_model_ok:
                logger.warning(
                    f"OpenRouter extraction failed, falling back to Mistral: {exc}"
                )
                mistral_prompt = _build_extraction_system_prompt(good_with, bad_with, [])
                raw_filters, raw_output = _extract_filters_mistral(query, mistral_prompt)
            else:
                raise
    else:
        raw_filters, raw_output = _extract_filters_mistral(query, system_prompt)

    # Validator always gates on the full allowed-list regardless of
    # backend — even when the prompt was lean, the LLM's output gets
    # gated against breeds that actually exist in the DB.
    cleaned = _postprocess_filters(
        raw_filters, set(good_with), set(bad_with), set(breed_allowed)
    )
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
    # Top breed per method group (image, cat_similarity) — kept separate
    # because the two methods' confidence values aren't comparable.
    inferred_breed_top: InferredBreedTop
    # Full list of inferred breed rows (image, image_2nd, cat_similarity,
    # cat_similarity_2nd). Up to 4 entries; may be empty.
    inferred_breeds: list[InferredBreedOut]
    fur_en: str | None
    fur_from_desc: str | None
    weight: str | None
    weight_from_desc: str | None
    thumbnail: str | None


def _to_inferred_breed_out(ib) -> InferredBreedOut | None:
    if ib is None:
        return None
    return InferredBreedOut(
        method=ib.method,
        value=ib.value,
        confidence=ib.confidence,
        model_name=ib.model_name,
    )


def _top_inferred_breed(dog) -> InferredBreedTop:
    """Return the top breed per method group (image, cat_similarity).

    Each method's "top" is its non-`_2nd` row — by construction `image`'s
    softmax probability is always higher than `image_2nd`'s, and
    `cat_similarity` carries the same dog-level coverage as `_2nd` but
    is the primary winner.
    """
    by_method = {ib.method: ib for ib in dog.inferred_breeds}
    return InferredBreedTop(
        image=_to_inferred_breed_out(by_method.get("image")),
        cat_similarity=_to_inferred_breed_out(by_method.get("cat_similarity")),
    )


def _inferred_breeds_list(dog) -> list[InferredBreedOut]:
    """Return all inferred breed rows for a dog as Pydantic objects."""
    return [
        _to_inferred_breed_out(ib)
        for ib in dog.inferred_breeds
    ]


class SearchResponse(BaseModel):
    query: str
    extracted_filters: dict
    raw_model_output: str  # TEMPORARY — remove after testing
    total: int
    dogs: list[DogSummaryOut]


@app.post("/api/dogs/search", response_model=SearchResponse)
def search_dogs(req: SearchRequest):
    """Natural language search: extract filters via LLM then query the DB."""
    from sqlalchemy import or_, select
    from sqlalchemy.orm import selectinload

    from .database.models import Dog, InferredDogBreed
    from .enrichment.normalizers import normalize_age, normalize_weight

    backend = get_search_backend()
    if backend == "mistral" and not _state.search_model_ok:
        raise HTTPException(status_code=503, detail="Search model not available")

    from .enrichment.groq_client import GroqError
    from .enrichment.openrouter_client import OpenRouterError
    try:
        extracted, raw_output = _extract_filters(req.query)
    except GroqError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Groq extraction failed: {exc}",
        ) from exc
    except OpenRouterError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"OpenRouter extraction failed: {exc}",
        ) from exc

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        q = select(Dog).options(
            selectinload(Dog.images),
            selectinload(Dog.inferred_breeds),
        ).where(Dog.superseded_at.is_(None))

        # SQL-level filters from extracted fields. Same merge rule as
        # /api/filter-dogs — see `_eq_resolved` for the rationale.
        if gender := extracted.get("gender"):
            q = q.where(_eq_resolved(Dog.gender_en, Dog.gender_from_desc, gender))
        if size := extracted.get("size"):
            q = q.where(_eq_resolved(Dog.size_en, Dog.size_from_desc, size))
        breeds = extracted.get("breed")
        if breeds:
            # `extracted["breed"]` is a list of candidates the LLM nominated
            # from the allowed list (str input tolerated for safety). Each
            # candidate fires two branches; the union is OR'd:
            #  - claimed columns (breed_en / breed_from_desc) via substring
            #    (so a candidate "Labrador" matches "Labrador mix")
            #  - InferredDogBreed.value for method='image' via exact match
            #    (AI-detected, canonical AKC, same source that fed the prompt)
            if isinstance(breeds, str):
                breeds = [breeds]
            breed_clauses = [
                or_(
                    _ilike_resolved(Dog.breed_en, Dog.breed_from_desc, f"%{b}%"),
                    select(InferredDogBreed.id).where(
                        InferredDogBreed.dog_id == Dog.id,
                        InferredDogBreed.value == b,
                        InferredDogBreed.method == "image",
                    ).exists(),
                )
                for b in breeds
            ]
            q = q.where(or_(*breed_clauses))
        if fur := extracted.get("fur"):
            q = q.where(_eq_resolved(Dog.fur_en, Dog.fur_from_desc, fur))
        # good_with / bad_with may be lists or strings — AND condition for each value
        gw_val = extracted.get("good_with") or []
        if isinstance(gw_val, str):
            gw_val = [gw_val]
        for gw in gw_val:
            q = q.where(_like_resolved(Dog.good_with_en, Dog.good_with_from_desc, f'%"{gw}"%'))
        bw_val = extracted.get("bad_with") or []
        if isinstance(bw_val, str):
            bw_val = [bw_val]
        for bw in bw_val:
            q = q.where(_like_resolved(Dog.bad_with_en, Dog.bad_with_from_desc, f'%"{bw}"%'))

        dogs = session.execute(q).scalars().all()

        # post-filters — derived categories use the same fallback as the stats cache.
        if age := extracted.get("age"):
            dogs = [d for d in dogs if normalize_age(d.age_en or d.age_from_desc) == age]
        if weight := extracted.get("weight"):
            dogs = [d for d in dogs if normalize_weight(d.weight or d.weight_from_desc) == weight]

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
                inferred_breeds=_inferred_breeds_list(dog),
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


#### POST /api/extract/field

# Mistral counterpart of `groq_extract_field`. Same contract: extract one
# field from an English description, return JSON `{"value": <value>}`.
# The worker passes the field's `value_type` and (for enums/lists) a
# small `allowed_values` list — kept lean to respect Mistral's prompt-size
# budget. The API returns the parsed value untouched; the worker reuses
# the shared coercion in `groq_client._coerce_extracted_value` to enforce
# allowed-value membership.

_EXTRACT_FIELD_PROMPT = """\
[INST] You extract a single field from an English dog adoption listing description.

Rules:
- Output JSON only: {{"value": <value>}}.
- If the description does NOT clearly mention the field, output {{"value": null}}.
- Do NOT guess. Do NOT infer from indirect cues unless the description is explicit.
- For enum fields: output MUST be one of the allowed values verbatim. If the meaning matches none of them, output null.
- For list fields: output a JSON array of allowed values; empty array if none mentioned.
- For free-text fields: output a short concise string verbatim from the description, or null.

Field to extract: {field_name}
{field_meaning}Output type: {value_type}
{allowed_line}
Description:
{description}
[/INST]"""


class ExtractFieldRequest(BaseModel):
    description: str
    field_name: str
    value_type: str  # "enum" | "list" | "string"
    allowed_values: list[str] | None = None
    field_description: str = ""


@app.post("/api/extract/field")
def extract_field(req: ExtractFieldRequest):
    """Extract one field from an English description using Mistral.

    Returns `{"value": <parsed JSON value>, "raw_output": <raw model text>}`.
    Validation against `allowed_values` happens in the caller.

    Mistral is lazy-loaded on first call when both backends are set to
    Groq (Mistral is skipped at startup to save RAM). The worker calls
    `/api/search-model/unload` after the pipeline finishes to free it.
    """
    import json
    import re

    try:
        _ensure_search_model_loaded()
    except Exception as exc:
        logger.error(f"On-demand Mistral load failed: {exc}")
        raise HTTPException(status_code=503, detail=f"Search model unavailable: {exc}")

    desc = (req.description or "").strip()
    if not desc:
        return {"value": None, "raw_output": ""}

    if req.value_type not in ("enum", "list", "string"):
        raise HTTPException(status_code=400, detail=f"unknown value_type: {req.value_type}")
    if req.value_type == "enum" and not req.allowed_values:
        raise HTTPException(status_code=400, detail="enum requires allowed_values")

    field_meaning = f"Field meaning: {req.field_description}\n" if req.field_description else ""
    allowed_line = (
        f"Allowed values (verbatim): {req.allowed_values}\n" if req.allowed_values else ""
    )
    prompt = _EXTRACT_FIELD_PROMPT.format(
        field_name=req.field_name,
        field_meaning=field_meaning,
        value_type=req.value_type,
        allowed_line=allowed_line,
        description=desc,
    )

    llm = _state.search_model
    t0 = time.time()
    output = llm(prompt, max_tokens=200, stop=["[INST]", "\n\n"], temperature=0.0)
    elapsed = time.time() - t0
    raw = output["choices"][0]["text"].strip()
    logger.info(f"Mistral extract {req.field_name} done in {elapsed:.1f}s: {raw!r}")

    def _try_parse(text: str) -> dict | None:
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        return obj if isinstance(obj, dict) else None

    parsed = _try_parse(raw)
    if parsed is None:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = _try_parse(match.group())

    value = parsed.get("value") if parsed else None
    return {"value": value, "raw_output": raw}


#### POST /api/extract/good-bad-with

# Combined extraction of good_with + bad_with in a single Mistral call.
# Mirrors `groq_extract_good_bad_with`. The two lists are extracted
# together so the model can place each topic in exactly one bucket —
# a constraint that's impossible to honor across two independent calls.

_GOOD_BAD_WITH_PROMPT = """\
[INST] You extract two compatibility lists from an English dog adoption listing description.

good_with = things/beings the dog gets along with or is suitable for.
bad_with  = things/beings the dog does NOT get along with or is NOT suitable for.

Rules:
- Output JSON only: {{"good_with": [...], "bad_with": [...]}}.
- Each list contains short lowercase tags like 'children', 'cats', 'other dogs', 'female dogs', 'male dogs', 'elderly', 'people', 'first-time owners', 'apartments without garden', 'small spaces', 'being left alone', 'hunting'.
- Read BOTH explicit compatibility fields and natural-language phrases:
  * 'Compatibility with Dogs: Good with females' -> good_with: 'female dogs'
  * 'Cat Compatibility: Yes' -> good_with: 'cats'
  * 'Cat Compatibility: No' -> bad_with: 'cats'
  * 'Compatibility with Cats: To be evaluated' -> bad_with: 'cats' (treat 'to be evaluated' as a precaution)
  * 'Need for Outdoor Space: Yes' -> bad_with: 'apartments without garden'
  * 'He gets along with X' -> good_with: 'X'
  * 'NOT SUITABLE FOR HUNTING' -> bad_with: 'hunting'
  * 'should not be left alone in a yard 24/7' -> bad_with: 'being left alone'
  * 'Being with people makes me happy' -> good_with: 'people'
- A topic appears in EXACTLY ONE list. Never put the same tag in both.
- Empty array if no signal for that side. Use lowercase tags.

Description:
{description}
[/INST]"""


class GoodBadWithRequest(BaseModel):
    description: str


@app.post("/api/extract/good-bad-with")
def extract_good_bad_with(req: GoodBadWithRequest):
    """Extract good_with + bad_with as a single Mistral call.

    Returns `{"good_with": [...], "bad_with": [...], "raw_output": <text>}`.
    """
    import json
    import re

    try:
        _ensure_search_model_loaded()
    except Exception as exc:
        logger.error(f"On-demand Mistral load failed: {exc}")
        raise HTTPException(status_code=503, detail=f"Search model unavailable: {exc}")

    desc = (req.description or "").strip()
    if not desc:
        return {"good_with": [], "bad_with": [], "raw_output": ""}

    prompt = _GOOD_BAD_WITH_PROMPT.format(description=desc)
    llm = _state.search_model
    t0 = time.time()
    output = llm(prompt, max_tokens=400, stop=["[INST]"], temperature=0.0)
    elapsed = time.time() - t0
    raw = output["choices"][0]["text"].strip()
    logger.info(f"Mistral good/bad_with done in {elapsed:.1f}s: {raw!r}")

    def _try_parse(text: str) -> dict | None:
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        return obj if isinstance(obj, dict) else None

    parsed = _try_parse(raw)
    if parsed is None:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = _try_parse(match.group())

    def _coerce(value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]

    good = _coerce(parsed.get("good_with")) if parsed else []
    bad = _coerce(parsed.get("bad_with")) if parsed else []
    # Defensive dedup mirroring the Groq path.
    if good and bad:
        good_lower = {g.lower() for g in good}
        bad = [b for b in bad if b.lower() not in good_lower]
    return {"good_with": good, "bad_with": bad, "raw_output": raw}


#### POST /api/search-model/unload

@app.post("/api/search-model/unload")
def unload_search_model():
    """Drop the Mistral model from memory.

    Called by the worker after Stage 2/3 completes so Mistral (loaded on
    demand for Groq fallback) doesn't sit in RAM between runs. No-op if
    Mistral isn't loaded.
    """
    was_loaded = _state.search_model_ok
    _unload_search_model()
    return {"unloaded": was_loaded}


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

# 30 s in-memory cache for the remote liveness probes. Health endpoints
# get polled aggressively (load balancers, monitoring, frontend banner)
# — we don't want each poll triggering outbound HTTPS calls.
_REMOTE_PROBE_CACHE_TTL = 30.0
_groq_probe_cache: dict[str, float | bool] = {"at": 0.0, "responsive": False}
_openrouter_probe_cache: dict[str, float | bool] = {"at": 0.0, "responsive": False}


def _groq_responsive_cached() -> bool:
    """Cached `is_responsive()` probe — refreshed at most once per 30 s."""
    from .enrichment.groq_client import is_responsive

    now = time.time()
    if (now - float(_groq_probe_cache["at"])) < _REMOTE_PROBE_CACHE_TTL:
        return bool(_groq_probe_cache["responsive"])

    result = is_responsive()
    _groq_probe_cache["at"] = now
    _groq_probe_cache["responsive"] = result
    return result


def _openrouter_responsive_cached() -> bool:
    """Cached `is_responsive()` probe for OpenRouter — same 30 s TTL pattern."""
    from .enrichment.openrouter_client import is_responsive

    now = time.time()
    if (now - float(_openrouter_probe_cache["at"])) < _REMOTE_PROBE_CACHE_TTL:
        return bool(_openrouter_probe_cache["responsive"])

    result = is_responsive()
    _openrouter_probe_cache["at"] = now
    _openrouter_probe_cache["responsive"] = result
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
    extract_backend = get_extract_backend()
    groq_in_use = any_backend_uses_groq()
    openrouter_in_use = any_backend_uses_openrouter()
    groq_configured = bool((os.environ.get("GROQ_API_KEY") or "").strip())
    openrouter_configured = bool((os.environ.get("OPENROUTER_API_KEY") or "").strip())

    # Only probe each remote when at least one backend actually uses it —
    # otherwise don't make outbound calls the operator didn't ask for.
    if groq_in_use and groq_configured:
        groq_responsive: bool | None = _groq_responsive_cached()
    elif groq_in_use:
        groq_responsive = False  # backend=groq but key missing
    else:
        groq_responsive = None

    if openrouter_in_use and openrouter_configured:
        openrouter_responsive: bool | None = _openrouter_responsive_cached()
    elif openrouter_in_use:
        openrouter_responsive = False
    else:
        openrouter_responsive = None

    # Active search backend usable?
    if search_backend == "mistral":
        search_ok = _state.search_model_ok
    elif search_backend == "groq":
        search_ok = groq_configured and bool(groq_responsive)
    else:  # openrouter
        search_ok = openrouter_configured and bool(openrouter_responsive)

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
            "openrouter": {
                "configured": openrouter_configured,
                "responsive": openrouter_responsive,
            },
        },
        "backends": {
            "search": search_backend,
            "translation": translation_backend,
            "extract": extract_backend,
        },
    }
