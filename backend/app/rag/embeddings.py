"""Etapa 2 - modelo de embedding gratuito (Sentence-Transformers).

O modelo e carregado sob demanda (lazy) e mantido em memoria: carregar
multilingual-e5-small custa alguns segundos e ~120 MB.
"""

from __future__ import annotations

import threading

from app.config import settings

_modelo = None
_lock = threading.Lock()


def get_modelo():
    global _modelo
    if _modelo is None:
        with _lock:
            if _modelo is None:
                from sentence_transformers import SentenceTransformer

                _modelo = SentenceTransformer(settings.embedding_model)
    return _modelo


def embed_passagens(textos: list[str]) -> list[list[float]]:
    """Vetoriza trechos da base de conhecimento."""
    prefixo = settings.embedding_passage_prefix
    entradas = [f"{prefixo} {t}" if prefixo else t for t in textos]
    vetores = get_modelo().encode(
        entradas, normalize_embeddings=True, batch_size=32, show_progress_bar=False
    )
    return [v.tolist() for v in vetores]


def embed_pergunta(texto: str) -> list[float]:
    """Vetoriza a pergunta do usuario."""
    prefixo = settings.embedding_query_prefix
    entrada = f"{prefixo} {texto}" if prefixo else texto
    vetor = get_modelo().encode([entrada], normalize_embeddings=True)[0]
    return vetor.tolist()
