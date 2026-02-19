from dotenv import load_dotenv
from scrapy.crawler import CrawlerProcess
from loguru import logger

load_dotenv()

from cucciolofinder.database import get_engine, get_session, init_db, reset_translations
from cucciolofinder.enrichment import enrich_breed_detection, enrich_translations
from cucciolofinder.scrapers.quattrozampeinfamiglia import QuattroZampeSpider
from cucciolofinder.scrapers.alberodimais import AlberoDiMaisSpider
from cucciolofinder.scrapers.empethy import EmpethySpider
from cucciolofinder.scrapers.enpatorino import EnpaTorinoSpider
from cucciolofinder.scrapers.canileoasi import CanileOasiSpider


if __name__ == "__main__":


    # Scheduled production flow: 
    # reset_translations() → scrape all spiders + pipelines → enrich_translations()

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

