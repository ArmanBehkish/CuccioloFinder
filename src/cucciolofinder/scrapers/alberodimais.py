import scrapy
from loguru import logger

from cucciolofinder.config import SHELTER_SITES
from .pipelines import AlberoDiMaisPipeline


class AlberoDiMaisSpider(scrapy.Spider):
    name = "AlberoDiMaisSpider"
    custom_settings = {
        "ITEM_PIPELINES": {"cucciolofinder.scrapers.pipelines.AlberoDiMaisPipeline": 1},
        "IMAGES_STORE": "data/images",
    }
    start_url = SHELTER_SITES["alberodimais"].url
    pages= set()

    def start_requests( self ):
        logger.debug(f"start URL is : { self.start_url}")
        yield scrapy.Request(url = self.start_url, callback=self.parse)

    def parse(self, response):
        dog_cards = response.css("div.pet-card")
        logger.debug(f"Found {len(dog_cards)} dog cards on page")  # DEBUG

        for card in dog_cards:
            inside_link = card.css("a::attr(href)").get()
            logger.debug(f"Found link: {inside_link}")  # DEBUG
            self.pages.add(inside_link)
            logger.debug(f"number of inside links until now: {len(self.pages)}")
            yield response.follow(inside_link, callback=self.parse_dog_detail)

       
    def parse_dog_detail(self, response):
        name = response.css("h2::text").get()
        logger.debug(f"name: {name}")
        # gender is an icon
        gender_class = response.css("i.fas::attr(class)").get()
        if gender_class:
            if "fa-mars" in gender_class:
                gender = "maschio"
            elif "fa-venus" in gender_class:
                gender = "femmina"
            else:
                gender = None
        else:
            gender = None

        logger.debug(f"gender: {gender}")
        descs = response.css(".container p::text").getall()

        if name == "Chanel":
            logger.debug(f"Chanel here")
            raise(ValueError)

        images = response.css("#carousel-myCarousel img.img-fluid::attr(src)").getall()
        logger.debug(f"images: {images}")

        yield {
            "name": name,
            "gender": gender,
            "descriptions": descs,   # list of texts
            "image_urls": images,
        }
