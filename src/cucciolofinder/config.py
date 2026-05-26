from dataclasses import dataclass

@dataclass
class ShelterSite:
    url: str

# Scrapers URLs for Pidemont Region
SHELTER_SITES: dict[str, ShelterSite] = {
    "quattrozampeinfamiglia": ShelterSite(url="https://www.quattrozampeinfamiglia.it/search/?geodir_search=1&saz=&stype=gd_animali&spost_category%5B%5D=47&sregion%5B%5D=Piemonte&s=&snear=&ssesso%5B%5D=&staglia%5B%5D=&set%5B%5D=&srazza%5B%5D=&srazza_gatto%5B%5D=&sgeo_lat=&sgeo_lon="),
    "empethy":ShelterSite(url="https://www.empethy.it/organizzazioni/rifugio-impronta-creativa-torino"),
    "alberodimais":ShelterSite(url="https://alberodimais.it/cani"),
    "enpatorino":ShelterSite(url="https://www.voltoweb.it/enpasezionetorino/"),
    "canileoasi":ShelterSite(url="https://canileoasi.it/adozioni/"),
}

# Shelter source_site values (the strings stored in `Dog.source_site`, see
# SPIDER_SOURCE_MAP in scrapers/pipelines.py) whose data is hidden from
# public APIs and not re-scraped. Existing DB rows stay untouched; they're
# excluded from /api/enums, /api/stats, /api/filter-dogs, /api/dogs/{id},
# /api/dogs/search, and the data-quality tests' EXPECTED_SOURCES.
DISABLED_SHELTERS: list[str] = ["alberodimais"]

# Quick-test scrape limit.
# Integer for limited number
# None for Production
SCRAPE_LIMIT_PER_SPIDER: int | None = None

# Breed-inference sub-pipelines to run during enrichment.
# Each entry corresponds to a `method` value written to inferred_dog_breeds.
# Available: "image", "cat_similarity".
BREED_DETECTION_PIPELINES: list[str] = ["image", "cat_similarity"]

# Minimum coverage (weighted fraction of present dimensions) before
# cat_similarity will write a row for a dog. Coverage = Σ W[present] / Σ W[all],
# weights are IG bits computed from the AKC reference. Below this threshold
# the dog's signal is too sparse for the score to mean anything; the dog is
# skipped. Default 0.25 ≈ "at least one high-IG dim, or a couple of mid-IG dims".
CAT_SIMILARITY_MIN_COVERAGE: float = 0.25