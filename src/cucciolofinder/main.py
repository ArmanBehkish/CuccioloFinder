import scrapy
from scrapy.crawler import CrawlerProcess
from loguru import logger
from cucciolofinder.scrapers.quattrozampeinfamiglia import QuattroZampeSpider


if __name__ == "__main__": 

    logger.debug("Hello, Dog Lover!")
    process = CrawlerProcess()
    process.crawl(QuattroZampeSpider)
    process.start()
