"""Generic value normalizers (size / fur / weight / age).

These helpers map raw shelter strings (Italian or English) and free-form
user input to small, AKC-aligned categorical vocabularies. They are
*not* breed-detection-specific — the API layer uses them for filtering,
stats, and search. They have zero heavy dependencies (no torch /
transformers), so importing this module from the API container is safe.

Breed-detection-specific helpers (zero-shot classifier, AKC reference
mappers, profile-text builder) live in `enrichment/breed/profile_builder.py`.
"""

import re

# SIZE: target categories — small, medium, large, giant.

_SIZE_EN: dict[str, str] = {
    "small": "small",
    "medium": "medium",
    "medium contained": "medium",
    "medium-small": "small",
    "medium-large": "large",
    "large": "large",
    "giant": "giant",
}

_SIZE_IT: dict[str, str] = {
    "piccola": "small",
    "piccolo": "small",
    "media": "medium",
    "medio": "medium",
    "media contenuta": "medium",
    "medio-piccola": "small",
    "medio-grande": "large",
    "grande": "large",
    "gigante": "giant",
}


def normalize_size(value: str | None) -> str | None:
    """Normalize a shelter dog size value to an AKC-aligned category.

    Tries the English map first, then falls back to the Italian map.
    Returns None if the value cannot be mapped.
    """
    if not value:
        return None
    key = value.strip().lower()
    return _SIZE_EN.get(key) or _SIZE_IT.get(key)


# FUR: target categories — short, medium, long.

_FUR_EN: dict[str, str] = {
    "short": "short",
    "medium": "medium",
    "long": "long",
}

_FUR_IT: dict[str, str] = {
    "corto": "short",
    "medio": "medium",
    "lungo": "long",
}


def normalize_fur(value: str | None) -> str | None:
    """Normalize a shelter dog fur value to a coat type.

    Tries the English map first, then falls back to the Italian map.
    Returns None if the value cannot be mapped.
    """
    if not value:
        return None
    key = value.strip().lower()
    return _FUR_EN.get(key) or _FUR_IT.get(key)


# WEIGHT: target categories — very light, light, medium, heavy, very heavy.

_WEIGHT_BINS: list[tuple[float, str]] = [
    (7, "very light"),
    (15, "light"),
    (30, "medium"),
    (50, "heavy"),
]
_WEIGHT_DEFAULT = "very heavy"

_WEIGHT_KG_RE = re.compile(r"(\d+(?:[.,]\d+)?)")


def parse_weight_kg(value: str | None) -> float | None:
    """Extract a numeric kg value from a shelter weight string.

    Handles formats like '15kg', '15 Kg', '15 kg', '15', '25'.
    Returns None for unparseable values like 'non specificato'.
    """
    if not value:
        return None
    match = _WEIGHT_KG_RE.search(value)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def kg_to_category(kg: float) -> str:
    """Bucket a kg value into one of the weight categories."""
    for threshold, label in _WEIGHT_BINS:
        if kg < threshold:
            return label
    return _WEIGHT_DEFAULT


def normalize_weight(value: str | None) -> str | None:
    """Parse a shelter weight string and return an AKC-aligned category."""
    kg = parse_weight_kg(value)
    if kg is None:
        return None
    return kg_to_category(kg)


# AGE: target categories — puppy (<1y), young (1–3y), adult (4–7y), senior (8y+).

def normalize_age(age_en: str | None) -> str | None:
    """Derive age_category from an English age string like '3 years', '6 months'.

    Returns one of: 'puppy', 'young', 'adult', 'senior', or None if unparseable.
    """
    if not age_en:
        return None
    s = age_en.strip().lower()
    months_match = re.search(r"(\d+)\s+month", s)
    years_match = re.search(r"(\d+)\s+year", s)
    if months_match:
        months = int(months_match.group(1))
        years = int(years_match.group(1)) if years_match else 0
        total_years = years + months / 12
    elif years_match:
        total_years = int(years_match.group(1))
    else:
        return None

    if total_years < 1:
        return "puppy"
    if total_years <= 3:
        return "young"
    if total_years <= 7:
        return "adult"
    return "senior"
