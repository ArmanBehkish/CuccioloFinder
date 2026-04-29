import os
from datetime import datetime

import scrapy
from loguru import logger

from cucciolofinder.config import SCRAPE_LIMIT_PER_SPIDER, SHELTER_SITES

ITALIAN_MONTHS_FULL: dict[str, int] = {
    "Gennaio": 1, "Febbraio": 2, "Marzo": 3, "Aprile": 4,
    "Maggio": 5, "Giugno": 6, "Luglio": 7, "Agosto": 8,
    "Settembre": 9, "Ottobre": 10, "Novembre": 11, "Dicembre": 12,
}


class CanileOasiSpider(scrapy.Spider):
    name = "CanileOasiSpider"
    _scraped = 0  # quick-test counter, bounded by SCRAPE_LIMIT_PER_SPIDER
    custom_settings = {
        "ITEM_PIPELINES": {
            "cucciolofinder.scrapers.pipelines.IdentityPipeline": 1,
            "cucciolofinder.scrapers.pipelines.CanileOasiPipeline": 5,
            "cucciolofinder.scrapers.pipelines.DatabasePipeline": 14,
        },
        "IMAGES_STORE": os.environ.get("IMAGES_PATH", "data/images"),
        # Scrapy header is blocked
        "USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.start_url = SHELTER_SITES["canileoasi"].url

    def start_requests(self):
        yield scrapy.Request(url=self.start_url, callback=self.parse)

    def parse(self, response: scrapy.http.Response):
        cards = response.css("div.wf-cell.iso-item")
        logger.debug(f"Found {len(cards)} dog cards")

        for card in cards:
            if SCRAPE_LIMIT_PER_SPIDER is not None and self._scraped >= SCRAPE_LIMIT_PER_SPIDER:
                logger.info(f"SCRAPE_LIMIT_PER_SPIDER={SCRAPE_LIMIT_PER_SPIDER} reached, stopping")
                return
            detail_url = card.css("h3.entry-title a::attr(href)").get()
            if detail_url:
                self._scraped += 1
                yield response.follow(detail_url, callback=self.parse_dog_detail)

    def _parse_italian_date_full(self, date_str: str) -> datetime | None:
        """Parse date like '7 Aprile 2021' """
        try:
            parts = date_str.strip().split()
            day = int(parts[0])
            month = ITALIAN_MONTHS_FULL.get(parts[1])
            year = int(parts[2])
            if month:
                return datetime(year, month, day)
        except (ValueError, IndexError):
            logger.warning(f"Could not parse date: {date_str}")
        return None

    def parse_dog_detail(self, response: scrapy.http.Response) -> dict:
        raw_name = response.css("h1.entry-title::text").get()
        if raw_name:
            name = raw_name.strip()
            logger.debug(f"Dog name: {name}")
        else:
            raise ValueError("Dog's name missing!")

        # Gender from icon
        gender_src = response.css("img.iconasesso::attr(src)").get()
        gender = None
        if gender_src:
            if "maschio" in gender_src:
                gender = "maschio"
            elif "femmina" in gender_src:
                gender = "femmina"

        # Età, Peso, Con noi da
        acf_fields = response.css("div.vc_acf.madai")
        age = None
        weight = None
        shelter_since = None
        shelter_since_date = None
        for field in acf_fields:
            label = field.css("span.vc_acf-label::text").get()
            if not label:
                continue
            # Get all text nodes and join, then strip the label part
            full_texts = field.css("::text").getall()
            value = " ".join(t.strip() for t in full_texts if t.strip())
            value = value.replace(label.strip(), "").strip()

            label_clean = label.strip().rstrip(":").lower()
            if "et" in label_clean:
                age = value
            elif "peso" in label_clean:
                weight = value
            elif "con noi" in label_clean:
                shelter_since = value
                shelter_since_date = self._parse_italian_date_full(value)

        # Compatibility criteria
        criteria = {}
        for crit in response.css("div.criteriadozione div.iconacriteri"):
            texts = crit.css("::text").getall()
            joined = " ".join(t.strip() for t in texts if t.strip())
            if ":" in joined:
                key, val = joined.split(":", 1)
                criteria[key.strip()] = val.strip()

        # Description
        paragraphs = response.css("div.wpb_text_column .wpb_wrapper p")
        description_parts = []
        for p in paragraphs:
            text = p.css("::text").getall()
            joined = " ".join(t.strip() for t in text if t.strip())
            if joined:
                description_parts.append(joined)
        description = "\n".join(description_parts)

        # Gallery images (full-size URLs from carousel)
        images = response.css("a.dt-pswp-item::attr(href)").getall()
        logger.debug(f"Found {len(images)} images for {name}")

        # check info
        logger.debug(f"Dog: {name}, gender: {gender}, age: {age}, weight: {weight}, in shelter since: {shelter_since_date.isoformat()}, other criteria: {criteria}, descriptions: {description}, source URL: {response.url}")

        yield {
            "source_url": response.url,
            "name": name,
            "gender": gender,
            "age": age,
            "weight": weight,
            "shelter_since": shelter_since_date.isoformat() if shelter_since_date else shelter_since,
            "criteria": criteria,
            "description": description,
            "image_urls": images,
        }
