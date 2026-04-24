import os

import scrapy
from loguru import logger
from scrapy_playwright.page import PageMethod

from cucciolofinder.config import SHELTER_SITES
from .pipelines import QuattroImagesPipeline


class QuattroZampeSpider(scrapy.Spider):
    name = "QuattrozampeSpider"
    custom_settings = {
        "ITEM_PIPELINES": {
            "cucciolofinder.scrapers.pipelines.QuattroImagesPipeline": 1,
            "cucciolofinder.scrapers.pipelines.DatabasePipeline": 14,
        },
        "IMAGES_STORE": os.environ.get("IMAGES_PATH", "data/images"),
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }
    start_url = SHELTER_SITES["quattrozampeinfamiglia"].url
    pages = set()

    # JS to click "Vedi altri animali" until all dogs are loaded
    LOAD_ALL_SCRIPT = """
        async () => {
            const sleep = ms => new Promise(r => setTimeout(r, ms));
            let clicks = 0;
            while (clicks < 50) {
                const btn = [...document.querySelectorAll('a, button')].find(
                    el => el.textContent.trim().toLowerCase().includes('Vedi altri')
                );
                if (!btn) break;
                btn.click();
                clicks++;
                await sleep(6000);
            }
        }
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.seen_names: dict[str, int] = {}

    def _unique_name(self, name: str) -> str:
        """Take care of repetitive names."""
        if name in self.seen_names:
            self.seen_names[name] += 1
            return f"{name}__{self.seen_names[name]:02d}"
        self.seen_names[name] = 1
        return name

    def start_requests(self):
        yield scrapy.Request(
            url=self.start_url,
            meta={
                "playwright": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_selector", "article.wdo-pt-slide", timeout=15000),
                    PageMethod("evaluate", self.LOAD_ALL_SCRIPT),
                    PageMethod("wait_for_timeout", 2000),
                ],
            },
            callback=self.parse,
        )

    def parse(self, response):
        # Old selector (site redesigned ~2026-04):
        # dog_cards = response.xpath("/html/body/div[1]/section[2]/div/div[3]/div/div/div/div/article")
        dog_cards = response.css("article.wdo-pt-slide")
        logger.info(f"Found {len(dog_cards)} dog cards after loading all pages")

        for card in dog_cards:
            inside_link = card.css("a::attr(href)").get()
            if "torino" in str(inside_link):
                self.pages.add(inside_link)
                yield response.follow(inside_link, callback=self.parse_dog_detail)

        # Old pagination (site now uses AJAX "Load More"):
        # next_page = response.xpath("//a[contains(@class, 'next')]/@href").get()
        # if next_page:
        #     yield response.follow(next_page, callback=self.parse)

    def parse_dog_detail(self, response):

        images = response.xpath("//section[4]/div//img/@src").getall()
        images = [img for img in images if "spazio_foto" not in img and not img.startswith("data:")]

        desc = response.xpath("/html/body/div[1]/section[5]/div/div[2]")
        raw_name = desc.css("h2::text").get()
        name = self._unique_name(raw_name.strip()) if raw_name else None

        # Description
        desc_parts = response.css("div.geodir-field-mi_presento p::text").getall()
        description = " ".join(t.strip() for t in desc_parts if t.strip())

        # Characteristics
        fields = self._parse_characteristics(response)

        # Good with - list items under adatto a
        good_with = response.css("div.geodir-field-adatto_a li::text").getall()
        good_with = [g.strip() for g in good_with if g.strip()]

        # Bad with - spans containing "non adatto"
        bad_with = []
        for span in response.css("span.geodir-dynamic-content"):
            text = span.css("::text").getall()
            joined = " ".join(t.strip() for t in text if t.strip())
            if "non adatto" in joined.lower():
                # Extract the category name (text before "non adatto")
                category = joined.lower().replace("non adatto", "").strip()
                if category:
                    bad_with.append(category.capitalize())

        logger.debug(
            f"Dog: {name}, gender: {fields.get('sesso')}, age: {fields.get('età')}, breed: {fields.get('razza cane')}, fur: {fields.get('pelo')}, size: {fields.get('taglia')}, weight: {fields.get('peso kg')}, good_with: {good_with}, bad_with: {bad_with}, description: {description}, source URL: {response.url}"
        )

        yield {
            "source_url": response.url,
            "name": name,
            "description": description,
            "age": fields.get("età"),
            "gender": fields.get("sesso"),
            "breed": fields.get("razza cane"),
            "fur": fields.get("pelo"),
            "size": fields.get("taglia"),
            "weight": fields.get("peso kg"),
            "microchip": fields.get("microchip"),
            "sterilization": fields.get("sterilizzazione"),
            "vaccine": fields.get("vaccinazioni"),
            "deworming": fields.get("sverminazione"),
            "good_with": good_with,
            "bad_with": bad_with,
            "image_urls": images,
        }

    @staticmethod
    def _parse_characteristics(response):
        characteristics = {}
        for item in response.css("div.geodir_post_meta"):
            label = item.css("span.geodir_post_meta_title::text").get()
            if label:
                label = label.strip().rstrip(":").strip().lower()
                if label not in characteristics:
                    value = item.xpath("text()").get()
                    characteristics[label] = value.strip() if value else None
        return characteristics
