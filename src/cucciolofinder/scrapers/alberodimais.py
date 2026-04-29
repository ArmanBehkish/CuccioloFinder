import os
from datetime import datetime

import scrapy
from loguru import logger

from cucciolofinder.config import SCRAPE_LIMIT_PER_SPIDER, SHELTER_SITES
from .pipelines import AlberoDiMaisPipeline


class AlberoDiMaisSpider(scrapy.Spider):
    name = "AlberoDiMaisSpider"
    _scraped = 0  # quick-test counter, bounded by SCRAPE_LIMIT_PER_SPIDER
    custom_settings = {
        "ITEM_PIPELINES": {
            "cucciolofinder.scrapers.pipelines.IdentityPipeline": 1,
            "cucciolofinder.scrapers.pipelines.AlberoDiMaisPipeline": 5,
            "cucciolofinder.scrapers.pipelines.DatabasePipeline": 14,
        },
        "IMAGES_STORE": os.environ.get("IMAGES_PATH", "data/images"),
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
            if SCRAPE_LIMIT_PER_SPIDER is not None and self._scraped >= SCRAPE_LIMIT_PER_SPIDER:
                logger.info(f"SCRAPE_LIMIT_PER_SPIDER={SCRAPE_LIMIT_PER_SPIDER} reached, stopping")
                return
            inside_link = card.css("a::attr(href)").get()
            logger.debug(f"Found link: {inside_link}")  # DEBUG
            self.pages.add(inside_link)
            logger.debug(f"number of inside links until now: {len(self.pages)}")
            self._scraped += 1
            yield response.follow(inside_link, callback=self.parse_dog_detail)

       
    def parse_dog_detail(self, response):
        raw_name = response.css("h2::text").get()
        name = raw_name.strip() if raw_name else None
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

        # age from birth date
        age = None
        for p_text in response.css(".container p::text").getall():
            if "Data di nascita" in p_text:
                date_str = p_text.split(":")[-1].strip()
                try:
                    birth_date = datetime.strptime(date_str, "%d/%m/%Y")
                    today = datetime.now()
                    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
                except ValueError:
                    logger.warning(f"Could not parse birth date: {date_str}")
                break

        # descriptions
        descs = response.css(".container p::text").getall()

        # images
        images = response.css("#carousel-myCarousel img.img-fluid::attr(src)").getall()

        logger.debug(f"Dog: {name}, gender: {gender}, age: {age}, descriptions: {descs}, source URL: {response.url} ")


        yield {
            "source_url": response.url,
            "name": name,
            "gender": gender,
            "age": f"{age} anno" if age == 1 else f"{age} anni" if age is not None else None,
            "descriptions": descs,   # list of texts
            "image_urls": images,
        }
