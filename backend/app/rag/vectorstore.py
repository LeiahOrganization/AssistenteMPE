"""Etapa 2 - base vetorial gratuita e persistente (ChromaDB).

A colecao guarda um chunk por registro, com metadados que alimentam tanto a
filtragem por categoria quanto a citacao de fontes exibida na interface.
"""

from __future__ import annotations

import os
import threading
from typing import Any

# desliga a telemetria do Chroma antes do import da biblioteca (evita ruido no log)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_IMPL", "chromadb.telemetry.posthog.NoopTelemetry")

from app.config import settings

_cliente = None
_lock = threading.Lock()


def get_colecao():
    """Devolve (criando se preciso) a colecao persistente do campus."""
    global _cliente
    if _cliente is None:
        with _lock:
            if _cliente is None:
                import chromadb
                from chromadb.config import Settings as ChromaSettings

                _cliente = chromadb.PersistentClient(
                    path=str(settings.chroma_path),
                    settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
                )
    return _cliente.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def limpar_documento(documento: str) -> None:
    """Remove todos os chunks de um documento (usado na reindexacao)."""
    get_colecao().delete(where={"documento": documento})


def resetar() -> None:
    """Zera a colecao inteira."""
    colecao = get_colecao()
    _cliente.delete_collection(colecao.name)  # type: ignore[union-attr]


def adicionar(
    ids: list[str],
    documentos: list[str],
    embeddings: list[list[float]],
    metadados: list[dict[str, Any]],
) -> None:
    colecao = get_colecao()
    # o Chroma tem limite pratico de lote; 200 e folgado para chunks de ~900 chars
    for i in range(0, len(ids), 200):
        fatia = slice(i, i + 200)
        colecao.add(
            ids=ids[fatia],
            documents=documentos[fatia],
            embeddings=embeddings[fatia],
            metadatas=metadados[fatia],
        )


def buscar(
    embedding: list[float], top_k: int, categoria: str | None = None
) -> list[dict[str, Any]]:
    """Busca semantica. Devolve chunks ordenados por similaridade (0 a 1)."""
    colecao = get_colecao()
    if colecao.count() == 0:
        return []

    filtro = {"categoria": categoria} if categoria else None
    bruto = colecao.query(
        query_embeddings=[embedding],
        n_results=min(top_k, colecao.count()),
        where=filtro,
        include=["documents", "metadatas", "distances"],
    )

    resultados: list[dict[str, Any]] = []
    for chunk_id, texto, meta, distancia in zip(
        bruto["ids"][0],
        bruto["documents"][0],
        bruto["metadatas"][0],
        bruto["distances"][0],
        strict=False,
    ):
        resultados.append(
            {
                "chunk_id": chunk_id,
                "texto": texto,
                "metadata": meta,
                # distancia cosseno (0 = identico) -> score de similaridade
                "score": round(max(0.0, 1.0 - float(distancia)), 4),
            }
        )
    return resultados


def chunks_do_documento(documento: str) -> list[dict[str, Any]]:
    """Todos os chunks de um documento, na ordem original (aba Documentos)."""
    bruto = get_colecao().get(
        where={"documento": documento}, include=["documents", "metadatas"]
    )
    itens = [
        {"chunk_id": cid, "texto": txt, "metadata": meta}
        for cid, txt, meta in zip(
            bruto["ids"], bruto["documents"], bruto["metadatas"], strict=False
        )
    ]
    return sorted(itens, key=lambda i: i["metadata"].get("indice", 0))


def estatisticas() -> dict[str, int]:
    colecao = get_colecao()
    total = colecao.count()
    if total == 0:
        return {"documentos": 0, "chunks": 0}
    metadados = colecao.get(include=["metadatas"])["metadatas"]
    return {
        "documentos": len({m.get("documento") for m in metadados}),
        "chunks": total,
    }


def contagem_por_documento() -> dict[str, int]:
    colecao = get_colecao()
    if colecao.count() == 0:
        return {}
    contagem: dict[str, int] = {}
    for meta in colecao.get(include=["metadatas"])["metadatas"]:
        nome = meta.get("documento", "?")
        contagem[nome] = contagem.get(nome, 0) + 1
    return contagem
