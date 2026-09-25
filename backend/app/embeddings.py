"""Text embeddings for semantic candidate search.

Anthropic does not offer an embedding model, so TalentFlow supports:
- fastembed: a small ONNX model that runs locally, no API key (default)
- voyage:    Voyage AI's hosted embeddings (VOYAGE_API_KEY)
- hash:      dependency-free feature hashing, good enough for tests and demos
"""

import hashlib
import logging
import math
import re
from functools import lru_cache
from typing import Protocol

from .config import get_settings

log = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]: ...


def _normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class HashEmbedder:
    def __init__(self, dim: int):
        self.dim = dim

    def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]:
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in _TOKEN.findall(text.lower()):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
                v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
            out.append(_normalize(v))
        return out


class FastEmbedEmbedder:
    def __init__(self, model: str, dim: int, cache_dir: str | None = None):
        from fastembed import TextEmbedding

        self.dim = dim
        self.model = TextEmbedding(model_name=model, cache_dir=cache_dir)

    def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]:
        vectors = self.model.query_embed(texts) if kind == "query" else self.model.embed(texts)
        return [_normalize([float(x) for x in v]) for v in vectors]


class VoyageEmbedder:
    def __init__(self, model: str, dim: int, api_key: str | None):
        import voyageai

        self.dim = dim
        self.model = model
        self.client = voyageai.Client(api_key=api_key)

    def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]:
        result = self.client.embed(texts, model=self.model, input_type=kind, output_dimension=self.dim)
        return [_normalize(v) for v in result.embeddings]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    try:
        if s.embedding_provider == "fastembed":
            return FastEmbedEmbedder(s.embedding_model, s.embedding_dim, s.embedding_cache_dir)
        if s.embedding_provider == "voyage":
            return VoyageEmbedder(s.embedding_model, s.embedding_dim, s.voyage_api_key)
    except ImportError:
        log.warning("%s is not installed; falling back to hash embeddings", s.embedding_provider)
    return HashEmbedder(s.embedding_dim)


def embed_one(text: str, *, kind: str = "document") -> list[float]:
    # Keep inputs to a size every provider accepts.
    return get_embedder().embed([text[:8000]], kind=kind)[0]


def cosine(a: list[float], b: list[float]) -> float:
    # Vectors are stored normalized, so the dot product is the cosine similarity.
    return sum(x * y for x, y in zip(a, b, strict=True))
