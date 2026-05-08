"""Breed-specific profile helpers: AKC reference mappers and zero-shot
behavior classification used by the breed-inference sub-pipelines.

Generic value normalizers (`normalize_size/fur/weight/age`,
`parse_weight_kg`) live in `enrichment/normalizers.py` — they're used
across the API and shouldn't depend on the breed package.
"""

import os
from pathlib import Path

from ..normalizers import kg_to_category

# AKC reference mappers — used to project AKC catalogue rows onto the
# same shared vocabulary as shelter dogs so embeddings/profiles compare.

# Approximate coat type from AKC grooming frequency.
_AKC_GROOMING_TO_COAT: dict[str, str] = {
    "occasional bath/brush": "short",
    "weekly brushing": "medium",
    "2-3 times a week brushing": "long",
    "daily brushing": "long",
    "specialty/professional": "long",
}


def akc_height_to_size(min_height: float, max_height: float) -> str:
    """Derive a size category from AKC numeric height range (cm).

    Thresholds based on AKC breed height distribution:
      avg < 35 cm  → small
      35–55 cm     → medium
      55–70 cm     → large
      ≥ 70 cm      → giant
    """
    avg = (min_height + max_height) / 2
    if avg < 35:
        return "small"
    if avg < 55:
        return "medium"
    if avg < 70:
        return "large"
    return "giant"


def akc_grooming_to_coat(grooming_category: str | None) -> str | None:
    """Derive a coat type from an AKC grooming_frequency_category."""
    if not grooming_category:
        return None
    return _AKC_GROOMING_TO_COAT.get(grooming_category.strip().lower())


def akc_weight_to_category(min_weight: float, max_weight: float) -> str:
    """Categorize an AKC breed weight range (kg) using the midpoint."""
    avg = (min_weight + max_weight) / 2
    return kg_to_category(avg)


# Behavior classification (zero-shot) — uses zero-shot NLI to infer
# AKC-style behavioral traits from shelter dog descriptions, good_with,
# and bad_with fields.

DEFAULT_ZSC_MODEL = os.environ.get("ZSC_MODEL_ID", "facebook/bart-large-mnli")
MODELS_DIR = Path(os.environ.get("MODELS_PATH", "data/models"))

ENERGY_LABELS = [
    "Calm",
    "Couch Potato",
    "Regular Exercise",
    "Energetic",
    "Needs Lots of Activity",
]

TRAINABILITY_LABELS = [
    "Agreeable",
    "Eager to Please",
    "Easy Training",
    "Independent",
    "May be Stubborn",
]

DEMEANOR_LABELS = [
    "Alert/Responsive",
    "Aloof/Wary",
    "Friendly",
    "Outgoing",
    "Reserved with Strangers",
]

# 8 temperament meta-categories (used for both AKC mapping and zero-shot)
TEMPERAMENT_META = [
    "Affectionate",
    "Friendly",
    "Loyal",
    "Playful",
    "Confident",
    "Intelligent",
    "Energetic",
    "Independent",
]

# Maps every individual AKC trait adjective → one of the 8 meta-categories.
# Built by extracting all unique words from the 267 AKC temperament triplets.
_TRAIT_TO_META: dict[str, str] = {
    # -- Affectionate --
    "affectionate": "Affectionate",
    "gentle": "Affectionate",
    "kind": "Affectionate",
    "loving": "Affectionate",
    "lovable": "Affectionate",
    "sensitive": "Affectionate",
    "sweet": "Affectionate",
    "sweet-natured": "Affectionate",
    "sweet-tempered": "Affectionate",
    "tenderhearted": "Affectionate",
    "deeply affectionate": "Affectionate",
    "undemanding": "Affectionate",
    # -- Friendly --
    "friendly": "Friendly",
    "sociable": "Friendly",
    "outgoing": "Friendly",
    "merry": "Friendly",
    "cheerful": "Friendly",
    "good-natured": "Friendly",
    "good-humored": "Friendly",
    "good-tempered": "Friendly",
    "amiable": "Friendly",
    "even-tempered": "Friendly",
    "people-oriented": "Friendly",
    "gregarious": "Friendly",
    "pleasant": "Friendly",
    "humble": "Friendly",
    "polite": "Friendly",
    "courteous": "Friendly",
    "easy-going": "Friendly",
    "patient": "Friendly",
    "docile": "Friendly",
    # -- Loyal --
    "loyal": "Loyal",
    "devoted": "Loyal",
    "faithful": "Loyal",
    "dependable": "Loyal",
    "family-oriented": "Loyal",
    "profoundly loyal": "Loyal",
    "deeply devoted": "Loyal",
    "home-loving": "Loyal",
    "confident guardian": "Loyal",
    # -- Playful --
    "playful": "Playful",
    "fun-loving": "Playful",
    "lively": "Playful",
    "mischievous": "Playful",
    "upbeat": "Playful",
    "happy": "Playful",
    "charming": "Playful",
    "amusing": "Playful",
    "comical": "Playful",
    "entertaining": "Playful",
    "frollicking": "Playful",
    "happy-go-lucky": "Playful",
    "perky": "Playful",
    "peppy": "Playful",
    "sassy": "Playful",
    "tomboyish": "Playful",
    "plucky": "Playful",
    "spunky": "Playful",
    "vivacious": "Playful",
    "boisterous": "Playful",
    "bouncy": "Playful",
    "charismatic": "Playful",
    "optimistic": "Playful",
    "positive": "Playful",
    "sense of humor": "Playful",
    "famously funny": "Playful",
    "funny": "Playful",
    # -- Confident --
    "confident": "Confident",
    "bold": "Confident",
    "fearless": "Confident",
    "courageous": "Confident",
    "brave": "Confident",
    "determined": "Confident",
    "self-confident": "Confident",
    "strong-willed": "Confident",
    "powerful": "Confident",
    "tenacious": "Confident",
    "strong": "Confident",
    "dashing": "Confident",
    # -- Intelligent --
    "smart": "Intelligent",
    "intelligent": "Intelligent",
    "bright": "Intelligent",
    "clever": "Intelligent",
    "trainable": "Intelligent",
    "eager to please": "Intelligent",
    "willing to please": "Intelligent",
    "attentive": "Intelligent",
    "perceptive": "Intelligent",
    "keen": "Intelligent",
    "observant": "Intelligent",
    "keenly alert": "Intelligent",
    "keenly observant": "Intelligent",
    "alert": "Intelligent",
    "curious": "Intelligent",
    "inquisitive": "Intelligent",
    "watchful": "Intelligent",
    "vigilant": "Intelligent",
    "canny": "Intelligent",
    "eager": "Intelligent",
    "alert and intelligent": "Intelligent",
    "wickedly smart": "Intelligent",
    "adaptable": "Intelligent",
    "versatile": "Intelligent",
    "responsive": "Intelligent",
    "obedient": "Intelligent",
    # -- Energetic --
    "active": "Energetic",
    "energetic": "Energetic",
    "athletic": "Energetic",
    "spirited": "Energetic",
    "agile": "Energetic",
    "exuberant": "Energetic",
    "ready to work": "Energetic",
    "work-oriented": "Energetic",
    "hardworking": "Energetic",
    "quick": "Energetic",
    "enthusiastic": "Energetic",
    "sprightly": "Energetic",
    # -- Independent --
    "independent": "Independent",
    "reserved": "Independent",
    "dignified": "Independent",
    "calm": "Independent",
    "noble": "Independent",
    "aristocratic": "Independent",
    "poised": "Independent",
    "graceful": "Independent",
    "proud": "Independent",
    "regal": "Independent",
    "majestic": "Independent",
    "serious-minded": "Independent",
    "gentlemanly": "Independent",
    "mellow": "Independent",
    "low-key": "Independent",
    "regal in manner": "Independent",
    "regally dignified": "Independent",
    "reserved with strangers": "Independent",
    "independent-minded": "Independent",
}


def akc_temperament_to_meta(temperament: str | None) -> list[str]:
    """Map an AKC temperament triplet string to a list of meta-categories.

    Example: "Friendly, Curious, Merry" → ["Friendly", "Intelligent", "Friendly"]
             deduplicated → ["Friendly", "Intelligent"]
    """
    if not temperament:
        return []
    traits = [t.strip() for t in temperament.split(",")]
    seen: set[str] = set()
    result: list[str] = []
    for trait in traits:
        meta = _TRAIT_TO_META.get(trait.strip().lower())
        if meta and meta not in seen:
            seen.add(meta)
            result.append(meta)
    return result


def _build_behavior_text(
    description_en: str | None,
    good_with_en: list[str] | None,
    bad_with_en: list[str] | None,
) -> str | None:
    """Combine available text fields into a single input for classification."""
    parts: list[str] = []
    if description_en and description_en.strip():
        parts.append(description_en.strip())
    if good_with_en:
        parts.append(f"Good with: {', '.join(good_with_en)}.")
    if bad_with_en:
        parts.append(f"Not good with: {', '.join(bad_with_en)}.")
    return " ".join(parts) if parts else None


def load_classifier(
    model_id: str = DEFAULT_ZSC_MODEL,
    models_dir: Path = MODELS_DIR,
):
    """Load the zero-shot classification pipeline (CPU, cached on disk)."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline

    cache_dir = models_dir / model_id.replace("/", "--")
    cache_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_id, cache_dir=cache_dir
    )
    return pipeline(
        "zero-shot-classification", model=model, tokenizer=tokenizer, device="cpu"
    )


def classify_behavior(
    description_en: str | None,
    good_with_en: list[str] | None,
    bad_with_en: list[str] | None,
    classifier,
    confidence_threshold: float = 0.3,
) -> dict[str, str | list[str] | None]:
    """Classify a shelter dog's behavioral traits using zero-shot NLI.

    Returns a dict with keys: energy_level, trainability, demeanor, temperament.
    Values are None when the input text is empty or the classifier's top
    score falls below *confidence_threshold*.
    """
    text = _build_behavior_text(description_en, good_with_en, bad_with_en)

    result: dict[str, str | list[str] | None] = {
        "energy_level": None,
        "trainability": None,
        "demeanor": None,
        "temperament": None,
    }

    if not text:
        return result

    # Single-label categories: pick the top prediction
    for key, labels in [
        ("energy_level", ENERGY_LABELS),
        ("trainability", TRAINABILITY_LABELS),
        ("demeanor", DEMEANOR_LABELS),
    ]:
        out = classifier(text, labels, multi_label=False)
        if out["scores"][0] >= confidence_threshold:
            result[key] = out["labels"][0]

    # Temperament: multi-label, pick top 3 above threshold
    out = classifier(text, TEMPERAMENT_META, multi_label=True)
    top = [
        label
        for label, score in zip(out["labels"], out["scores"])
        if score >= confidence_threshold
    ][:3]
    result["temperament"] = top if top else None

    return result


