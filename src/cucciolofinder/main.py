from scrapy.crawler import CrawlerProcess
from loguru import logger

from cucciolofinder.database import get_engine, get_session, init_db, reset_translations
from cucciolofinder.enrichment import enrich_translations
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
    #process.crawl(QuattroZampeSpider)
    # process.crawl(EmpethySpider)
    # process.crawl(AlberoDiMaisSpider)
    # process.crawl(EnpaTorinoSpider)
    process.crawl(CanileOasiSpider)
    process.start()

    # Step 2: Enrich translations
    logger.info("Starting translation enrichment...")
    Session = get_session(engine)
    with Session() as session:
        reset_translations(session)
        enrich_translations(session, limit=10)  # TODO: remove limit for production
