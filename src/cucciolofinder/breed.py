from __future__ import annotations

import argparse
import os
from pathlib import Path

import torch

from cucciolofinder.database import Dog, DogImage, get_engine, get_session


DEFAULT_MODEL_ID = "wesleyacheng/dog-breeds-multiclass-image-classification-with-vit"


def load_model(model_id: str, device: "torch.device"):
    from transformers import AutoImageProcessor, AutoModelForImageClassification

    processor = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModelForImageClassification.from_pretrained(model_id)
    model.to(device)
    model.eval()
    return processor, model


def classify_image(
    image_path: Path,
    processor,
    model,
    device: "torch.device",
) -> "torch.Tensor":
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)
    return probs[0].cpu()


def pick_dogs_with_images(session, images_dir: Path, limit: int):
    rows = (
        session.query(Dog, DogImage)
        .join(DogImage, DogImage.dog_id == Dog.id)
        .filter(DogImage.local_path.isnot(None))
        .order_by(Dog.id, DogImage.position)
        .all()
    )

    selected = []
    current = {}
    for dog, image in rows:
        if dog.id in current:
            image_paths = current[dog.id][1]
        else:
            if len(selected) >= limit:
                break
            image_paths = []
            current[dog.id] = (dog, image_paths)
            selected.append(current[dog.id])

        path = images_dir / image.local_path
        if path.exists():
            image_paths.append(path)

    return [(dog, paths) for dog, paths in selected if paths]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify dog breeds for sample images in the database."
    )
    parser.add_argument("--limit", type=int, default=3, help="Number of dogs to classify")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("DB_PATH", "data/db/cucciolofinder.db"),
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--images-path",
        default=os.environ.get("IMAGES_PATH", "data/images"),
        help="Root directory for downloaded images",
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
        help="Hugging Face model id",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    images_dir = Path(args.images_path)
    engine = get_engine(db_path)
    Session = get_session(engine)

    device = torch.device("cpu")
    processor, model = load_model(args.model_id, device)
    id2label = model.config.id2label

    with Session() as session:
        selected = pick_dogs_with_images(session, images_dir, args.limit)

    if not selected:
        print("No dogs with local images found.")
        return 1

    for dog, image_paths in selected:
        print(f"Dog id={dog.id} name={dog.name} images_found={len(image_paths)}")
        for path in image_paths:
            print(f"  {path}")
            try:
                probs = classify_image(path, processor, model, device)
            except Exception as exc:
                print(f"    [warn] classify failed: {exc}")
                continue
            top_probs, top_indices = torch.topk(probs, k=3)
            for rank, (score, idx) in enumerate(zip(top_probs, top_indices), start=1):
                label = id2label.get(idx.item(), str(idx.item()))
                print(f"    {rank}. {label} ({score.item():.4f})")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
