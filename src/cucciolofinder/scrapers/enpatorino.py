import os
from datetime import datetime, timedelta

import scrapy
from loguru import logger

from cucciolofinder.config import SHELTER_SITES

ITALIAN_MONTHS: dict[str, int] = {
    "Gen": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "Mag": 5, "Giu": 6, "Lug": 7, "Ago": 8,
    "Set": 9, "Ott": 10, "Nov": 11, "Dic": 12,
}

CATEGORY_PATHS = [
    "category/i-nostri-ospiti/cani/cani-taglia-grande/",
    "category/i-nostri-ospiti/cani/cani-taglia-media/",
    "category/i-nostri-ospiti/cani/cani-taglia-piccola/",
]

# Only scrape new items
MAX_AGE_DAYS = 365


class EnpaTorinoSpider(scrapy.Spider):
    name = "EnpaTorinoSpider"
    custom_settings = {
        "ITEM_PIPELINES": {
            "cucciolofinder.scrapers.pipelines.EnpaTorinoPipeline": 1,
            "cucciolofinder.scrapers.pipelines.DatabasePipeline": 14,
        },
        "IMAGES_STORE": os.environ.get("IMAGES_PATH", "data/images"),
    }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.base_url = SHELTER_SITES["enpatorino"].url
        self.cutoff_date = datetime.now() - timedelta(days=MAX_AGE_DAYS)
        self.seen_names: dict[str, int] = {}

    def start_requests(self):
        # TODO: extract paths to make it more robust
        for path in CATEGORY_PATHS:
            url = f"{self.base_url}{path}"
            yield scrapy.Request(url=url, callback=self.parse)

    def parse(self, response):
        articles = response.css("article.post")
        logger.debug(f"Found {len(articles)} items on {response.url}")

        has_recent = False

        for article in articles:
            date_text = article.css("p.post-date::text").get()
            detail_url = article.css("h2.post-title a::attr(href)").get()
            name = article.css("h2.post-title a::text").get()

            if not date_text or not detail_url:
                continue

            post_date = self._parse_italian_date(date_text)
            if not post_date:
                continue

            if post_date >= self.cutoff_date:
                has_recent = True
                logger.debug(f"[RECENT ITEM:] Name: {name} Date:({post_date.isoformat()}) -> URL: {detail_url}")
                yield response.follow(
                    detail_url,
                    callback=self.parse_dog_detail,
                    cb_kwargs={"post_date": post_date},
                )
            else:
                logger.debug(f"[OLD ITEM:] Name: {name} Date:({post_date.isoformat()}) -> URL: {detail_url} -- skipping)")

        # next page if this page had recent items
        if has_recent:
            next_page = response.css("a.nextpostslink::attr(href)").get()
            if next_page:
                logger.info(f"Following next page: {next_page}")
                yield response.follow(next_page, callback=self.parse)

    def _unique_name(self, name: str) -> str:
        """Take care of repetitive names."""
        if name in self.seen_names:
            self.seen_names[name] += 1
            return f"{name}__{self.seen_names[name]:02d}"
        self.seen_names[name] = 1
        return name

    def parse_dog_detail(self, response, post_date):
        raw_name = response.css("h1.post-title::text").get()
        if raw_name:
            name = self._unique_name(raw_name or "unknown")
        else:
            raise ValueError("Dog's name missing!")

        # Description paragraphs inside entry-inner, skip empty ones
        paragraphs = response.css("div.entry-inner p")
        description_parts = []
        for p in paragraphs:
            text = p.css("::text").getall()
            joined = " ".join(t.strip() for t in text if t.strip())
            if joined:
                description_parts.append(joined)
        description = "\n".join(description_parts)

        # Full-size images from the entry content
        images = response.css("div.entry-inner img.size-full::attr(src)").getall()

        logger.debug(f"Dog: {name}, descriptoin: {description}, post_date: {post_date.isoformat()}, source URL: {response.url}")

        yield {
            "source_url": response.url,
            "name": name,
            "post_date": post_date.isoformat(),
            "description": description,
            "image_urls": images,
        }


    def _parse_italian_date(self, date_str):
        """Parse Italian dates into datetime."""
        try:
            parts = date_str.strip().replace(",", "").split()
            day = int(parts[0])
            month = ITALIAN_MONTHS.get(parts[1])
            year = int(parts[2])
            if month:
                return datetime(year, month, day)
        except (ValueError, IndexError):
            logger.warning(f"Could not parse date: {date_str}")
        return None
