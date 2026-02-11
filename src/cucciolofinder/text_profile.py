import argparse
import os
from pathlib import Path

import torch
import torch.nn.functional as F

from cucciolofinder.database import Dog, get_engine, get_session


def _clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return ", ".join(parts)
    return str(value).strip()


def build_dog_profile_text(dog) -> str:
    fields = [
        ("description_en", "description"),
        ("size_en", "size"),
        ("fur_en", "fur"),
        ("good_with_en", "good_with"),
        ("bad_with_en", "bad_with"),
        ("age_en", "age"),
        ("gender_en", "gender")
        ]
    lines = []
    for field, label in fields:
        value = _clean_text(getattr(dog, field, None))
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _mean_pooling(model_output, attention_mask: torch.Tensor) -> torch.Tensor:
    token_embeddings = model_output.last_hidden_state
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    summed = torch.sum(token_embeddings * input_mask_expanded, dim=1)
    counts = torch.clamp(input_mask_expanded.sum(dim=1), min=1e-9)
    return summed / counts


def embed_texts(texts: list[str], model_id: str, cache_dir: Path) -> torch.Tensor:
    from transformers import AutoModel, AutoTokenizer

    cache_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir)
    model = AutoModel.from_pretrained(model_id, cache_dir=cache_dir)
    model.eval()

    device = torch.device("cpu")
    model.to(device)

    prefixed = [f"passage: {text}" for text in texts]
    encoded = tokenizer(
        prefixed,
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    encoded = {k: v.to(device) for k, v in encoded.items()}

    with torch.no_grad():
        output = model(**encoded)
        embeddings = _mean_pooling(output, encoded["attention_mask"])
        embeddings = F.normalize(embeddings, p=2, dim=1)

    return embeddings.cpu()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print text profiles for sample dogs using English fields."
    )
    parser.add_argument("--limit", type=int, default=3, help="Number of dogs to show")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("DB_PATH", "data/db/cucciolofinder.db"),
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--embed",
        action="store_true",
        help="Compute and print BGE embeddings for each dog profile",
    )
    parser.add_argument(
        "--model-id",
        default="BAAI/bge-large-en-v1.5",
        help="Embedding model id",
    )
    parser.add_argument(
        "--model-cache",
        default=os.environ.get("EMBEDDING_MODEL_CACHE", "data/models/bge-large-en-v1.5"),
        help="Cache directory for downloaded embedding model",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    engine = get_engine(db_path)
    Session = get_session(engine)

    with Session() as session:
        dogs = session.query(Dog).order_by(Dog.id).limit(args.limit).all()

    if not dogs:
        print("No dogs found.")
        return 1

    for dog in dogs:
        profile = build_dog_profile_text(dog)
        print(f"Dog id={dog.id} name={dog.name}")
        if profile:
            for line in profile.splitlines():
                print(f"  {line}")
        else:
            print("  [no english profile fields]")
        print()

    if args.embed:
        texts = [build_dog_profile_text(dog) for dog in dogs]
        valid = [(dog, text) for dog, text in zip(dogs, texts) if text]
        if not valid:
            print("No dogs with English profile text to embed.")
            return 1

        dogs_valid, texts_valid = zip(*valid)
        embeddings = embed_texts(
            list(texts_valid),
            args.model_id,
            Path(args.model_cache),
        )

        for dog, emb in zip(dogs_valid, embeddings, strict=True):
            vector = emb.tolist()
            print(f"Embedding for dog id={dog.id} name={dog.name} dim={len(vector)}")
            print(vector)
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
