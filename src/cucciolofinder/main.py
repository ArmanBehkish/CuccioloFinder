import scrapy
from scrapy.crawler import CrawlerProcess
from loguru import logger
from cucciolofinder.database import get_engine, init_db
from cucciolofinder.scrapers.quattrozampeinfamiglia import QuattroZampeSpider
from cucciolofinder.scrapers.alberodimais import AlberoDiMaisSpider
from cucciolofinder.scrapers.empethy import EmpethySpider
from cucciolofinder.scrapers.enpatorino import EnpaTorinoSpider
from cucciolofinder.scrapers.canileoasi import CanileOasiSpider


if __name__ == "__main__":

    engine = get_engine()
    init_db(engine)

    process = CrawlerProcess()
    process.crawl(QuattroZampeSpider)
    process.crawl(EmpethySpider)
    process.crawl(AlberoDiMaisSpider)
    process.crawl(EnpaTorinoSpider)
    process.crawl(CanileOasiSpider)
    process.start()
