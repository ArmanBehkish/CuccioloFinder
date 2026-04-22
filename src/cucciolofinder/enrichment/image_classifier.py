"""Image-based dog breed classification using a ViT model."""

import os
from pathlib import Path

from loguru import logger

DEFAULT_IMAGE_MODEL = os.environ.get(
    "IMAGE_MODEL_ID",
    "wesleyacheng/dog-breeds-multiclass-image-classification-with-vit",
)
MODELS_DIR = Path(os.environ.get("MODELS_PATH", "data/models"))
IMAGES_DIR = Path(os.environ.get("IMAGES_PATH", "data/images"))


def load_image_classifier(
    model_id: str = DEFAULT_IMAGE_MODEL,
    models_dir: Path = MODELS_DIR,
):
    """Load the ViT breed classification model (CPU, cached on disk).

    Returns (processor, model, id2label) tuple.
    """
    import torch
    from transformers import AutoImageProcessor, AutoModelForImageClassification

    cache_dir = models_dir / model_id.replace("/", "--")
    cache_dir.mkdir(parents=True, exist_ok=True)

    processor = AutoImageProcessor.from_pretrained(model_id, cache_dir=cache_dir)
    model = AutoModelForImageClassification.from_pretrained(
        model_id, cache_dir=cache_dir
    )
    model.to(torch.device("cpu"))
    model.eval()
    id2label = model.config.id2label
    return processor, model, id2label


def _classify_single_image(
    image_path: Path,
    processor,
    model,
) -> list[tuple[str, float]]:
    """Classify one image, return top-3 (label, probability) pairs."""
    import torch
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    inputs = processor(images=img, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)

    top_probs, top_indices = torch.topk(probs[0], k=3)
    id2label = model.config.id2label
    return [
        (id2label.get(idx.item(), str(idx.item())), score.item())
        for score, idx in zip(top_probs, top_indices)
    ]


def classify_breed(
    image_paths: list[Path],
    processor,
    model,
    valid_labels: set[str] | None = None,
) -> list[tuple[str, float]]:
    """Classify breed from multiple images of the same dog.

    For each image, the top-3 predictions are collected.  Then across all
    images the breeds with the highest single-image probability are ranked.

    When *valid_labels* is provided, only labels in that set are kept.
    Skipped labels are replaced by the next-highest valid one, so the
    returned list always has up to 2 entries (unless fewer valid labels exist).

    Returns a list of up to 2 (breed_label, probability) tuples sorted by
    descending probability.  Returns an empty list when no images can be
    classified.
    """
    # breed → max probability seen across any image
    best: dict[str, float] = {}

    for path in image_paths:
        try:
            top3 = _classify_single_image(path, processor, model)
        except Exception as exc:
            logger.warning(f"Image classification failed for {path}: {exc}")
            continue
        for label, prob in top3:
            if label not in best or prob > best[label]:
                best[label] = prob

    if not best:
        return []

    ranked = sorted(best.items(), key=lambda x: x[1], reverse=True)

    if valid_labels is None:
        return ranked[:2]

    result = []
    for label, prob in ranked:
        if label in valid_labels:
            result.append((label, prob))
            if len(result) == 2:
                break
    return result
