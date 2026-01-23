import scrapy
from loguru import logger

from cucciolofinder.config import SHELTER_SITES
from .pipelines import QuattroImagesPipeline


class QuattroZampeSpider(scrapy.Spider):
    name = "QuattrozampeSpider"
    custom_settings = {
        "ITEM_PIPELINES": {"cucciolofinder.scrapers.pipelines.QuattroImagesPipeline": 1},
        "IMAGES_STORE": "data/images",
    }
    start_url = SHELTER_SITES["quattrozampeinfamiglia"].url
    pages= set()

    def start_requests( self ):
        yield scrapy.Request(url = self.start_url, callback=self.parse)

    def parse(self, response):
        dog_cards = response.xpath("/html/body/div[1]/section[2]/div/div[3]/div/div/div/div/article")
   
        for card in dog_cards:
            inside_link = card.css("a::attr(href)").get()
            if "torino" in str(inside_link):
                self.pages.add(inside_link)
                logger.debug(f"number of inside links until now: {len(self.pages)}")
                yield response.follow(inside_link, callback=self.parse_dog_detail)

        # next page on regular HTML pagination
        next_page = response.xpath("//a[contains(@class, 'next')]/@href").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

        
    def parse_dog_detail(self, response):
        # Extract dog data from detail page
        images = response.xpath("//section[4]/div//img/@src").getall()
        images = [image for image in images if "spazio_foto" not in image]

        # description region
        desc = response.xpath("/html/body/div[1]/section[5]/div/div[2]")
        name = desc.css("h2::text").get()
        logger.debug(f"Extracting dog: {name}")

        explanation= desc.xpath("//div[contains(@class,'geodir-field-mi_presento')]").css("p::text").get()

        def parse_dog_detail(response):
            items = response.css("div.geodir_post_meta")
            characteristics = {}
            for item in items:
                label = item.css("span.geodir_post_meta_title::text").get()
                if label:
                    label = label.strip().rstrip(":")  # "Età:" -> "Età"
                    # Get value - text after the label span
                    value = item.xpath("text()").get()
                    value = value.strip() if value else None
                    characteristics[label.lower()] = value
            return characteristics
        
        # get charactereistic fields
        fields = parse_dog_detail(response)

        yield {
            "name": name,
            "explanation": explanation,
            "age": fields.get('età'),
            "sex": fields.get('sesso'),
            "breed": fields.get('razza cane'),
            "fur": fields.get('pelo'),
            "size": fields.get('taglia'),
            "weight": fields.get('peso kg'),
            "microchip": fields.get('microchip'),
            "sterilization": fields.get('sterilizzazione'),
            "vaccine": fields.get('vaccinazioni'),
            "deworming": fields.get('sverminazione'),
            "image_urls": images,
        }
