"""Categorical-similarity breed inference.

Per-dimension typed similarity (ordinal / nominal-with-similarity-matrix /
IDF-Jaccard) weighted by information gain over the AKC reference. Replaces
the deprecated text-embedding pipeline.

Layout:
    1. Dual-source dimension resolvers (size_en + size_from_desc → bucket)
    2. Static vocabularies + similarity functions + nominal matrices
    3. AKC index loader + IG weight computation (per `run()` invocation)
    4. Per-dog scoring loop with skip + top-2 row writes
"""

import csv
import math
import os
from collections import Counter
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.config import CAT_SIMILARITY_MIN_COVERAGE
from cucciolofinder.database import Breed, Dog, InferredDogBreed

from ..normalizers import (
    kg_to_category,
    normalize_fur,
    normalize_size,
    parse_weight_kg,
)
from .profile_builder import (
    DEMEANOR_LABELS,
    ENERGY_LABELS,
    TEMPERAMENT_META,
    TRAINABILITY_LABELS,
    akc_grooming_to_coat,
    akc_height_to_size,
    akc_temperament_to_meta,
    akc_weight_to_category,
)

AKC_CSV = Path(os.environ.get("AKC_CSV_PATH", "data/datasets/akc-data-latest.csv"))

MODEL_NAME = "cat-similarity-v1"


# =============================================================================
# Section 1 — Dual-source dimension resolvers
# =============================================================================
#
# Rules (size example):
#   - equal values                          → that value
#   - one is a compound hedge ("medium-large", "medio-grande", …) and
#     the other is an exact bucket          → prefer the exact bucket
#   - both exact but disagree               → prefer the larger
#     (adult-size bias, consistent with the Stage-2 extract prompt)
#   - only one source populated             → normalize that one alone

_SIZE_COMPOUND = frozenset({
    "medium-small", "medio-piccola",
    "medium-large", "medio-grande",
    "medium contained", "media contenuta",
})

_SIZE_RANK: dict[str, int] = {"small": 0, "medium": 1, "large": 2, "giant": 3}
_FUR_RANK: dict[str, int] = {"short": 0, "medium": 1, "long": 2}


def resolve_size(size_en: str | None, size_from_desc: str | None) -> str | None:
    return _resolve_categorical(
        size_en, size_from_desc, _SIZE_COMPOUND, _SIZE_RANK, normalize_size
    )


def resolve_fur(fur_en: str | None, fur_from_desc: str | None) -> str | None:
    return _resolve_categorical(
        fur_en, fur_from_desc, frozenset(), _FUR_RANK, normalize_fur
    )


def resolve_weight(
    weight: str | None, weight_from_desc: str | None
) -> str | None:
    """Combine weight + weight_from_desc kg strings into a category.

    Take the larger parsed kg value (adult-weight bias), bin via
    `kg_to_category`. Returns None when neither parses to a number.
    """
    kg_a = parse_weight_kg(weight)
    kg_b = parse_weight_kg(weight_from_desc)
    candidates = [k for k in (kg_a, kg_b) if k is not None]
    if not candidates:
        return None
    return kg_to_category(max(candidates))


def _resolve_categorical(
    a_raw: str | None,
    b_raw: str | None,
    compound_set: frozenset[str],
    rank: dict[str, int],
    normalize,
) -> str | None:
    a_key = (a_raw or "").strip().lower() or None
    b_key = (b_raw or "").strip().lower() or None

    if a_key is None and b_key is None:
        return None
    if a_key is None:
        return normalize(b_key)
    if b_key is None:
        return normalize(a_key)

    a_norm = normalize(a_key)
    b_norm = normalize(b_key)
    if a_norm is None:
        return b_norm
    if b_norm is None:
        return a_norm
    if a_norm == b_norm:
        return a_norm

    a_compound = a_key in compound_set
    b_compound = b_key in compound_set
    if a_compound and not b_compound:
        return b_norm
    if b_compound and not a_compound:
        return a_norm
    return a_norm if rank[a_norm] >= rank[b_norm] else b_norm


# =============================================================================
# Section 2 — Vocabularies + similarity functions
# =============================================================================

# Ordered low-to-high. Used by `_sim_ordinal`.
_SIZE_LEVELS: tuple[str, ...] = ("small", "medium", "large", "giant")
_FUR_LEVELS: tuple[str, ...] = ("short", "medium", "long")
_WEIGHT_LEVELS: tuple[str, ...] = (
    "very light", "light", "medium", "heavy", "very heavy",
)
_ENERGY_LEVELS: tuple[str, ...] = tuple(ENERGY_LABELS)


# ---- Nominal similarity matrices (hand-coded, symmetric, diagonal=1.0) ----
#
# Trainability — clusters: cooperative {Agreeable, Eager, Easy} vs.
# resistant {Independent, May be Stubborn}.
#
#                    Agree  Eager  Easy   Indep  Stub
# Agreeable          1.0    0.7    0.6    0.4    0.3
# Eager to Please    0.7    1.0    0.8    0.2    0.1
# Easy Training      0.6    0.8    1.0    0.3    0.2
# Independent        0.4    0.2    0.3    1.0    0.7
# May be Stubborn    0.3    0.1    0.2    0.7    1.0

_TRAINABILITY_SIM: dict[tuple[str, str], float] = {
    ("Agreeable", "Eager to Please"):       0.7,
    ("Agreeable", "Easy Training"):         0.6,
    ("Agreeable", "Independent"):           0.4,
    ("Agreeable", "May be Stubborn"):       0.3,
    ("Eager to Please", "Easy Training"):   0.8,
    ("Eager to Please", "Independent"):     0.2,
    ("Eager to Please", "May be Stubborn"): 0.1,
    ("Easy Training", "Independent"):       0.3,
    ("Easy Training", "May be Stubborn"):   0.2,
    ("Independent", "May be Stubborn"):     0.7,
}

# Demeanor — clusters: extroverted {Friendly, Outgoing} vs. cautious
# {Aloof/Wary, Reserved}; Alert/Responsive is roughly orthogonal.
#
#                            Alert  Aloof  Friend  Outgo  Reserv
# Alert/Responsive           1.0    0.3    0.5     0.5    0.4
# Aloof/Wary                 0.3    1.0    0.1     0.1    0.7
# Friendly                   0.5    0.1    1.0     0.8    0.3
# Outgoing                   0.5    0.1    0.8     1.0    0.2
# Reserved with Strangers    0.4    0.7    0.3     0.2    1.0

_DEMEANOR_SIM: dict[tuple[str, str], float] = {
    ("Alert/Responsive", "Aloof/Wary"):              0.3,
    ("Alert/Responsive", "Friendly"):                0.5,
    ("Alert/Responsive", "Outgoing"):                0.5,
    ("Alert/Responsive", "Reserved with Strangers"): 0.4,
    ("Aloof/Wary", "Friendly"):                      0.1,
    ("Aloof/Wary", "Outgoing"):                      0.1,
    ("Aloof/Wary", "Reserved with Strangers"):       0.7,
    ("Friendly", "Outgoing"):                        0.8,
    ("Friendly", "Reserved with Strangers"):         0.3,
    ("Outgoing", "Reserved with Strangers"):         0.2,
}


def _sim_ordinal(a: str, b: str, levels: tuple[str, ...]) -> float:
    """Linear ordinal: 1 - dist/(N-1). Returns 0 if either value is off-vocab."""
    if a == b:
        return 1.0
    try:
        pos_a = levels.index(a)
        pos_b = levels.index(b)
    except ValueError:
        return 0.0
    if len(levels) <= 1:
        return 0.0
    return 1.0 - abs(pos_a - pos_b) / (len(levels) - 1)


def _sim_nominal(a: str, b: str, table: dict[tuple[str, str], float]) -> float:
    """Hand-coded nominal similarity. Symmetric; diagonal=1.0."""
    if a == b:
        return 1.0
    return table.get((a, b)) if (a, b) in table else table.get((b, a), 0.0)


def _sim_temperament(
    a: list[str] | None,
    b: list[str] | None,
    idf: dict[str, float],
) -> float:
    """IDF-weighted Jaccard over temperament meta-categories."""
    set_a = set(a) if a else set()
    set_b = set(b) if b else set()
    union = set_a | set_b
    if not union:
        return 0.0
    intersection = set_a & set_b
    num = sum(idf.get(t, 0.0) for t in intersection)
    denom = sum(idf.get(t, 0.0) for t in union)
    if denom == 0:
        return 0.0
    return num / denom


# =============================================================================
# Section 3 — AKC index + IG weights
# =============================================================================

# Order of dimensions for logging consistency.
DIMENSIONS: tuple[str, ...] = (
    "size", "fur", "weight",
    "energy_level", "trainability", "demeanor",
    "temperament",
)


def _build_akc_index(csv_path: Path = AKC_CSV) -> dict[str, dict]:
    """Project each AKC breed onto the 7-dim shared vocabulary.

    Returns: {breed: {size, fur, weight, energy_level, trainability,
                      demeanor, temperament, popularity}}
    Each dim is None when the AKC field is missing/unparseable. Popularity
    is an int rank (1=most popular) or None — used for tie-breaking only,
    not for similarity scoring.
    """
    index: dict[str, dict] = {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            breed = (row.get("") or "").strip()
            if not breed:
                continue

            try:
                size = akc_height_to_size(
                    float(row["min_height"]), float(row["max_height"])
                )
            except (KeyError, ValueError):
                size = None
            try:
                weight = akc_weight_to_category(
                    float(row["min_weight"]), float(row["max_weight"])
                )
            except (KeyError, ValueError):
                weight = None

            fur = akc_grooming_to_coat(row.get("grooming_frequency_category"))
            energy = (row.get("energy_level_category") or "").strip() or None
            train = (row.get("trainability_category") or "").strip() or None
            demeanor = (row.get("demeanor_category") or "").strip() or None
            temperament_list = akc_temperament_to_meta(row.get("temperament"))
            temperament: list[str] | None = (
                temperament_list if temperament_list else None
            )

            try:
                popularity = int(row["popularity"])
            except (KeyError, ValueError):
                popularity = None

            index[breed] = {
                "size": size,
                "fur": fur,
                "weight": weight,
                "energy_level": energy,
                "trainability": train,
                "demeanor": demeanor,
                "temperament": temperament,
                "popularity": popularity,
            }
    return index


def _compute_weights(
    akc_index: dict[str, dict],
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    """Compute IG weights + temperament IDF + per-dim N_eff.

    Returns: (weights, temperament_idf, n_eff)
    - weights[dim] = IG bits over AKC for the 6 categorical dims; for
      `temperament`, sum of per-trait binary IGs (Option A from the doc).
    - temperament_idf[trait] = log(N / df(trait)); used inside the Jaccard.
    - n_eff[dim] = number of AKC breeds with that dim non-null.
    """
    weights: dict[str, float] = {}
    n_eff: dict[str, int] = {}

    # Single-value dims: 6 of them.
    for dim in ("size", "fur", "weight", "energy_level", "trainability", "demeanor"):
        values = [b[dim] for b in akc_index.values() if b[dim] is not None]
        n = len(values)
        n_eff[dim] = n
        if n == 0:
            weights[dim] = 0.0
            continue
        h_y = math.log2(n)
        counts = Counter(values)
        h_y_x = sum((c / n) * math.log2(c) for c in counts.values())
        weights[dim] = max(0.0, h_y - h_y_x)

    # Temperament: per-trait binary IG, summed (independence approximation).
    temp_breeds = [b["temperament"] for b in akc_index.values() if b["temperament"]]
    n_temp = len(temp_breeds)
    n_eff["temperament"] = n_temp

    temperament_idf: dict[str, float] = {}
    temp_weight = 0.0
    if n_temp > 0:
        for trait in TEMPERAMENT_META:
            df = sum(1 for traits in temp_breeds if trait in traits)
            if df == 0 or df == n_temp:
                # Universal or absent trait — no information gain, no IDF signal.
                temperament_idf[trait] = 0.0
                continue
            p_has = df / n_temp
            p_lacks = (n_temp - df) / n_temp
            h_y_x = p_has * math.log2(df) + p_lacks * math.log2(n_temp - df)
            ig_t = max(0.0, math.log2(n_temp) - h_y_x)
            temperament_idf[trait] = math.log(n_temp / df)
            temp_weight += ig_t
    weights["temperament"] = temp_weight

    return weights, temperament_idf, n_eff


def _log_weights(
    weights: dict[str, float],
    n_eff: dict[str, int],
    n_total: int,
    temperament_idf: dict[str, float],
) -> None:
    """Emit a clear weight summary at the top of every run."""
    logger.info("cat_similarity weights (IG bits over AKC reference):")
    total_w = sum(weights.values())
    for dim in DIMENSIONS:
        w = weights.get(dim, 0.0)
        share = (w / total_w * 100) if total_w > 0 else 0.0
        logger.info(
            f"  {dim:14s}  IG={w:5.3f}  "
            f"({share:4.1f}% of total)  N_eff={n_eff.get(dim, 0)}/{n_total}"
        )
    logger.info(f"  total_weight = {total_w:.3f}")
    nonzero_idf = sorted(
        ((t, v) for t, v in temperament_idf.items() if v > 0),
        key=lambda kv: -kv[1],
    )
    if nonzero_idf:
        logger.info("  temperament IDF (rare → more diagnostic):")
        for trait, v in nonzero_idf:
            logger.info(f"    {trait:15s}  idf={v:.3f}")


# =============================================================================
# Section 4 — Per-dog scoring + run loop
# =============================================================================


def _acquire_dog_dims(dog: Dog) -> dict[str, object]:
    """Read the 7 dims for one dog, treating "" / [] sentinels as None."""
    energy = dog.energy_level_from_desc or None
    train = dog.trainability_from_desc or None
    demeanor = dog.demeanor_from_desc or None
    temperament = dog.temperament_from_desc or None  # [] is falsy → None
    return {
        "size": resolve_size(dog.size_en, dog.size_from_desc),
        "fur": resolve_fur(dog.fur_en, dog.fur_from_desc),
        "weight": resolve_weight(dog.weight, dog.weight_from_desc),
        "energy_level": energy,
        "trainability": train,
        "demeanor": demeanor,
        "temperament": temperament,
    }


def _coverage(
    dog_dims: dict[str, object],
    weights: dict[str, float],
) -> tuple[float, list[str]]:
    """Return (fractional coverage, list of present dims)."""
    total = sum(weights.values())
    if total == 0:
        return 0.0, []
    present_w = 0.0
    present_dims: list[str] = []
    for dim, w in weights.items():
        if dog_dims.get(dim) is not None:
            present_w += w
            present_dims.append(dim)
    return present_w / total, present_dims


def _score_breed(
    dog_dims: dict[str, object],
    breed_dims: dict[str, object],
    weights: dict[str, float],
    temperament_idf: dict[str, float],
) -> tuple[float, float] | None:
    """Score one (dog, breed) pair on the dim intersection.

    Returns (score, denom) — score in [0, 1], denom is the sum of weights
    for the intersected dims. Returns None when there is no overlap.
    """
    numer = 0.0
    denom = 0.0

    for dim, levels in (
        ("size", _SIZE_LEVELS),
        ("fur", _FUR_LEVELS),
        ("weight", _WEIGHT_LEVELS),
        ("energy_level", _ENERGY_LEVELS),
    ):
        d_val = dog_dims.get(dim)
        b_val = breed_dims.get(dim)
        if d_val is None or b_val is None:
            continue
        sim = _sim_ordinal(d_val, b_val, levels)
        w = weights[dim]
        numer += w * sim
        denom += w

    for dim, table in (
        ("trainability", _TRAINABILITY_SIM),
        ("demeanor", _DEMEANOR_SIM),
    ):
        d_val = dog_dims.get(dim)
        b_val = breed_dims.get(dim)
        if d_val is None or b_val is None:
            continue
        sim = _sim_nominal(d_val, b_val, table)
        w = weights[dim]
        numer += w * sim
        denom += w

    d_temp = dog_dims.get("temperament")
    b_temp = breed_dims.get("temperament")
    if d_temp and b_temp:
        sim = _sim_temperament(d_temp, b_temp, temperament_idf)
        w = weights["temperament"]
        numer += w * sim
        denom += w

    if denom == 0:
        return None
    return numer / denom, denom


def _rank_breeds(
    dog_dims: dict[str, object],
    akc_index: dict[str, dict],
    valid_breed_names: set[str],
    weights: dict[str, float],
    temperament_idf: dict[str, float],
) -> list[tuple[float, str, int]]:
    """Score every AKC breed against the dog. Sort: score desc, then
    popularity asc (lower rank = more popular = wins ties), then breed
    name asc for full determinism.
    Only includes breeds present in the seeded `breeds` table — keeps the
    FK on `inferred_dog_breeds.value` valid.
    """
    scored: list[tuple[float, str, int]] = []
    for breed_name, breed_dims in akc_index.items():
        if breed_name not in valid_breed_names:
            continue
        result = _score_breed(dog_dims, breed_dims, weights, temperament_idf)
        if result is None:
            continue
        score, _ = result
        # Missing popularity → least popular (loses ties).
        popularity = breed_dims.get("popularity")
        pop_key = popularity if popularity is not None else 9999
        scored.append((score, breed_name, pop_key))

    scored.sort(key=lambda t: (-t[0], t[2], t[1]))
    return scored


def run(session: Session) -> int:
    """Score active dogs against AKC and write top-2 breeds to inferred_dog_breeds."""
    from .dispatcher import upsert_inferred_breed

    logger.info("cat_similarity: building AKC index...")
    akc = _build_akc_index()
    if not akc:
        logger.warning("cat_similarity: AKC index empty — skipping pipeline")
        return 0

    weights, temperament_idf, n_eff = _compute_weights(akc)
    _log_weights(weights, n_eff, len(akc), temperament_idf)

    valid_breed_names = {b.name for b in session.query(Breed).all()}
    if not valid_breed_names:
        logger.warning("cat_similarity: no breeds seeded — skipping pipeline")
        return 0

    dogs = session.query(Dog).filter(Dog.superseded_at.is_(None)).all()
    already_scored = {
        row[0]
        for row in session.query(InferredDogBreed.dog_id)
        .filter(
            InferredDogBreed.method == "cat_similarity",
            InferredDogBreed.model_name == MODEL_NAME,
        )
        .all()
    }
    dogs_to_score = [d for d in dogs if d.id not in already_scored]
    logger.info(
        f"cat_similarity: {len(dogs)} active dogs, "
        f"{len(dogs) - len(dogs_to_score)} already scored (skipping), "
        f"{len(dogs_to_score)} to score"
    )
    if not dogs_to_score:
        return 0

    rows_written = 0
    skipped_low_coverage = 0
    skipped_no_breeds = 0

    for dog in dogs_to_score:
        dog_dims = _acquire_dog_dims(dog)
        coverage, present_dims = _coverage(dog_dims, weights)

        if coverage < CAT_SIMILARITY_MIN_COVERAGE:
            logger.info(
                f"[{dog.name}] cat_similarity skipped: coverage={coverage:.3f} "
                f"< min={CAT_SIMILARITY_MIN_COVERAGE} (present: {present_dims})"
            )
            skipped_low_coverage += 1
            continue

        ranked = _rank_breeds(
            dog_dims, akc, valid_breed_names, weights, temperament_idf
        )
        if not ranked:
            logger.info(f"[{dog.name}] cat_similarity skipped: no scoreable breeds")
            skipped_no_breeds += 1
            continue

        top1 = ranked[0]
        top2 = ranked[1] if len(ranked) > 1 else None

        logger.info(
            f"[{dog.name}] cat_similarity coverage={coverage:.3f} "
            f"({len(present_dims)}/{len(weights)} dims: {present_dims})"
        )
        logger.info(
            f"[{dog.name}] cat_similarity #1: {top1[1]} "
            f"score={top1[0]:.3f} popularity_rank={top1[2]}"
        )
        if top2:
            logger.info(
                f"[{dog.name}] cat_similarity #2: {top2[1]} "
                f"score={top2[0]:.3f} popularity_rank={top2[2]}"
            )

        upsert_inferred_breed(
            session,
            dog_id=dog.id,
            method="cat_similarity",
            value=top1[1],
            model_name=MODEL_NAME,
            confidence=coverage,
        )
        rows_written += 1

        if top2:
            upsert_inferred_breed(
                session,
                dog_id=dog.id,
                method="cat_similarity_2nd",
                value=top2[1],
                model_name=MODEL_NAME,
                confidence=coverage,
            )
            rows_written += 1

    session.commit()
    logger.info(
        f"cat_similarity complete. Rows written: {rows_written} "
        f"(skipped low-coverage: {skipped_low_coverage}, "
        f"no-scoreable-breeds: {skipped_no_breeds})"
    )
    return rows_written
