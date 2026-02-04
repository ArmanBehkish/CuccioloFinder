import scrapy
from loguru import logger
from scrapy_playwright.page import PageMethod

from cucciolofinder.config import SHELTER_SITES


class EmpethySpider(scrapy.Spider):
    name = "EmpethySpider"
    custom_settings = {
        "ITEM_PIPELINES": {
            "cucciolofinder.scrapers.pipelines.EmpethyPipeline": 1,
            "cucciolofinder.scrapers.pipelines.DatabasePipeline": 14,
        },
        "IMAGES_STORE": "data/images",
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    }
    start_url = SHELTER_SITES["empethy"].url

    # JS to click "Carica altri"
    LOAD_ALL_SCRIPT = """
        async () => {
            const sleep = ms => new Promise(r => setTimeout(r, 2000));
            while (true) {
                const buttons = [...document.querySelectorAll('button')];
                const loadMore = buttons.find(b => b.textContent.includes('Carica altri'));
                if (!loadMore) break;
                loadMore.click();
                await sleep(2000);
            }
        }
    """

    def start_requests(self):
        logger.debug(f"start URL is: {self.start_url}")
        # listing page is JS rendered
        yield scrapy.Request(
            url=self.start_url,
            meta={
                "playwright": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_selector", "a[href*='/adozione']", timeout=10000),
                    # JS Loop
                    PageMethod("evaluate", self.LOAD_ALL_SCRIPT),
                    PageMethod("wait_for_timeout", 2000),
                ],
            },
            callback=self.parse,
        )

    def parse(self, response):
        # Extract dog detail links from JS-rendered page
        dog_links = response.css(".group.relative a[href*='/adozione']::attr(href)").getall()
        # Deduplicate
        dog_links = list(set(dog_links))
        logger.debug(f"Found {len(dog_links)} dog links on listing page")

        for link in dog_links:
            yield response.follow(link, callback=self.parse_dog_detail)

    def parse_dog_detail(self, response):
        # TODO: saw a cat coming in, add a check

        # Name
        name = response.css("h2.font-semibold::text").get()
        if name:
            name = name.strip()

        # Images - only from the photo grid container
        images = response.css("div.grid-cols-4 img[src*='supabase']::attr(src)").getall()
        images = list(set(images))  # deduplicate

        # La mia storia
        description = self._extract_section_text(response, "La mia storia")

        # Le mie caratteristiche - parse into individual fields
        characteristics = self._extract_section_items(response, "Le mie caratteristiche")
        char_fields = self._parse_characteristics(characteristics)

        # Mi trovo bene con...list of friends
        good_with = self._extract_section_items(response, "Mi trovo bene con")

        # Non mi trovo bene con...list of foes
        bad_with = self._extract_section_items(response, "Non mi trovo bene con")

        logger.debug(f"Dog {name}, description: {description}, characteristics: {char_fields}, good with: {good_with}, bad with: {bad_with}, source URL: {response.url}")

        yield {
            "source_url": response.url,
            "name": name,
            "description": description,
            "gender": char_fields["gender"],
            "breed": char_fields["breed"],
            "size": char_fields["size"],
            "weight": char_fields["weight"],
            "fur": char_fields["fur"],
            "age": char_fields["age"],
            "deworming": char_fields["deworming"],
            "vaccine": char_fields["vaccine"],
            "microchip": char_fields["microchip"],
            "sterilization": char_fields["sterilization"],
            "good_with": good_with,
            "bad_with": bad_with,
            "image_urls": images,
        }

    def _extract_section_text(self, response, heading):
        """Extract paragraph text from a section identified by its heading."""
        section = response.xpath(
            f"//h2[contains(text(), '{heading}')]/ancestor::div[contains(@class, 'lightBorder')]"
        )
        if not section:
            section = response.xpath(
                f"//h2[contains(text(), '{heading}')]/.."
            )
        if section:
            texts = section.css("p::text").getall()
            return " ".join(t.strip() for t in texts if t.strip())
        logger.warning(f"Section '{heading}' not found")
        return None

    def _extract_section_items(self, response, heading):
        """Extract list items from a section identified by its heading."""
        section = response.xpath(
            f"//h2[contains(text(), '{heading}')]/ancestor::div[contains(@class, 'lightBorder')]"
        )
        if not section:
            section = response.xpath(
                f"//h2[contains(text(), '{heading}')]/.."
            )
        if section:
            # Get all text nodes that are actual content (not just whitespace)
            items = section.css("span::text, p::text, div::text").getall()
            items = [i.strip() for i in items if i.strip() and i.strip() != heading]
            return items
        logger.warning(f"Section '{heading}' not found")
        return []

    @staticmethod
    def _parse_characteristics(items: list[str]) -> dict:
        """Parse the characteristics list into individual fields."""
        fields = {
            "gender": None,
            "breed": None,
            "size": None,
            "weight": None,
            "fur": None,
            "age": None,
            "deworming": None,
            "vaccine": None,
            "microchip": None,
            "sterilization": None,
        }
        for item in items:
            lower = item.lower()
            if ":" in item:
                key, val = item.split(":", 1)
                val = val.strip()
                key_lower = key.strip().lower()
                if "razza" in key_lower:
                    fields["breed"] = val
                elif "taglia" in key_lower:
                    fields["size"] = val
                elif "peso" in key_lower:
                    fields["weight"] = val
                elif "pelo" in key_lower:
                    fields["fur"] = val
                elif "et" in key_lower:
                    fields["age"] = val
            elif lower in ("maschio", "femmina"):
                fields["gender"] = lower
            elif "sverminat" in lower:
                fields["deworming"] = item
            elif "vaccinat" in lower:
                fields["vaccine"] = item
            elif "microchip" in lower:
                fields["microchip"] = item
            elif "sterilizzat" in lower:
                fields["sterilization"] = item
        return fields
