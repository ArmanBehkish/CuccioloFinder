from dotenv import load_dotenv
from scrapy.crawler import CrawlerProcess
from loguru import logger

load_dotenv()

from cucciolofinder.config import SCRAPE_LIMIT_PER_SPIDER
from cucciolofinder.database import get_engine, get_session, init_db, reset_translations
from cucciolofinder.enrichment import enrich_breed_detection, enrich_translations
from cucciolofinder.enrichment.backends import validate_backend_config
from cucciolofinder.scrapers.quattrozampeinfamiglia import QuattroZampeSpider
from cucciolofinder.scrapers.alberodimais import AlberoDiMaisSpider
from cucciolofinder.scrapers.empethy import EmpethySpider
from cucciolofinder.scrapers.enpatorino import EnpaTorinoSpider
from cucciolofinder.scrapers.canileoasi import CanileOasiSpider


def _set_worker_status(api_url: str, busy: bool) -> None:
    """Signal worker busy/ready to the API container."""
    import requests
    try:
        requests.post(f"{api_url}/api/worker/status", json={"busy": busy}, timeout=10)
    except Exception as exc:
        logger.warning(f"Failed to set worker status: {exc}")


if __name__ == "__main__":


    # Scheduled production flow:
    # reset_translations() → scrape all spiders + pipelines → enrich_translations()

    validate_backend_config(exit_on_error=True)

    import os
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    _set_worker_status(api_url, busy=True)

    engine = get_engine()
    init_db(engine)

    # Step 1: Scrape all sources
    logger.info("Starting scraping...")
    crawler_settings = {}
    if SCRAPE_LIMIT_PER_SPIDER is not None:
        logger.warning(f"SCRAPE_LIMIT_PER_SPIDER={SCRAPE_LIMIT_PER_SPIDER} — quick-test mode, each spider will close after this many items")
        crawler_settings["CLOSESPIDER_ITEMCOUNT"] = SCRAPE_LIMIT_PER_SPIDER
    process = CrawlerProcess(crawler_settings)
    process.crawl(QuattroZampeSpider)
    # process.crawl(EmpethySpider)
    # process.crawl(AlberoDiMaisSpider)
    # process.crawl(EnpaTorinoSpider)
    # process.crawl(CanileOasiSpider)
    process.start()

    # Step 2: Enrich translations
    logger.info("Starting translation enrichment...")
    Session = get_session(engine)
    with Session() as session:
        reset_translations(session)
        enrich_translations(session)  

    # Step 3: Breed detection (image + text profile)
    logger.info("Starting breed detection...")
    with Session() as session:
        enrich_breed_detection(session)

    # Step 4: Data quality tests
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

    # Step 5: Notify running API to reload caches
    logger.info("Refreshing API caches...")
    import requests
    try:
        resp = requests.post(f"{api_url}/api/stats/refresh", timeout=30)
        resp.raise_for_status()
        logger.info(f"API cache refresh OK: {resp.json()}")
    except Exception as exc:
        logger.warning(f"API cache refresh failed (API may not be running): {exc}")

    # Step 6: API contract tests (against live API)
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

