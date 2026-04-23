import os

from loguru import logger

# Static mapping for common Italian words
TRANSLATION_MAP: dict[str, str] = {
    # gender
    "maschio": "male",
    "femmina": "female",
    # size
    "piccola": "small",
    "piccolo": "small",
    "Piccola": "small",
    "media": "medium",
    "medio": "medium",
    "Media": "medium",
    "grande": "large",
    "Grande": "large",
    "Gigante": "giant",
    "medio-grande": "medium-large",
    "medio-piccola": "medium-small",
    "Media contenuta": "medium contained",
    # yes/no values
    "si": "yes",
    "sì": "yes",
    "Sì": "yes",
    "no": "no",
    # vaccine
    "Vaccinato": "yes",
    # sterilization
    "Sterilizzato": "yes",
    "Non sterilizzato": "no",
    # deworming
    "Sverminato": "yes",
    # microchip
    "Dotato di microchip": "yes",
    # fur
    "corto": "short",
    "lungo": "long",
    # good_with / bad_with items
    "Bambini": "children",
    "bambini": "children",
    "Persone anziane": "elderly",
    "persone anziane": "elderly",
    "Gatti maschi": "male cats",
    "gatti maschi": "male cats",
    "Gatti femmina": "female cats",
    "gatti femmina": "female cats",
    "Cani maschi": "male dogs",
    "cani maschi": "male dogs",
    "Cani maschi interi": "unneutered male dogs",
    "cani maschi interi": "unneutered male dogs",
    "Cani femmina": "female dogs",
    "cani femmina": "female dogs",
    "Cani femmina intere": "unspayed female dogs",
    "cani femmina intere": "unspayed female dogs",
}


class TranslationService:
    """HF API for dev env., local model on prod"""

    def __init__(self) -> None:
        self.use_local = bool(os.environ.get("USE_LOCAL_MODEL"))
        self.model_name = os.environ.get("TRANSLATION_MODEL_ID", "Helsinki-NLP/opus-mt-it-en")
        self._client = None
        self._tokenizer = None
        self._model = None

    def _get_api_client(self):
        """HF Inference API"""
        if self._client is None:
            from huggingface_hub import InferenceClient

            self._client = InferenceClient(
                provider="hf-inference",
                api_key=os.environ["HF_TOKEN"],
            )
        return self._client

    def _get_local_model(self):
        """local transformers model."""
        if self._tokenizer is None:
            from transformers import MarianMTModel, MarianTokenizer

            self._tokenizer = MarianTokenizer.from_pretrained(self.model_name)
            self._model = MarianMTModel.from_pretrained(self.model_name)
        return self._tokenizer, self._model

    def _translate_api(self, text: str) -> str:
        """Translate using HF Inference API."""
        client = self._get_api_client()
        result = client.translation(text, model=self.model_name)
        return result.translation_text

    def _translate_local(self, text: str) -> str:
        """Translate using local transformers model."""
        tokenizer, model = self._get_local_model()
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        translated = model.generate(**inputs, max_length=512)
        return tokenizer.decode(translated[0], skip_special_tokens=True)

    def translate(self, text: str) -> str:
        """Translate text using configured backend."""
        if not text or not text.strip():
            return ""

        if self.use_local:
            return self._translate_local(text)
        return self._translate_api(text)

    def translate_field(self, value: str) -> str:
        """Translate a field value. Tries static map first, falls back to model."""
        if not value:
            return ""

        value_stripped = value.strip()

        if value_stripped in TRANSLATION_MAP:
            return TRANSLATION_MAP[value_stripped]

        logger.debug(f"Unmapped value, using model: '{value_stripped}'")
        return self.translate(value_stripped)

    def translate_list(self, values: list[str] | None) -> list[str] | None:
        """Translate a list of values (e.g., good_with, bad_with)."""
        if not values:
            return None
        return [self.translate_field(v) for v in values]

    _CHUNK_LIMIT = 900

    def _split_description(self, text: str) -> list[str]:
        """Split a long description into two roughly equal parts.

        Looks for a newline or sentence boundary (. ! ?) near the middle.
        Falls back to splitting at the nearest space if no boundary is found.
        """
        if len(text) <= self._CHUNK_LIMIT:
            return [text]

        mid = len(text) // 2
        search_range = len(text) // 4  # look within ±25% of the middle
        left = mid - search_range
        right = mid + search_range

        # Priority 1: newline nearest to middle
        best = None
        for i in range(left, right):
            if text[i] == "\n":
                if best is None or abs(i - mid) < abs(best - mid):
                    best = i

        # Priority 2: sentence boundary (. ! ?) nearest to middle
        if best is None:
            for i in range(left, right):
                if text[i] in ".!?" and i + 1 < len(text) and text[i + 1] == " ":
                    if best is None or abs(i - mid) < abs(best - mid):
                        best = i + 1  # include the punctuation

        # Fallback: nearest space
        if best is None:
            for i in range(left, right):
                if text[i] == " ":
                    if best is None or abs(i - mid) < abs(best - mid):
                        best = i

        if best is None:
            best = mid

        part1 = text[:best].strip()
        part2 = text[best:].strip()
        return [p for p in (part1, part2) if p]

    def translate_description(self, text: str, max_retries: int = 3) -> str:
        """Translate dog description using Mistral via the API container.

        Splits descriptions longer than 900 chars into two parts,
        translates each separately, and combines the results.
        Retries with backoff when the API is unreachable (e.g. OOM restart).
        """
        if not text or not text.strip():
            return ""

        chunks = self._split_description(text.strip())
        logger.info(f"Description ({len(text)} chars) split into {len(chunks)} chunk(s): {[len(c) for c in chunks]}")

        translated_parts = []
        for i, chunk in enumerate(chunks):
            result = self._translate_chunk(chunk, chunk_index=i + 1, total_chunks=len(chunks), max_retries=max_retries)
            if not result:
                logger.warning(f"Chunk {i + 1}/{len(chunks)} translation failed, returning empty")
                return ""
            translated_parts.append(result)

        return "\n\n".join(translated_parts)

    def _translate_chunk(self, text: str, chunk_index: int, total_chunks: int, max_retries: int) -> str:
        """Translate a single chunk with retries."""
        import time

        import requests

        api_url = os.environ.get("API_URL", "http://api:8000")

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Sending chunk {chunk_index}/{total_chunks} ({len(text)} chars) [attempt {attempt}/{max_retries}]")
                resp = requests.post(
                    f"{api_url}/api/translate/description",
                    json={"text": text},
                    timeout=120,
                )
                resp.raise_for_status()
                translation = resp.json().get("translation", "")
                if not translation:
                    logger.warning(f"Chunk {chunk_index}/{total_chunks}: endpoint returned empty")
                    return ""
                logger.info(f"Chunk {chunk_index}/{total_chunks} translated ({len(translation)} chars)")
                return translation
            except requests.exceptions.RequestException as e:
                logger.warning(f"Chunk {chunk_index}/{total_chunks} failed (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    wait = (45, 60, 90)[attempt - 1]
                    logger.info(f"Retrying in {wait}s (API may be restarting)...")
                    time.sleep(wait)

        logger.error(f"Chunk {chunk_index}/{total_chunks} failed after all retries")
        return ""
