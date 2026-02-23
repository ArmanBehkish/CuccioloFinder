"""Breed matching via sentence embeddings of structured profiles."""

import csv
import os
from pathlib import Path

import torch
import torch.nn.functional as F
from loguru import logger

from .profile_builder import (
    akc_grooming_to_coat,
    akc_height_to_size,
    akc_temperament_to_meta,
    akc_weight_to_category,
    build_profile_text,
)

DEFAULT_EMBED_MODEL = os.environ.get("EMBED_MODEL_ID", "sentence-transformers/all-MiniLM-L6-v2")
MODELS_DIR = Path(os.environ.get("MODELS_PATH", "data/models"))
AKC_CSV = Path(os.environ.get("AKC_CSV_PATH", "data/datasets/akc-data-latest.csv"))


def load_embedding_model(
    model_id: str = DEFAULT_EMBED_MODEL,
    models_dir: Path = MODELS_DIR,
):
    """Load the sentence-transformer model (CPU, cached on disk).

    Returns (tokenizer, model) tuple.
    """
    from transformers import AutoModel, AutoTokenizer

    cache_dir = models_dir / model_id.replace("/", "--")
    cache_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir)
    model = AutoModel.from_pretrained(model_id, cache_dir=cache_dir)
    model.to(torch.device("cpu"))
    model.eval()
    return tokenizer, model



def _mean_pooling(model_output, attention_mask: torch.Tensor) -> torch.Tensor:
    """Mean pooling over non-padded tokens (standard for sentence-transformers)."""
    token_embeddings = model_output.last_hidden_state
    mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    summed = torch.sum(token_embeddings * mask_expanded, dim=1)
    counts = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
    return summed / counts


def embed_texts(
    texts: list[str],
    tokenizer,
    model,
    batch_size: int = 32,
) -> torch.Tensor:
    """Embed a list of texts and return L2-normalized vectors.

    Uses mean pooling + L2 normalization (standard for all-MiniLM-L6-v2).
    Processes in batches to stay within memory limits.
    Returns a (N, D) tensor on CPU where D=384.
    """
    all_embeddings: list[torch.Tensor] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        encoded = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=256,  # all-MiniLM-L6-v2 max sequence length
            return_tensors="pt",
        )
        with torch.no_grad():
            output = model(**encoded)
            embs = _mean_pooling(output, encoded["attention_mask"])
            embs = F.normalize(embs, p=2, dim=1)
        all_embeddings.append(embs)

    return torch.cat(all_embeddings, dim=0)



def _build_akc_profiles(csv_path: Path = AKC_CSV) -> list[tuple[str, str]]:
    """Read the AKC CSV and build a profile text for each breed.

    Returns a list of (breed_name, profile_text) tuples.
    """
    profiles: list[tuple[str, str]] = []

    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            breed = row.get("", "").strip()  # first unnamed column = breed name
            if not breed:
                continue

            temperament = akc_temperament_to_meta(row.get("temperament"))
            energy_level = row.get("energy_level_category", "").strip() or None
            trainability = row.get("trainability_category", "").strip() or None
            demeanor = row.get("demeanor_category", "").strip() or None

            try:
                size = akc_height_to_size(
                    float(row["min_height"]), float(row["max_height"])
                )
            except (KeyError, ValueError):
                size = None

            try:
                weight = akc_weight_to_category(
                    float(row["min_weight"]), float(row["max_weight"])
                )
            except (KeyError, ValueError):
                weight = None

            fur = akc_grooming_to_coat(row.get("grooming_frequency_category"))

            text = build_profile_text(
                size=size,
                fur=fur,
                weight=weight,
                energy_level=energy_level,
                trainability=trainability,
                demeanor=demeanor,
                temperament=temperament,
            )
            if text:
                profiles.append((breed, text))

    logger.info(f"Built AKC profiles for {len(profiles)} breeds")
    return profiles


def build_akc_index(
    tokenizer,
    model,
    csv_path: Path = AKC_CSV,
) -> tuple[list[str], torch.Tensor]:
    """Build the AKC breed embedding index.

    Returns (breed_names, embeddings) where embeddings is a (N, D) tensor.
    """
    profiles = _build_akc_profiles(csv_path)
    breed_names = [name for name, _ in profiles]
    texts = [text for _, text in profiles]
    embeddings = embed_texts(texts, tokenizer, model)
    logger.info(
        f"AKC index: {len(breed_names)} breeds, embedding dim={embeddings.shape[1]}"
    )
    return breed_names, embeddings


def find_closest_breeds(
    dog_embedding: torch.Tensor,
    akc_embeddings: torch.Tensor,
    breed_names: list[str],
    top_k: int = 3,
) -> list[tuple[str, float]]:
    """Find the top-k closest AKC breeds by cosine similarity.

    Args:
        dog_embedding: (D,) or (1, D) tensor for a single dog.
        akc_embeddings: (N, D) tensor for all AKC breeds.
        breed_names: list of N breed names matching akc_embeddings rows.
        top_k: number of results to return.

    Returns a list of (breed_name, similarity_score) tuples, descending.
    """
    if dog_embedding.dim() == 1:
        dog_embedding = dog_embedding.unsqueeze(0)

    # Both are already L2-normalized, so dot product = cosine similarity
    similarities = torch.mm(dog_embedding, akc_embeddings.t()).squeeze(0)
    top_scores, top_indices = torch.topk(similarities, k=min(top_k, len(breed_names)))

    return [
        (breed_names[idx.item()], score.item())
        for score, idx in zip(top_scores, top_indices)
    ]
