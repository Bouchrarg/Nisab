from __future__ import annotations

from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-base"


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME, device="cpu")


def embed_passages(texts: list[str]) -> np.ndarray:
    model = get_model()
    prefixed = [f"passage: {t}" for t in texts]
    return model.encode(prefixed, normalize_embeddings=True, show_progress_bar=len(texts) > 20)


def embed_query(text: str) -> np.ndarray:
    model = get_model()
    return model.encode([f"query: {text}"], normalize_embeddings=True)[0]