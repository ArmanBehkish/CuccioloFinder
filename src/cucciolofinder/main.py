import scrapy
from scrapy.crawler import CrawlerProcess
from loguru import logger
from cucciolofinder.scrapers.quattrozampeinfamiglia import QuattroZampeSpider
from cucciolofinder.scrapers.alberodimais import AlberoDiMaisSpider
from cucciolofinder.scrapers.empethy import EmpethySpider


if __name__ == "__main__": 

    process = CrawlerProcess()
    process.crawl(EmpethySpider)
    #process.crawl(AlberoDiMaisSpider)
    process.start()
