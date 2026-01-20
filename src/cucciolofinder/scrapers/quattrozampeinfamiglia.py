import scrapy
from loguru import logger

from cucciolofinder.config import SHELTER_SITES


class QuattroZampeSpider(scrapy.Spider):
    name = "QuattrozampeSpider"
    start_url = SHELTER_SITES["quattrozampeinfamiglia"].url
    pages= set()

    def start_requests( self ):
        logger.debug(f"start URL is : { self.start_url}")
        yield scrapy.Request(url = self.start_url, callback=self.parse)

    def parse(self, response):
        dog_cards = response.xpath("/html/body/div[1]/section[2]/div/div[3]/div/div/div/div/article")
   
        for card in dog_cards:
            inside_link = card.css("a::attr(href)").get()
            if "torino" in str(inside_link):
                logger.debug(f"inside link: {inside_link}")
                self.pages.add(inside_link)
                logger.debug(f"number of inside links until now: {len(self.pages)}")
                yield response.follow(inside_link, callback=self.parse_dog_detail)

        # Follow next page if exists
        next_page = response.xpath("//a[contains(@class, 'next')]/@href").get()
        logger.debug(f"Following next page: {next_page}")
        if next_page:
            yield response.follow(next_page, callback=self.parse)

        
    def parse_dog_detail(self, response):
        # Extract dog data from detail page
        # TODO: Update selectors based on actual HTML structure
        pass
