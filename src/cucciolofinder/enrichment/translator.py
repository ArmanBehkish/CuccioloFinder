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
    "Vaccinato": "vaccinated",
    # sterilization
    "Sterilizzato": "sterilized",
    "Non sterilizzato": "not sterilized",
    # deworming
    "Sverminato": "dewormed",
    # microchip
    "Dotato di microchip": "microchipped",
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
    "Cani femmina": "female dogs",
    "cani femmina": "female dogs",
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

    def translate_description(self, text: str) -> str:
        """Translate long description text, splitting by sentence.
        """
        if not text or not text.strip():
            return ""

        sentences = [s.strip() for s in text.replace("\n", ". ").split(".") if s.strip()]

        translated_sentences = []
        for sentence in sentences:
            try:
                translated = self.translate(sentence)

                # Check if translation is just the original echoed back (API failure mode)
                if translated.strip().lower() == sentence.strip().lower():
                    logger.warning(f"Translation returned original text, aborting: '{sentence[:50]}...'")
                    return ""  # Return empty so field stays NULL

                translated_sentences.append(translated)
            except Exception as e:
                logger.warning(f"Failed to translate sentence: {e}")
                return ""

        return ". ".join(translated_sentences)
