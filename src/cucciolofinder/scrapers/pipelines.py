from urllib.parse import unquote

from scrapy.pipelines.images import ImagesPipeline


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