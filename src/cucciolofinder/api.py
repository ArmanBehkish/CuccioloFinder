import asyncio
import os
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

# .78 B Param Model, change in env if no mem
SEARCH_MODEL_ID = os.environ.get("SEARCH_MODEL_ID", "google/flan-t5-large")

#### App state

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

def _probe_db() -> None:
    """Blocking: create engine, run a trivial query to confirm DB is reachable."""
    _state.engine = get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(_state.engine)
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    _state.db_ok = True


def _load_search_model() -> None:
    """Blocking: load the search model from disk into memory."""
    from pathlib import Path
    from transformers import pipeline as hf_pipeline

    models_dir = Path(os.environ.get("MODELS_PATH", "data/models"))
    cache_dir = models_dir / SEARCH_MODEL_ID.replace("/", "--")
    cache_dir.mkdir(parents=True, exist_ok=True)

    _state.search_model = hf_pipeline(
        "text2text-generation",
        model=SEARCH_MODEL_ID,
        model_kwargs={"cache_dir": str(cache_dir)},
        device="cpu",
    )
    _state.search_model_ok = True


def _dispose_engine() -> None:
    """Blocking: close all connections in the pool."""
    if _state.engine is not None:
        _state.engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """only for context manager send blockings to threads"""
    # Startup
    try:
        await asyncio.to_thread(_probe_db)
        logger.info("DB connection OK")
    except Exception as exc:
        logger.warning(f"DB not reachable at startup: {exc}")
        _state.db_ok = False

    try:
        await asyncio.to_thread(_load_search_model)
        logger.info(f"Search model {SEARCH_MODEL_ID} loaded OK")
    except Exception as exc:
        logger.warning(f"Search model not loaded at startup: {exc}")
        _state.search_model_ok = False

    if _state.db_ok:
        try:
            await asyncio.to_thread(_reload_caches)
        except Exception as exc:
            logger.warning(f"Cache load failed at startup: {exc}")

    yield

    # Shutdown
    await asyncio.to_thread(_dispose_engine)
    logger.info("DB connection pool disposed")

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

    from .database.models import Dog
    from .enrichment.profile_builder import normalize_age, normalize_weight

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        # enums cache
        enums: dict = {}

        def distinct_non_null(col):
            rows = session.execute(
                select(distinct(col)).where(col.isnot(None)).order_by(col)
            ).scalars().all()
            return [r for r in rows if r]

        enums["source_site"] = distinct_non_null(Dog.source_site)
        enums["gender_en"] = distinct_non_null(Dog.gender_en)
        enums["size_en"] = distinct_non_null(Dog.size_en)
        enums["breed_en"] = distinct_non_null(Dog.breed_en)
        enums["age_en"] = distinct_non_null(Dog.age_en)
        enums["fur_en"] = distinct_non_null(Dog.fur_en)
        enums["microchip_en"] = distinct_non_null(Dog.microchip_en)
        enums["sterilization_en"] = distinct_non_null(Dog.sterilization_en)
        enums["vaccine_en"] = distinct_non_null(Dog.vaccine_en)
        enums["deworming_en"] = distinct_non_null(Dog.deworming_en)

        # age_category: derived from age_en
        age_cats: set[str] = set()
        for (age_en,) in session.execute(
            select(Dog.age_en).where(Dog.age_en.isnot(None))
        ).all():
            cat = normalize_age(age_en)
            if cat:
                age_cats.add(cat)
        enums["age_category"] = sorted(age_cats)

        # weight categories: derived from weight column
        weight_cats: set[str] = set()
        for (w,) in session.execute(
            select(Dog.weight).where(Dog.weight.isnot(None))
        ).all():
            cat = normalize_weight(w)
            if cat:
                weight_cats.add(cat)
        enums["weight"] = sorted(weight_cats)

        # good_with_en / bad_with_en: flatten JSON arrays
        def flatten_json_array(col):
            values: set[str] = set()
            for (arr,) in session.execute(select(col).where(col.isnot(None))).all():
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

        # date ranges
        min_post, max_post = session.execute(
            select(func.min(Dog.post_date), func.max(Dog.post_date))
        ).one()
        enums["post_date"] = {
            "min": str(min_post) if min_post else None,
            "max": str(max_post) if max_post else None,
        }

        min_ss, max_ss = session.execute(
            select(func.min(Dog.shelter_since), func.max(Dog.shelter_since)).where(
                Dog.shelter_since.isnot(None)
            )
        ).one()
        enums["shelter_since"] = {
            "min": min_ss,
            "max": max_ss,
        }

        # populate enums cache
        _state.enums_cache = enums

        # stats cache
        dogs_rows = session.execute(select(Dog)).scalars().all()

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
    return _state.enums_cache


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
        raise HTTPException(status_code=503, detail="Database unreachable")

    try:
        total = _reload_caches()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cache reload failed: {exc}") from exc

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
    limit: int = Field(default=30, ge=1, le=100)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1)


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
    from .enrichment.profile_builder import normalize_age, normalize_weight

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        q = select(Dog).options(selectinload(Dog.images))

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

    # Cap at limit, then paginate within that pool
    dogs = dogs[: params.limit]
    total = len(dogs)
    page_size = min(params.page_size, params.limit)
    offset = (params.page - 1) * page_size
    page_dogs = dogs[offset : offset + page_size]

    dog_list = []
    for dog in page_dogs:
        thumbnail = None
        if dog.images:
            first = min(
                dog.images,
                key=lambda img: img.position if img.position is not None else 999,
            )
            thumbnail = _image_url(first)
        dog_list.append({
            "id": dog.id,
            "name": dog.name,
            "source_site": dog.source_site,
            "gender_en": dog.gender_en,
            "age_en": dog.age_en,
            "size_en": dog.size_en,
            "breed_en": dog.breed_en,
            "fur_en": dog.fur_en,
            "weight": dog.weight,
            "thumbnail": thumbnail,
        })

    return {
        "total": total,
        "page": params.page,
        "page_size": page_size,
        "dogs": dog_list,
    }


#### GET /api/dogs/{id}

class DogImageOut(BaseModel):
    url: str
    position: int | None


class DogProfileOut(BaseModel):
    id: int
    name: str
    source_site: str
    source_url: str
    description_en: str | None
    gender_en: str | None
    age_en: str | None
    size_en: str | None
    breed_en: str | None
    fur_en: str | None
    weight: str | None
    microchip_en: str | None
    sterilization_en: str | None
    vaccine_en: str | None
    deworming_en: str | None
    good_with_en: list[str] | None
    bad_with_en: list[str] | None
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
            select(Dog).where(Dog.id == dog_id).options(selectinload(Dog.images))
        ).scalar_one_or_none()

    if dog is None:
        raise HTTPException(status_code=404, detail=f"Dog {dog_id} not found")

    return DogProfileOut(
        id=dog.id,
        name=dog.name,
        source_site=dog.source_site,
        source_url=dog.source_url,
        description_en=dog.description_en,
        gender_en=dog.gender_en,
        age_en=dog.age_en,
        size_en=dog.size_en,
        breed_en=dog.breed_en,
        fur_en=dog.fur_en,
        weight=dog.weight,
        microchip_en=dog.microchip_en,
        sterilization_en=dog.sterilization_en,
        vaccine_en=dog.vaccine_en,
        deworming_en=dog.deworming_en,
        good_with_en=dog.good_with_en,
        bad_with_en=dog.bad_with_en,
        post_date=str(dog.post_date) if dog.post_date else None,
        shelter_since=dog.shelter_since,
        images=[
            DogImageOut(url=_image_url(img), position=img.position)
            for img in sorted(dog.images, key=lambda img: img.position if img.position is not None else 999)
        ],
    )


#### POST /api/dogs/search

# 2-shot extraction prompt
_EXTRACTION_PROMPT = """\
Extract dog search preferences from this text as JSON.
Valid fields and values:
- size: small, medium, large, giant
- gender: male, female
- fur: short, medium, long
- weight: very light, light, medium, heavy, very heavy
- age: puppy, young, adult, senior
- breed: any breed name
- good_with: list of e.g. children, elderly, cats, dogs
- bad_with: list of e.g. children, cats, dogs
Only include fields that are clearly mentioned or implied. Return only valid JSON.

Text: "I'm looking for a big male dog with long fur, maybe a German Shepherd, that's good with elderly people but not with cats"
JSON: {"size": "large", "gender": "male", "fur": "long", "breed": "German Shepherd", "good_with": ["elderly"], "bad_with": ["cats"]}

Text: "We need a lightweight puppy for our apartment, preferably vaccinated and good with our two kids"
JSON: {"weight": "light", "age": "puppy", "good_with": ["children"]}

Text: "<USER_QUERY>"
JSON:"""


def _extract_filters(query: str) -> dict:
    """Run the LLM on the query and return a dict of extracted filter fields."""
    import json
    import re

    prompt = _EXTRACTION_PROMPT.replace("<USER_QUERY>", query)
    raw = _state.search_model(prompt, max_new_tokens=128)[0]["generated_text"].strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fall back: find the first {...} block in the output
    match = re.search(r"\{[^{}]*\}", raw)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {}


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)


class DogSummaryOut(BaseModel):
    id: int
    name: str
    source_site: str
    gender_en: str | None
    age_en: str | None
    size_en: str | None
    breed_en: str | None
    fur_en: str | None
    weight: str | None
    thumbnail: str | None


class SearchResponse(BaseModel):
    query: str
    extracted_filters: dict
    total: int
    dogs: list[DogSummaryOut]


@app.post("/api/dogs/search", response_model=SearchResponse)
def search_dogs(req: SearchRequest):
    """Natural language search: extract filters via LLM then query the DB."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from .database.models import Dog
    from .enrichment.profile_builder import normalize_age, normalize_weight

    if not _state.search_model_ok:
        raise HTTPException(status_code=503, detail="Search model not available")

    extracted = _extract_filters(req.query)

    engine = _state.engine or get_engine(DEFAULT_DB_PATH)
    SessionLocal = get_session(engine)

    with SessionLocal() as session:
        q = select(Dog).options(selectinload(Dog.images))

        # SQL-level filters from extracted fields
        if gender := extracted.get("gender"):
            q = q.where(Dog.gender_en == gender)
        if size := extracted.get("size"):
            q = q.where(Dog.size_en == size)
        if breed := extracted.get("breed"):
            q = q.where(Dog.breed_en.ilike(f"%{breed}%"))
        if fur := extracted.get("fur"):
            q = q.where(Dog.fur_en == fur)
        # good_with / bad_with may be lists — AND condition for each value
        for gw in extracted.get("good_with") or []:
            q = q.where(Dog.good_with_en.like(f'%"{gw}"%'))
        for bw in extracted.get("bad_with") or []:
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
            age_en=dog.age_en,
            size_en=dog.size_en,
            breed_en=dog.breed_en,
            fur_en=dog.fur_en,
            weight=dog.weight,
            thumbnail=thumbnail,
        ))

    return SearchResponse(
        query=req.query,
        extracted_filters=extracted,
        total=len(dog_list),
        dogs=dog_list,
    )


#### GET /api/health

@app.get("/api/health")
def health():
    """Health check: server + DB + search model readiness."""
    db_ok = False
    try:
        engine = _state.engine or get_engine(DEFAULT_DB_PATH)
        SessionLocal = get_session(engine)
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    _state.db_ok = db_ok

    all_ok = _state.db_ok and _state.search_model_ok
    return {
        "status": "ok" if all_ok else "degraded",
        "db": _state.db_ok,
        "search_model": _state.search_model_ok,
    }
