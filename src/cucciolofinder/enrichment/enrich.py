import json
import os
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from cucciolofinder.database import Breed, Dog, FieldProvenance

from .translator import TranslationService

# Fields that get translated (with _en counterparts)
SIMPLE_FIELDS = ["gender", "size", "fur", "microchip", "sterilization", "vaccine", "deworming"]
LIST_FIELDS = ["good_with", "bad_with"]
COMPLEX_FIELDS = ["description", "age"]

# Medical fields: normalize any positive/negative value to yes/no
MEDICAL_FIELDS = {"microchip", "sterilization", "vaccine", "deworming"}
_MEDICAL_YES = {"yes", "si", "sì", "microchipped", "sterilized", "vaccinated", "dewormed",
                "dotato di microchip", "sterilizzato", "vaccinato", "sverminato"}
_MEDICAL_NO = {"no", "not sterilized", "non sterilizzato"}

def _normalize_medical(value: str) -> str:
    v = value.strip().lower()
    if v in _MEDICAL_YES:
        return "yes"
    if v in _MEDICAL_NO:
        return "no"
    return v

def enrich_translations(session: Session, limit: int | None = None) -> int:
    """
    Translate Italian fields to English for dogs with NULL _en fields.

    Args:
        session: SQLAlchemy session
        limit: Max number of dogs to process (None = all)

    Returns the number of dogs processed.
    """
    translator = TranslationService()
    processed_count = 0

    query = session.query(Dog).filter(Dog.superseded_at.is_(None))
    if limit:
        query = query.limit(limit)
    dogs = query.all()

    for dog in dogs:
        updated = False

        # Simple fields: use static mapping (with model fallback)
        for field in SIMPLE_FIELDS:
            en_field = f"{field}_en"
            italian_value = getattr(dog, field, None)
            english_value = getattr(dog, en_field, None)

            if italian_value and english_value is None:
                translated = translator.translate_field(italian_value)
                if translated:
                    value = _normalize_medical(translated) if field in MEDICAL_FIELDS else translated.lower()
                    setattr(dog, en_field, value)
                    updated = True
                    # logger.debug(f"[{dog.name}] {field} Translation: IT: ' {italian_value}' → EN: '{translated}'")

        # List fields: translate each item
        for field in LIST_FIELDS:
            en_field = f"{field}_en"
            italian_list = getattr(dog, field, None)
            english_list = getattr(dog, en_field, None)

            if italian_list and english_list is None:
                translated_list = translator.translate_list(italian_list)
                if translated_list:
                    setattr(dog, en_field, translated_list)
                    updated = True
                    # logger.debug(f"[{dog.name}] {field} Translation: IT: {italian_list} → EN: {translated_list}")

        # Complex fields: use translation model
        for field in COMPLEX_FIELDS:
            en_field = f"{field}_en"
            italian_value = getattr(dog, field, None)
            english_value = getattr(dog, en_field, None)

            if italian_value and english_value is None:
                try:
                    if field == "description":
                        # logger.debug(f"TRASNLATING DESCRIPTION: {italian_value}")
                        translated = translator.translate_description(italian_value)
                    else:
                        # age — try static map first, then model
                        translated = translator.translate_field(italian_value)

                    if translated:
                        setattr(dog, en_field, translated)
                        updated = True
                        # logger.debug(f"[{dog.name}] {field}: '{italian_value[:50]}...' → '{translated[:50]}...'")

                        # Record provenance for model-translated fields
                        _upsert_provenance(
                            session,
                            dog_id=dog.id,
                            field_name=en_field,
                            method="llm",
                            model_name=translator.model_name,
                        )
                except Exception as e:
                    logger.warning(f"[{dog.name}] Failed to translate {field}: {e}")

        if updated:
            processed_count += 1
            logger.info(f"Enriched translations for dog '{dog.name}' (id={dog.id})")

    session.commit()
    logger.info(f"Translation enrichment complete. Processed {processed_count} dogs.")
    return processed_count


def _upsert_provenance(
    session: Session,
    dog_id: int,
    field_name: str,
    method: str,
    model_name: str | None = None,
    confidence: float | None = None,
) -> None:
    """Insert or update a provenance record for a field."""
    existing = (
        session.query(FieldProvenance)
        .filter_by(dog_id=dog_id, field_name=field_name, method=method)
        .first()
    )

    if existing:
        existing.model_name = model_name
        existing.confidence = confidence
    else:
        session.add(
            FieldProvenance(
                dog_id=dog_id,
                field_name=field_name,
                method=method,
                model_name=model_name,
                confidence=confidence,
            )
        )


IMAGES_DIR = Path(os.environ.get("IMAGES_PATH", "data/images"))
VIT_TO_AKC_JSON = Path(os.environ.get("VIT_TO_AKC_PATH", "data/datasets/vit_to_akc.json"))


def enrich_breed_detection(session: Session) -> int:
    """Infer breed for each dog using image classification and text profile
    embedding similarity against the AKC breed index.

    Stores the result in dog.breed_en and records provenance.
    Returns the number of dogs processed.
    """
    from .breed_embedding import (
        build_akc_index,
        embed_texts,
        find_closest_breeds,
        load_embedding_model,
    )
    from .image_classifier import classify_breed, load_image_classifier
    from .profile_builder import (
        build_profile_text,
        classify_behavior,
        load_classifier,
        normalize_fur,
        normalize_size,
        normalize_weight,
    )

    # --- load models once ---
    logger.info("Loading image classifier...")
    processor, img_model, _ = load_image_classifier()

    logger.info("Loading zero-shot classifier...")
    zsc = load_classifier()

    logger.info("Loading embedding model...")
    tokenizer, embed_model = load_embedding_model()

    logger.info("Building AKC breed index...")
    breed_names, akc_embeddings = build_akc_index(tokenizer, embed_model)

    # --- load ViT→AKC mapping and valid breed set ---
    vit_to_akc: dict[str, str] = {}
    if VIT_TO_AKC_JSON.exists():
        with open(VIT_TO_AKC_JSON, encoding="utf-8") as fh:
            vit_to_akc = json.load(fh)
    valid_vit_labels = set(vit_to_akc.keys())
    valid_breeds = {b.name for b in session.query(Breed).all()}
    logger.info(f"Breed validation: {len(vit_to_akc)} ViT mappings, {len(valid_breeds)} valid breeds")

    # --- iterate all dogs ---
    dogs = session.query(Dog).filter(Dog.superseded_at.is_(None)).all()
    logger.info(f"Processing breed detection for {len(dogs)} dogs")

    processed = 0
    for dog in dogs:
        logger.info(f"--- [{dog.source_site}] {dog.name} (id={dog.id}) ---")

        # ---- 1. Image classification ----
        image_breeds: list[tuple[str, float]] = []
        image_paths = [
            IMAGES_DIR / img.local_path
            for img in dog.images
            if img.local_path
        ]
        if image_paths:
            image_breeds_raw = classify_breed(image_paths, processor, img_model, valid_vit_labels)
            if not image_breeds_raw:
                logger.info(f"  Image breeds: classifier returned nothing (valid_vit_labels={len(valid_vit_labels)})")
            # Resolve ViT labels to canonical AKC names
            image_breeds = []
            for label, prob in image_breeds_raw:
                canonical = vit_to_akc.get(label)
                if canonical and canonical in valid_breeds:
                    image_breeds.append((canonical, prob))
                else:
                    logger.info(f"  Image label '{label}' → canonical='{canonical}', in valid_breeds={canonical in valid_breeds if canonical else 'N/A'}")
            if image_breeds:
                fmt = ", ".join(f"{b} ({p:.2f})" for b, p in image_breeds)
                logger.info(f"  Image breeds: {fmt}")
            else:
                logger.info("  Image breeds: classification failed or no valid mapping")
        else:
            logger.info("  Image breeds: no images available")

        # ---- 2. Text profile embedding ----
        text_breeds: list[tuple[str, float]] = []

        size = normalize_size(dog.size_en) or normalize_size(dog.size)
        fur = normalize_fur(dog.fur_en) or normalize_fur(dog.fur)
        weight = normalize_weight(dog.weight)

        behavior = classify_behavior(
            dog.description_en, dog.good_with_en, dog.bad_with_en, zsc
        )

        energy = behavior["energy_level"]
        train = behavior["trainability"]
        demeanor = behavior["demeanor"]
        temperament = behavior["temperament"]

        profile = build_profile_text(
            size=size, fur=fur, weight=weight,
            energy_level=energy, trainability=train,
            demeanor=demeanor, temperament=temperament,
        )
        logger.info(f"  Profile: {profile or '(empty)'}")

        fields_present = all([size, fur, weight, energy, train, demeanor, temperament])

        if fields_present:
            dog_emb = embed_texts([profile], tokenizer, embed_model)[0]
            text_breeds = find_closest_breeds(
                dog_emb, akc_embeddings, breed_names, top_k=2
            )
            fmt = ", ".join(f"{b} ({s:.3f})" for b, s in text_breeds)
            logger.info(f"  Text breeds: {fmt}")
        else:
            missing = [
                name for name, val in [
                    ("size", size), ("fur", fur), ("weight", weight),
                    ("energy", energy), ("trainability", train),
                    ("demeanor", demeanor), ("temperament", temperament),
                ]
                if not val
            ]
            logger.info(
                f"  Text breeds: not enough info to infer breed "
                f"(missing: {', '.join(missing)})"
            )

        # ---- 3. Combine results (dynamic α) ----
        # α = weight given to image signal, (1-α) = weight for text signal.
        # Dynamic α based on image top-1 confidence:
        #   > 0.7  → α = 0.8   (image is confident, trust it heavily)
        #   0.4–0.7 → α = 0.5  (moderate confidence, balanced)
        #   < 0.4  → α = 0.3   (image unsure, lean on text)
        # Fallbacks when only one signal is available:
        #   no image  → α = 0.0  (text only)
        #   no text   → α = 1.0  (image only)
        has_image = bool(image_breeds)
        has_text = bool(text_breeds)

        if not has_image and not has_text:
            logger.info("  Verdict: not enough information to infer breed")
            processed += 1
            continue

        if has_image and has_text:
            top1_prob = image_breeds[0][1]
            if top1_prob > 0.7:       # high image confidence
                alpha = 0.8
            elif top1_prob >= 0.4:    # moderate image confidence
                alpha = 0.5
            else:                     # low image confidence
                alpha = 0.3
            method = "image+text"
        elif has_image:
            alpha = 1.0               # image only
            method = "image"
        else:
            alpha = 0.0               # text only
            method = "text"

        # Merge all candidates into a single pool.
        # Both sources now use canonical AKC names, so keys match directly.
        candidates: dict[str, dict] = {}

        for breed, prob in image_breeds:
            candidates.setdefault(breed, {"image": 0.0, "text": 0.0, "name": breed})
            candidates[breed]["image"] = max(candidates[breed]["image"], prob)

        for breed, sim in text_breeds:
            candidates.setdefault(breed, {"image": 0.0, "text": 0.0, "name": breed})
            candidates[breed]["text"] = max(candidates[breed]["text"], sim)

        for info in candidates.values():
            info["combined"] = alpha * info["image"] + (1 - alpha) * info["text"]

        ranked = sorted(
            candidates.values(), key=lambda x: x["combined"], reverse=True
        )
        top = ranked[0]

        # ---- 4. Store result + breakdown in database ----
        dog.breed_en = top["name"]

        # Store individual signal provenance for detail page breakdown
        if has_image:
            _upsert_provenance(
                session, dog_id=dog.id, field_name="breed_en",
                method="image", model_name=image_breeds[0][0],
                confidence=image_breeds[0][1],
            )
            if len(image_breeds) > 1:
                _upsert_provenance(
                    session, dog_id=dog.id, field_name="breed_en",
                    method="image_2nd", model_name=image_breeds[1][0],
                    confidence=image_breeds[1][1],
                )
        if has_text:
            _upsert_provenance(
                session, dog_id=dog.id, field_name="breed_en",
                method="text", model_name=text_breeds[0][0],
                confidence=text_breeds[0][1],
            )
        _upsert_provenance(
            session, dog_id=dog.id, field_name="breed_en",
            method="combined", model_name=f"α={alpha}",
            confidence=top["combined"],
        )

        logger.info(
            f"  Verdict: {top['name']} "
            f"(combined={top['combined']:.3f}, α={alpha}, "
            f"img={top['image']:.2f}, txt={top['text']:.3f}, method={method})"
        )
        if len(ranked) > 1:
            r2 = ranked[1]
            logger.info(
                f"  Runner-up: {r2['name']} "
                f"(combined={r2['combined']:.3f}, "
                f"img={r2['image']:.2f}, txt={r2['text']:.3f})"
            )

        processed += 1

    session.commit()
    logger.info(f"Breed detection complete. Processed {processed} dogs.")
    return processed
