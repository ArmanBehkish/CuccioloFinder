import re
from datetime import datetime, timezone
from urllib.parse import unquote

from loguru import logger
from scrapy.exceptions import DropItem
from scrapy.pipelines.images import ImagesPipeline

from cucciolofinder.database import (
    Dog,
    DogImage,
    InferredDogBreed,
    get_engine,
    get_session,
    init_db,
    resolve_dog_identity,
)

FROM_DESC_COLUMNS = [
    "gender_from_desc", "age_from_desc", "weight_from_desc", "size_from_desc",
    "breed_from_desc", "fur_from_desc", "microchip_from_desc",
    "sterilization_from_desc", "vaccine_from_desc", "deworming_from_desc",
    "good_with_from_desc", "bad_with_from_desc",
]

# Methods invalidated when the image set changes. Membership only —
# re-orderings without a new/dropped image don't change classifier output,
# so we don't waste a re-run on them.
IMAGE_DERIVED_BREED_METHODS = frozenset({"image", "image_2nd"})


SPIDER_SOURCE_MAP = {
    "QuattrozampeSpider": "quattrozampe",
    "AlberoDiMaisSpider": "alberodimais",
    "EmpethySpider": "empethy",
    "EnpaTorinoSpider": "enpatorino",
    "CanileOasiSpider": "canileoasi",
}


class IdentityPipeline:
    """Resolve dog_uid + generation before image download or DB write.

    Runs at priority 1 so the image pipelines (priority >1) can use
    `item["dog_uid"]` as the filename token, and DatabasePipeline (priority
    14) can use `item["generation"]` and `item["_supersede_id"]`.

    `_skip_persist=True` is set when the active row is already up-to-date
    with what we just scraped — DatabasePipeline drops the item without
    writing.
    """

    def open_spider(self, spider):
        self.engine = get_engine()
        init_db(self.engine)
        self.Session = get_session(self.engine)

    def process_item(self, item, spider):
        source_site = SPIDER_SOURCE_MAP.get(spider.name, spider.name)
        source_url = item["source_url"]
        image_urls = item.get("image_urls") or []

        with self.Session() as session:
            identity = resolve_dog_identity(
                session, source_site, source_url, image_urls
            )

        item["dog_uid"] = identity.dog_uid
        item["generation"] = identity.generation
        item["_supersede_id"] = identity.supersede_id
        return item


class _DogImagesPipeline(ImagesPipeline):
    """Shared base for per-shelter image pipelines.

    Filename pattern: `{prefix}_{dog_uid}_{index}.{ext}`. Subclasses set
    `prefix` and `ext` (or override `_extension`).
    """

    prefix: str = "Dog"
    ext: str | None = None  # None -> derive from URL

    def _extension(self, request_url: str) -> str:
        if self.ext:
            return self.ext
        return request_url.split("?")[0].split(".")[-1] or "jpg"

    def file_path(self, request, response=None, info=None, *, item=None):
        dog_uid = item["dog_uid"]
        ext = self._extension(request.url)
        image_urls = item.get("image_urls", [])
        decoded_url = unquote(request.url)

        try:
            image_index = image_urls.index(decoded_url)
        except ValueError:
            try:
                image_index = image_urls.index(request.url)
            except ValueError:
                image_index = hash(request.url) % 10000

        return f"{self.prefix}_{dog_uid}_{image_index}.{ext}"


class QuattroImagesPipeline(_DogImagesPipeline):
    prefix = "QuattroZampe"


class AlberoDiMaisPipeline(_DogImagesPipeline):
    prefix = "AlberoDiMais"
    ext = "jpg"  # Google Cloud Storage URLs have no file extension


class EmpethyPipeline(_DogImagesPipeline):
    prefix = "Empethy"
    ext = "jpg"  # Supabase URLs have no file extension


class EnpaTorinoPipeline(_DogImagesPipeline):
    prefix = "EnpaTorino"


class CanileOasiPipeline(_DogImagesPipeline):
    prefix = "CanileOasi"


# No transformation, direct mapping
DOG_DIRECT_FIELDS = [
    "source_url", "name", "gender", "age", "weight", "size",
    "breed", "fur", "microchip", "sterilization", "vaccine",
    "deworming", "shelter_since", "good_with", "bad_with",
]

# Fields with english translation
TRANSLATABLE_FIELDS = [
    "description", "gender", "age", "size", "breed", "fur",
    "microchip", "sterilization", "vaccine", "deworming",
    "good_with", "bad_with",
]


def _normalize_dog_data(item: dict, source_site: str) -> tuple[dict, object]:
    """Apply per-source quirks and return (dog_data, post_date).

    Mirrors the normalization that previously lived inline in
    DatabasePipeline.process_item.
    """
    # AlberoDiMais: descriptions (list) -> description (str)
    if "descriptions" in item:
        description = "\n".join(t.strip() for t in item["descriptions"] if t.strip())
    else:
        description = item.get("description")

    # CanileOasi: criteria dict -> append to description
    criteria = item.get("criteria")
    if criteria:
        criteria_text = "\n".join(f"{k}: {v}" for k, v in criteria.items())
        description = f"{description}\n\n{criteria_text}" if description else criteria_text

    # CanileOasi: strip "Guarda Tutti i Nostri X Cani in Adozione"
    if description and source_site == "canileoasi":
        description = re.sub(r"Guarda Tutti i Nostri (\d+ )?Cani in Adozione\s*", "", description)

    # EnpaTorino: post_date ISO string -> date object
    post_date = None
    if item.get("post_date"):
        post_date = datetime.fromisoformat(item["post_date"]).date()

    dog_data = {"source_site": source_site, "description": description, "post_date": post_date}
    for field in DOG_DIRECT_FIELDS:
        if field in item:
            dog_data[field] = item[field]
    return dog_data, post_date


def _has_changes(existing: Dog, dog_data: dict, image_urls: list[str]) -> bool:
    """True if any scraped field differs from what's stored."""
    for key, new_value in dog_data.items():
        if getattr(existing, key) != new_value:
            return True

    stored_urls = [
        img.url
        for img in sorted(
            existing.images,
            key=lambda i: i.position if i.position is not None else 999,
        )
    ]
    return stored_urls != list(image_urls or [])


class DatabasePipeline:
    def open_spider(self, spider):
        self.engine = get_engine()
        init_db(self.engine)
        self.Session = get_session(self.engine)

    def process_item(self, item, spider):
        source_site = SPIDER_SOURCE_MAP.get(spider.name, spider.name)
        dog_data, _ = _normalize_dog_data(item, source_site)
        image_urls = item.get("image_urls") or []

        with self.Session() as session:
            # Supersede the recycled-URL row if IdentityPipeline flagged one.
            supersede_id = item.get("_supersede_id")
            if supersede_id is not None:
                old = session.query(Dog).filter_by(id=supersede_id).first()
                if old is not None:
                    old.superseded_at = datetime.now(timezone.utc)

            existing = (
                session.query(Dog)
                .filter_by(
                    source_site=source_site,
                    source_url=item["source_url"],
                    superseded_at=None,
                )
                .first()
            )

            if existing and supersede_id is None:
                # Same physical dog, listing being refreshed.
                if not _has_changes(existing, dog_data, image_urls):
                    logger.debug(
                        f"DATABASE: No changes for '{existing.name}' (uid={existing.dog_uid}), skipping write"
                    )
                    raise DropItem("unchanged")

                # Capture the image-set diff before the DogImage delete+re-add
                # below mutates `existing.images`. Set-equality (not order).
                images_changed = {img.url for img in existing.images} != set(image_urls)

                description_changed = False
                for key, value in dog_data.items():
                    old_value = getattr(existing, key)
                    setattr(existing, key, value)
                    if old_value != value:
                        if key == "description":
                            description_changed = True
                        if key in TRANSLATABLE_FIELDS:
                            en_field = f"{key}_en"
                            if hasattr(existing, en_field):
                                setattr(existing, en_field, None)
                                logger.debug(f"Cleared {en_field} for dog '{existing.name}' (field changed)")

                if description_changed:
                    for col in FROM_DESC_COLUMNS:
                        setattr(existing, col, None)
                    logger.debug(
                        f"Description changed for dog '{existing.name}': cleared *_from_desc"
                    )

                if images_changed:
                    deleted_img = (
                        session.query(InferredDogBreed)
                        .filter(
                            InferredDogBreed.dog_id == existing.id,
                            InferredDogBreed.method.in_(IMAGE_DERIVED_BREED_METHODS),
                        )
                        .delete(synchronize_session=False)
                    )
                    logger.debug(
                        f"Image set changed for dog '{existing.name}': "
                        f"deleted {deleted_img} image-derived inferred_dog_breeds rows"
                    )

                dog = existing
            else:
                dog = Dog(
                    **dog_data,
                    dog_uid=item["dog_uid"],
                    generation=item["generation"],
                )
                session.add(dog)

            session.flush()

            image_path_map = {}
            for result in item.get("images", []):
                image_path_map[result["url"]] = result["path"]
                image_path_map[unquote(result["url"])] = result["path"]

            session.query(DogImage).filter_by(dog_id=dog.id).delete()
            for i, url in enumerate(image_urls):
                local_path = image_path_map.get(url) or image_path_map.get(unquote(url))
                session.add(DogImage(dog_id=dog.id, url=url, local_path=local_path, position=i))

            session.commit()
            logger.debug(f"DATABASE: Saved dog '{dog.name}' (id={dog.id}, uid={dog.dog_uid}) from {source_site}")

        return item
