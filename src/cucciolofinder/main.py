from dotenv import load_dotenv
from scrapy.crawler import CrawlerProcess
from loguru import logger

load_dotenv()

from cucciolofinder.database import get_engine, get_session, init_db
from cucciolofinder.enrichment import (
    enrich_behavior_from_desc,
    enrich_breed_detection,
    enrich_from_desc,
    enrich_translations,
)
from cucciolofinder.enrichment.backends import validate_backend_config
from cucciolofinder.scrapers.quattrozampeinfamiglia import QuattroZampeSpider
from cucciolofinder.scrapers.alberodimais import AlberoDiMaisSpider
from cucciolofinder.scrapers.empethy import EmpethySpider
from cucciolofinder.scrapers.enpatorino import EnpaTorinoSpider
from cucciolofinder.scrapers.canileoasi import CanileOasiSpider


def _check_api_reachable(api_url: str) -> bool:
    """Probe `/api/health`. Returns True iff the API responds 2xx.

    The worker can run a Groq-only pipeline without the API, but Mistral
    fallback (Stage 2 extraction, search) requires it. We log a loud
    warning so the operator knows the fallback won't fire if Groq fails.
    """
    import requests
    try:
        resp = requests.get(f"{api_url}/api/health", timeout=10)
        if resp.ok:
            logger.info(f"API reachable at {api_url}")
            return True
        logger.warning(
            f"API at {api_url} returned HTTP {resp.status_code} — "
            "Mistral fallback will not work if Groq fails."
        )
        return False
    except Exception as exc:
        logger.warning(
            f"API at {api_url} not reachable ({exc}). "
            "Worker will run Groq-only — Mistral fallback unavailable."
        )
        return False


def _set_worker_status(api_url: str, busy: bool) -> None:
    """Signal worker busy/ready to the API container."""
    import requests
    try:
        requests.post(f"{api_url}/api/worker/status", json={"busy": busy}, timeout=10)
    except Exception as exc:
        logger.warning(f"Failed to set worker status: {exc}")


def _unload_search_model(api_url: str) -> None:
    """Ask the API to drop Mistral from RAM.

    The API lazy-loads Mistral as a Groq fallback during Stage 2/3; once
    enrichment finishes we don't want it lingering in server memory.
    """
    import requests
    try:
        resp = requests.post(f"{api_url}/api/search-model/unload", timeout=30)
        resp.raise_for_status()
        if resp.json().get("unloaded"):
            logger.info("Mistral unloaded on API after enrichment")
    except Exception as exc:
        logger.warning(f"Failed to unload Mistral on API: {exc}")


if __name__ == "__main__":


    # Scheduled production flow:
    # scrape (per-field invalidation in DatabasePipeline) →
    # enrich_translations → enrich_from_desc → enrich_breed_detection
    # → data-quality tests → API cache refresh → API tests

    validate_backend_config(exit_on_error=True)

    import os
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    _check_api_reachable(api_url)
    _set_worker_status(api_url, busy=True)

    engine = get_engine()
    init_db(engine)

    # Step 1: Scrape all sources
    logger.info("Starting scraping...")
    process = CrawlerProcess()
    process.crawl(QuattroZampeSpider)
    process.crawl(EmpethySpider)
    process.crawl(AlberoDiMaisSpider)
    process.crawl(EnpaTorinoSpider)
    process.crawl(CanileOasiSpider)
    process.start()

    # Step 2: Enrich translations (Stage 1)
    logger.info("Starting translation enrichment...")
    Session = get_session(engine)
    with Session() as session:
        enrich_translations(session)

    # Step 3: Description-extraction fallbacks (Stage 2)
    logger.info("Starting description-extraction enrichment...")
    with Session() as session:
        enrich_from_desc(session)

    # Step 3b: Behavior dimensions for cat_similarity (Stage 2 sibling)
    logger.info("Starting behavior-dimension extraction...")
    with Session() as session:
        enrich_behavior_from_desc(session)

    # Step 4: Breed detection sub-pipelines (Stage 3 — writes to inferred_dog_breeds)
    logger.info("Starting breed detection...")
    with Session() as session:
        enrich_breed_detection(session)

    # Drop Mistral from API RAM if it was lazy-loaded as a Groq fallback.
    _unload_search_model(api_url)

    # Step 5: Data quality tests
    logger.info("Running data quality tests...")
    import subprocess
    result = subprocess.run(
        ["uv", "run", "pytest", "tests/data_quality/", "-v", "-s"],
        capture_output=False,
    )
    if result.returncode != 0:
        logger.warning(f"Data quality tests failed (exit code {result.returncode})")
    else:
        logger.info("Data quality tests passed")

    # Step 6: Notify running API to reload caches
    logger.info("Refreshing API caches...")
    import requests
    try:
        resp = requests.post(f"{api_url}/api/stats/refresh", timeout=30)
        resp.raise_for_status()
        logger.info(f"API cache refresh OK: {resp.json()}")
    except Exception as exc:
        logger.warning(f"API cache refresh failed (API may not be running): {exc}")

    # Step 7: API contract tests (against live API)
    logger.info("Running API tests...")
    result = subprocess.run(
        ["uv", "run", "pytest", "tests/api/", "-v", "-s"],
        capture_output=False,
        env={**os.environ, "API_URL": api_url},
    )
    if result.returncode != 0:
        logger.warning(f"API tests failed (exit code {result.returncode})")
    else:
        logger.info("API tests passed")

    _set_worker_status(api_url, busy=False)

