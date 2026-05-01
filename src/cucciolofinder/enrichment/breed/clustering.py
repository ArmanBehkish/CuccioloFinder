"""Clustering-based breed inference (stub).

Idea: cluster the dog dataset in feature space (image embeddings or
profile embeddings), label each cluster with its most common AKC match
from other pipelines, then assign each dog its cluster's label as a
weak signal. Useful for novel/mixed breeds where individual signals
disagree.

Not implemented yet — `run` is a no-op.
"""

from loguru import logger
from sqlalchemy.orm import Session


def run(session: Session) -> int:
    logger.info("Clustering breed pipeline: not implemented, skipping")
    return 0
