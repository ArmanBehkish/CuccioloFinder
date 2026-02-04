from datetime import datetime
from urllib.parse import unquote

from loguru import logger
from scrapy.pipelines.images import ImagesPipeline

from cucciolofinder.database import Dog, DogImage, get_engine, get_session, init_db


class QuattroImagesPipeline(ImagesPipeline):
    def file_path(self, request, response=None, info=None, *, item=None):
        dog_name = item.get("name", "unknown").replace(" ", "_")
        ext = request.url.split("?")[0].split(".")[-1]
        decoded_url = unquote(request.url)
        image_urls = item.get("image_urls", [])

        try:
            image_index = image_urls.index(decoded_url)
        except ValueError:
            image_index = hash(request.url) % 10000

        return f"QuattroZampe_{dog_name}_{image_index}.{ext}"
    
class AlberoDiMaisPipeline(ImagesPipeline):
    def file_path(self, request, response=None, info=None, *, item=None):
        dog_name = item.get("name", "unknown").replace(" ", "_")
        # Google Cloud Storage URL
        ext = "jpg"
        image_urls = item.get("image_urls", [])
        
        try:
            image_index = image_urls.index(request.url)
        except ValueError:
            image_index = hash(request.url) % 10000

        return f"AlberoDiMais_{dog_name}_{image_index}.{ext}"


class EmpethyPipeline(ImagesPipeline):
    def file_path(self, request, response=None, info=None, *, item=None):
        dog_name = item.get("name", "unknown").replace(" ", "_")
        # Supabase URLs have no file extension
        ext = "jpg"
        image_urls = item.get("image_urls", [])

        try:
            image_index = image_urls.index(request.url)
        except ValueError:
            image_index = hash(request.url) % 10000

        return f"Empethy_{dog_name}_{image_index}.{ext}"
    

class EnpaTorinoPipeline(ImagesPipeline):
    def file_path(self, request, response=None, info=None, *, item=None):
        dog_name = item.get("name", "unknown").replace(" ", "_")
        ext = request.url.split("?")[0].split(".")[-1] or "jpg"
        image_urls = item.get("image_urls", [])

        try:
            image_index = image_urls.index(request.url)
        except ValueError:
            image_index = hash(request.url) % 10000

        return f"EnpaTorino_{dog_name}_{image_index}.{ext}"


class CanileOasiPipeline(ImagesPipeline):
    def file_path(self, request, response=None, info=None, *, item=None):
        dog_name = item.get("name", "unknown").replace(" ", "_")
        ext = request.url.split("?")[0].split(".")[-1] or "jpg"
        image_urls = item.get("image_urls", [])

        try:
            image_index = image_urls.index(request.url)
        except ValueError:
            image_index = hash(request.url) % 10000

        return f"CanileOasi_{dog_name}_{image_index}.{ext}"


SPIDER_SOURCE_MAP = {
    "QuattrozampeSpider": "quattrozampe",
    "AlberoDiMaisSpider": "alberodimais",
    "EmpethySpider": "empethy",
    "EnpaTorinoSpider": "enpatorino",
    "CanileOasiSpider": "canileoasi",
}

# No transformation, direct mapping
DOG_DIRECT_FIELDS = [
    "source_url", "name", "gender", "age", "weight", "size",
    "breed", "fur", "microchip", "sterilization", "vaccine",
    "deworming", "shelter_since", "good_with", "bad_with",
]


class DatabasePipeline:
    def open_spider(self, spider):
        self.engine = get_engine()
        init_db(self.engine)
        self.Session = get_session(self.engine)

    def process_item(self, item, spider):
        source_site = SPIDER_SOURCE_MAP.get(spider.name, spider.name)

        # Normalizations

        # AlberoDiMais: descriptions (list) -> description (str)
        if "descriptions" in item:
            description = "\n".join(
                t.strip() for t in item["descriptions"] if t.strip()
            )
        else:
            description = item.get("description")

        # CanileOasi: criteria dict -> append to description
        criteria = item.get("criteria")
        if criteria:
            criteria_text = "\n".join(f"{k}: {v}" for k, v in criteria.items())
            if description:
                description = f"{description}\n\n{criteria_text}"
            else:
                description = criteria_text

        # EnpaTorino: post_date ISO string -> date object
        post_date = None
        if "post_date" in item and item["post_date"]:
            post_date = datetime.fromisoformat(item["post_date"]).date()

        # BUILD ROW
        dog_data = {"source_site": source_site, "description": description, "post_date": post_date}
        for field in DOG_DIRECT_FIELDS:
            if field in item:
                dog_data[field] = item[field]

        # --- Upsert ---
        with self.Session() as session:
            existing = session.query(Dog).filter_by(source_url=item["source_url"]).first()
            if existing:
                # update existing row
                for key, value in dog_data.items():
                    setattr(existing, key, value)
                dog = existing
            else:
                # insert new dog
                dog = Dog(**dog_data)
                session.add(dog)

            session.flush()

            # url -> local_path (normalize with unquote to handle encoded URLs)
            image_path_map = {}
            for result in item.get("images", []):
                image_path_map[result["url"]] = result["path"]
                image_path_map[unquote(result["url"])] = result["path"]

            # Replace/add images
            session.query(DogImage).filter_by(dog_id=dog.id).delete()
            for i, url in enumerate(item.get("image_urls", [])):
                local_path = image_path_map.get(url) or image_path_map.get(unquote(url))
                # if not local_path:
                #     logger.debug(f"No local_path match for URL: {url}")
                session.add(DogImage(dog_id=dog.id, url=url, local_path=local_path, position=i))

            session.commit()
            logger.debug(f"DATABASE: Saved dog '{dog.name}' (id={dog.id}) from {source_site}")

        return item