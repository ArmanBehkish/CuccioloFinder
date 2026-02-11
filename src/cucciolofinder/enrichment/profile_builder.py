import os
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Size normalization
# ---------------------------------------------------------------------------
# Target categories (shared vocabulary for both AKC breeds and shelter dogs):
#   small, medium, large, giant

# English values (after translation by TranslationService)
_SIZE_EN: dict[str, str] = {
    "small": "small",
    "medium": "medium",
    "medium contained": "medium",
    "medium-small": "small",
    "medium-large": "large",
    "large": "large",
    "giant": "giant",
}

# Raw Italian values (fallback when _en field is not yet populated)
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


# ---------------------------------------------------------------------------
# Fur / coat normalization
# ---------------------------------------------------------------------------
# Target categories (shared vocabulary): short, medium, long

# English values
_FUR_EN: dict[str, str] = {
    "short": "short",
    "medium": "medium",
    "long": "long",
}

# Raw Italian values
_FUR_IT: dict[str, str] = {
    "corto": "short",
    "medio": "medium",
    "lungo": "long",
}

# Approximate coat type from AKC grooming frequency
_AKC_GROOMING_TO_COAT: dict[str, str] = {
    "occasional bath/brush": "short",
    "weekly brushing": "medium",
    "2-3 times a week brushing": "long",
    "daily brushing": "long",
    "specialty/professional": "long",
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


def akc_grooming_to_coat(grooming_category: str | None) -> str | None:
    """Derive a coat type from an AKC grooming_frequency_category."""
    if not grooming_category:
        return None
    return _AKC_GROOMING_TO_COAT.get(grooming_category.strip().lower())


# ---------------------------------------------------------------------------
# Weight normalization
# ---------------------------------------------------------------------------
# Target categories (shared vocabulary):
#   very light, light, medium, heavy, very heavy

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


def _kg_to_category(kg: float) -> str:
    for threshold, label in _WEIGHT_BINS:
        if kg < threshold:
            return label
    return _WEIGHT_DEFAULT


def normalize_weight(value: str | None) -> str | None:
    """Parse a shelter weight string and return an AKC-aligned category."""
    kg = parse_weight_kg(value)
    if kg is None:
        return None
    return _kg_to_category(kg)


def akc_weight_to_category(min_weight: float, max_weight: float) -> str:
    """Categorize an AKC breed weight range (kg) using the midpoint."""
    avg = (min_weight + max_weight) / 2
    return _kg_to_category(avg)


# ---------------------------------------------------------------------------
# Behavior classification (zero-shot)
# ---------------------------------------------------------------------------
# Uses zero-shot NLI to infer AKC-style behavioral traits from shelter
# dog descriptions, good_with, and bad_with fields.

DEFAULT_ZSC_MODEL = "facebook/bart-large-mnli"
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


# ---------------------------------------------------------------------------
# Profile template — the final text that gets embedded
# ---------------------------------------------------------------------------

def build_profile_text(
    size: str | None,
    fur: str | None,
    weight: str | None,
    energy_level: str | None,
    trainability: str | None,
    demeanor: str | None,
    temperament: list[str] | None,
) -> str:
    """Format all normalized fields into the shared text template for embedding."""
    parts: list[str] = []
    if temperament:
        parts.append(f"temperament: {', '.join(temperament)}")
    if energy_level:
        parts.append(f"energy_level: {energy_level}")
    if trainability:
        parts.append(f"trainability: {trainability}")
    if demeanor:
        parts.append(f"demeanor: {demeanor}")
    if size:
        parts.append(f"size: {size}")
    if weight:
        parts.append(f"weight: {weight}")
    if fur:
        parts.append(f"coat: {fur}")
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# TEST — remove after server validation
# ---------------------------------------------------------------------------

def test_profiles() -> None:
    """Build and print full profiles for 2 dogs per shelter."""
    from sqlalchemy import func

    from cucciolofinder.database import Dog, get_engine, get_session

    engine = get_engine()
    Session = get_session(engine)

    with Session() as session:
        # pick 2 dogs per source_site
        sites = [row[0] for row in session.query(Dog.source_site).distinct()]
        dogs: list = []
        for site in sites:
            sample = (
                session.query(Dog)
                .filter(Dog.source_site == site)
                .order_by(func.random())
                .limit(2)
                .all()
            )
            dogs.extend(sample)

    if not dogs:
        print("No dogs found.")
        return

    print("Loading zero-shot classifier...")
    classifier = load_classifier()

    for dog in dogs:
        size = normalize_size(dog.size_en or dog.size)
        fur = normalize_fur(dog.fur_en or dog.fur)
        weight = normalize_weight(dog.weight)

        desc = dog.description_en or dog.description
        good = dog.good_with_en or dog.good_with
        bad = dog.bad_with_en or dog.bad_with
        behavior = classify_behavior(desc, good, bad, classifier)

        profile = build_profile_text(
            size=size,
            fur=fur,
            weight=weight,
            energy_level=behavior["energy_level"],
            trainability=behavior["trainability"],
            demeanor=behavior["demeanor"],
            temperament=behavior["temperament"],
        )

        print(f"[{dog.source_site}] {dog.name}: {profile}")
        print()

