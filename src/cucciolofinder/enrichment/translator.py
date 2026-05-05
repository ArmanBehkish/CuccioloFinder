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

    _CHUNK_LIMIT = 800

    def _find_best_boundary(self, text: str, target: int, search_range: int) -> int:
        """Find the best split point near target within ±search_range.

        Priority: newline > sentence boundary (. ! ?) > space > exact target.
        """
        left = max(0, target - search_range)
        right = min(len(text), target + search_range)

        # Priority 1: newline nearest to target
        best = None
        for i in range(left, right):
            if text[i] == "\n":
                if best is None or abs(i - target) < abs(best - target):
                    best = i

        # Priority 2: sentence boundary (. ! ?) nearest to target
        if best is None:
            for i in range(left, right):
                if text[i] in ".!?" and i + 1 < len(text) and text[i + 1] == " ":
                    if best is None or abs(i - target) < abs(best - target):
                        best = i + 1  # include the punctuation

        # Fallback: nearest space
        if best is None:
            for i in range(left, right):
                if text[i] == " ":
                    if best is None or abs(i - target) < abs(best - target):
                        best = i

        return best if best is not None else target

    def _split_description(self, text: str) -> list[str]:
        """Split a long description into chunks of at most ~800 chars each.

        Determines the number of chunks needed, then finds the best
        boundary (newline, sentence, space) near each split point.
        """
        if len(text) <= self._CHUNK_LIMIT:
            return [text]

        import math
        num_chunks = math.ceil(len(text) / self._CHUNK_LIMIT)
        chunk_size = len(text) / num_chunks
        search_range = int(chunk_size * 0.25)  # look within ±25% of each split point

        chunks = []
        start = 0
        for i in range(1, num_chunks):
            target = int(i * chunk_size)
            boundary = self._find_best_boundary(text, target, search_range)
            chunk = text[start:boundary].strip()
            if chunk:
                chunks.append(chunk)
            start = boundary

        # Last chunk
        last = text[start:].strip()
        if last:
            chunks.append(last)

        return chunks

    def translate_description(self, text: str, max_retries: int = 3) -> str:
        """Translate dog description via the configured backend.

        - `TRANSLATION_BACKEND=groq`: single Groq call (Llama 3.3's 128k
          context handles any shelter description in one shot — no chunking,
          no API hop). On failure, optionally falls back to the chunked
          Mistral path when `REMOTE_FALLBACK_TO_MISTRAL=1` AND Mistral is
          loaded in the API container (i.e. `SEARCH_BACKEND=mistral`).
        - `TRANSLATION_BACKEND=openrouter`: single OpenRouter call against
          the same Llama 3.3 70B family — same prompt, same fallback rule.
        - `TRANSLATION_BACKEND=mistral` (default): split into ≤800 char
          chunks at sentence/newline boundaries, translate each via
          `POST /api/translate/description`, retry with backoff.
        """
        if not text or not text.strip():
            return ""

        from cucciolofinder.enrichment.backends import (
            get_fallback_enabled,
            get_search_backend,
            get_translation_backend,
        )

        backend = get_translation_backend()

        if backend == "groq":
            from cucciolofinder.enrichment.groq_client import (
                GroqError,
                groq_translate_description,
            )
            try:
                return groq_translate_description(text.strip())
            except GroqError as exc:
                fallback_eligible = (
                    get_fallback_enabled() and get_search_backend() == "mistral"
                )
                if not fallback_eligible:
                    logger.error(
                        f"Groq translation failed and Mistral fallback unavailable: {exc}"
                    )
                    return ""
                logger.warning(
                    f"Groq translation failed, falling back to Mistral chunked path: {exc}"
                )
                # fall through to the chunked Mistral path
        elif backend == "openrouter":
            from cucciolofinder.enrichment.openrouter_client import (
                OpenRouterError,
                openrouter_translate_description,
            )
            try:
                return openrouter_translate_description(text.strip())
            except OpenRouterError as exc:
                fallback_eligible = (
                    get_fallback_enabled() and get_search_backend() == "mistral"
                )
                if not fallback_eligible:
                    logger.error(
                        f"OpenRouter translation failed and Mistral fallback unavailable: {exc}"
                    )
                    return ""
                logger.warning(
                    f"OpenRouter translation failed, falling back to Mistral chunked path: {exc}"
                )
                # fall through to the chunked Mistral path

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
                    timeout=180,
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
