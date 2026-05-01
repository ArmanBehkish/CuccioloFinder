"""Categorical-similarity + IG-weighted breed inference (stub).

Planned approach (see conversation in
`/Users/arman/.claude/plans/shimmying-jingling-dijkstra.md`):

  - Compare the dog's categorical fields (size, fur, weight bin, age bin,
    temperament set, etc.) to each AKC breed's reference profile using
    per-dimension similarity functions:
      - Ordinal dimensions: `1 - dist / (N - 1)`.
      - Nominal dimensions: exact match (1.0 / 0.0).
      - Set-valued (temperament tags): IDF-weighted Jaccard.
  - Weight each dimension by its information gain over AKC reference,
    `IG(Y; Xᵢ) = H(Y) - H(Y | Xᵢ)`, computed once at startup.
  - Coverage-aware confidence: average over dimensions present, scaled
    by the fraction of available dimensions.
  - Write `method='categorical'` row to inferred_dog_breeds.

Not implemented yet — `run` is a no-op so the dispatcher can list this
pipeline in `BREED_DETECTION_PIPELINES` once it's ready.
"""

from loguru import logger
from sqlalchemy.orm import Session


def run(session: Session) -> int:
    logger.info("Categorical breed pipeline: not implemented, skipping")
    return 0
