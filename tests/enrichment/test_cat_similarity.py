"""Tests for cat_similarity: resolvers, similarity functions, IG weights."""

import math

import pytest

from cucciolofinder.enrichment.breed.cat_similarity import (
    _DEMEANOR_SIM,
    _ENERGY_LEVELS,
    _FUR_LEVELS,
    _SIZE_LEVELS,
    _TRAINABILITY_SIM,
    _compute_weights,
    _coverage,
    _sim_nominal,
    _sim_ordinal,
    _sim_temperament,
    resolve_fur,
    resolve_size,
    resolve_weight,
)


# ---------- size ----------

@pytest.mark.parametrize(("a", "b", "expected"), [
    # User-given examples
    ("medium-large", "medium", "medium"),
    ("medium-large", "large", "large"),
    ("large", "giant", "giant"),
    # Symmetric: argument order shouldn't matter
    ("medium", "medium-large", "medium"),
    ("large", "medium-large", "large"),
    ("giant", "large", "giant"),
    # Agreement
    ("medium", "medium", "medium"),
    ("large", "large", "large"),
    # Italian compound + English exact
    ("medio-grande", "medium", "medium"),
    ("medio-grande", "large", "large"),
    # "medium contained" treated as compound (it's a hedge)
    ("medium contained", "small", "small"),
    ("media contenuta", "large", "large"),
    # Single source: normalize alone
    ("medium-large", None, "large"),
    (None, "medium-large", "large"),
    ("medium", None, "medium"),
    (None, "small", "small"),
    # Both empty/null
    (None, None, None),
    ("", "", None),
    # Both compound, disagreeing — pick larger normalized
    ("medium-small", "medium-large", "large"),
    # Exact + exact further apart — pick larger
    ("small", "large", "large"),
])
def test_resolve_size(a, b, expected):
    assert resolve_size(a, b) == expected


# ---------- fur ----------

@pytest.mark.parametrize(("a", "b", "expected"), [
    ("short", "short", "short"),
    ("short", "medium", "medium"),  # disagree → larger
    ("medium", "long", "long"),
    ("short", "long", "long"),
    ("corto", "long", "long"),  # Italian + English mix
    ("short", None, "short"),
    (None, "long", "long"),
    (None, None, None),
])
def test_resolve_fur(a, b, expected):
    assert resolve_fur(a, b) == expected


# ---------- weight ----------
# Bin thresholds: <7 very light, <15 light, <30 medium, <50 heavy, else very heavy.

@pytest.mark.parametrize(("a", "b", "expected"), [
    ("30kg", "25kg", "heavy"),     # max=30 → heavy (30 not < 30)
    ("12kg", "30kg", "heavy"),
    ("5kg", "5kg", "very light"),
    ("20", None, "medium"),
    (None, "8kg", "light"),
    ("60kg", "55kg", "very heavy"),
    (None, None, None),
    ("not a number", None, None),
    # Mixed: one parses, one doesn't — use the parsed one
    ("12kg", "no info", "light"),
])
def test_resolve_weight(a, b, expected):
    assert resolve_weight(a, b) == expected


# ---------- ordinal similarity ----------

@pytest.mark.parametrize(("a", "b", "expected"), [
    # Identity
    ("small", "small", 1.0),
    ("giant", "giant", 1.0),
    # Adjacent (1 step apart, N=4 → 1 - 1/3)
    ("small", "medium", pytest.approx(2 / 3, abs=1e-3)),
    ("medium", "large", pytest.approx(2 / 3, abs=1e-3)),
    ("large", "giant", pytest.approx(2 / 3, abs=1e-3)),
    # 2 steps apart
    ("small", "large", pytest.approx(1 / 3, abs=1e-3)),
    ("medium", "giant", pytest.approx(1 / 3, abs=1e-3)),
    # Opposite ends (N-1 steps)
    ("small", "giant", 0.0),
    # Off-vocab → 0
    ("xxx", "small", 0.0),
])
def test_sim_ordinal_size(a, b, expected):
    assert _sim_ordinal(a, b, _SIZE_LEVELS) == expected


def test_sim_ordinal_fur():
    # N=3 → adjacent gives 1 - 1/2 = 0.5
    assert _sim_ordinal("short", "medium", _FUR_LEVELS) == 0.5
    assert _sim_ordinal("short", "long", _FUR_LEVELS) == 0.0
    assert _sim_ordinal("long", "long", _FUR_LEVELS) == 1.0


def test_sim_ordinal_energy_levels():
    assert _sim_ordinal("Calm", "Calm", _ENERGY_LEVELS) == 1.0
    # 5 levels, opposite ends: dist=4, 1 - 4/4 = 0
    assert _sim_ordinal("Calm", "Needs Lots of Activity", _ENERGY_LEVELS) == 0.0


# ---------- nominal similarity ----------

def test_sim_nominal_diagonal():
    """Same label always returns 1.0, even if not in table."""
    assert _sim_nominal("Agreeable", "Agreeable", _TRAINABILITY_SIM) == 1.0
    assert _sim_nominal("Friendly", "Friendly", _DEMEANOR_SIM) == 1.0


def test_sim_nominal_table_lookup_symmetric():
    """Lookup works in either argument order."""
    assert _sim_nominal("Agreeable", "Eager to Please", _TRAINABILITY_SIM) == 0.7
    assert _sim_nominal("Eager to Please", "Agreeable", _TRAINABILITY_SIM) == 0.7
    assert _sim_nominal("Friendly", "Outgoing", _DEMEANOR_SIM) == 0.8
    assert _sim_nominal("Outgoing", "Friendly", _DEMEANOR_SIM) == 0.8


def test_sim_nominal_unknown_pair_returns_zero():
    assert _sim_nominal("Agreeable", "NotALabel", _TRAINABILITY_SIM) == 0.0


# ---------- temperament: IDF-weighted Jaccard ----------

def test_sim_temperament_idf_weighted():
    """A = {Friendly, Aloof/Wary}, B adds rare {Loyal}.
    Numerator = idf(intersection); denominator = idf(union).
    Rare matches dominate via high IDF.
    """
    idf = {"Friendly": 0.22, "Aloof/Wary": 3.00, "Loyal": 1.39}
    a = ["Friendly", "Aloof/Wary"]
    b = ["Friendly", "Aloof/Wary", "Loyal"]
    expected = (0.22 + 3.00) / (0.22 + 3.00 + 1.39)
    assert _sim_temperament(a, b, idf) == pytest.approx(expected, abs=1e-3)


def test_sim_temperament_identical_sets():
    idf = {"Friendly": 0.22, "Loyal": 1.39}
    a = ["Friendly", "Loyal"]
    assert _sim_temperament(a, a, idf) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("a, b", [
    (None, None),
    (None, ["Friendly"]),
    ([], []),
])
def test_sim_temperament_empty_sides(a, b):
    """Empty union → 0; never errors out."""
    assert _sim_temperament(a, b, {"Friendly": 1.0}) == 0.0


# ---------- IG weights ----------

def test_compute_weights_size_skewed_distribution():
    """200 breeds split 50/60/70/20 across the 4 size buckets.

    IG(size) = log2(200) − Σ (n_j / 200) · log2(n_j)
             = 7.643 − [0.25·5.644 + 0.30·5.907 + 0.35·6.129 + 0.10·4.322]
             ≈ 7.643 − 5.764 ≈ 1.88 bits.
    """
    fake_index = {}
    breed_id = 0
    for size, count in [("small", 50), ("medium", 60), ("large", 70), ("giant", 20)]:
        for _ in range(count):
            breed_id += 1
            fake_index[f"breed{breed_id}"] = {
                "size": size, "fur": None, "weight": None,
                "energy_level": None, "trainability": None,
                "demeanor": None, "temperament": None, "popularity": None,
            }

    weights, _, n_eff = _compute_weights(fake_index)
    assert n_eff["size"] == 200
    assert weights["size"] == pytest.approx(1.88, abs=0.01)


def test_compute_weights_uniform_distribution_max_ig():
    """N=4 breeds each in their own bucket → IG = log2(4) = 2.0 bits."""
    fake_index = {
        f"b{i}": {
            "size": s, "fur": None, "weight": None,
            "energy_level": None, "trainability": None,
            "demeanor": None, "temperament": None, "popularity": None,
        }
        for i, s in enumerate(["small", "medium", "large", "giant"])
    }
    weights, _, _ = _compute_weights(fake_index)
    assert weights["size"] == pytest.approx(2.0, abs=1e-9)


def test_compute_weights_universal_value_zero_ig():
    """All breeds share one value → no information gained."""
    fake_index = {
        f"b{i}": {
            "size": "medium", "fur": None, "weight": None,
            "energy_level": None, "trainability": None,
            "demeanor": None, "temperament": None, "popularity": None,
        }
        for i in range(10)
    }
    weights, _, _ = _compute_weights(fake_index)
    assert weights["size"] == pytest.approx(0.0, abs=1e-9)


def test_compute_weights_temperament_idf():
    """Rare temperament trait gets high IDF, common one gets low IDF.
    Both traits used here are in TEMPERAMENT_META.
    """
    fake_index = {}
    for i in range(8):
        fake_index[f"common{i}"] = {
            "size": None, "fur": None, "weight": None,
            "energy_level": None, "trainability": None, "demeanor": None,
            "temperament": ["Friendly"], "popularity": None,
        }
    for i in range(2):
        fake_index[f"rare{i}"] = {
            "size": None, "fur": None, "weight": None,
            "energy_level": None, "trainability": None, "demeanor": None,
            "temperament": ["Independent"], "popularity": None,
        }
    _, idf, n_eff = _compute_weights(fake_index)
    assert n_eff["temperament"] == 10
    assert idf["Friendly"] == pytest.approx(math.log(10 / 8), abs=1e-3)
    assert idf["Independent"] == pytest.approx(math.log(10 / 2), abs=1e-3)


# ---------- coverage ----------

def test_coverage_full():
    weights = {"size": 1.0, "fur": 1.0, "weight": 2.0}
    dog_dims = {"size": "medium", "fur": "short", "weight": "light"}
    cov, present = _coverage(dog_dims, weights)
    assert cov == 1.0
    assert sorted(present) == ["fur", "size", "weight"]


def test_coverage_partial():
    weights = {"size": 1.0, "fur": 1.0, "weight": 2.0}
    dog_dims = {"size": "medium", "fur": None, "weight": None}
    cov, present = _coverage(dog_dims, weights)
    assert cov == pytest.approx(0.25, abs=1e-9)  # 1/(1+1+2)
    assert present == ["size"]


def test_coverage_zero_weights_safe():
    weights = {"size": 0.0, "fur": 0.0}
    dog_dims = {"size": "medium", "fur": "short"}
    cov, present = _coverage(dog_dims, weights)
    assert cov == 0.0
    assert present == []
