"""Etapa 2 - base vetorial gratuita e persistente (ChromaDB).

A colecao guarda um chunk por registro, com metadados que alimentam tanto a
filtragem por categoria quanto a citacao de fontes exibida na interface.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.config import settings

_cliente = None
_lock = threading.RLock()
_ATIVOS = {"status_indice": {"$ne": "archived"}}
logger = logging.getLogger(__name__)


def _filtro(**campos) -> dict:
    return {"$and": [_ATIVOS, *({k: v} for k, v in campos.items())]} if campos else _ATIVOS


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
                    settings=ChromaSettings(
                        anonymized_telemetry=False,
                        chroma_product_telemetry_impl="app.rag._chroma_telemetry.SemTelemetria",
                    ),
                )
    return _cliente.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,  # Sempre usamos os vetores do Sentence-Transformers.
    )


def limpar_documento(documento: str) -> None:
    """Remove todos os chunks de um documento (usado na reindexacao)."""
    with _lock:
        get_colecao().delete(where={"documento": documento})


def resetar() -> None:
    """Zera a colecao inteira."""
    with _lock:
        colecao = get_colecao()
        _cliente.delete_collection(colecao.name)  # type: ignore[union-attr]


def contar_inalterados(documento: str, metadados: dict[str, Any]) -> int:
    with _lock:
        registros = get_colecao().get(where=_filtro(documento=documento), include=["metadatas"])
    itens = registros["metadatas"]
    if itens and all(all(m.get(k) == v for k, v in metadados.items()) for m in itens):
        return len(itens)
    return 0


def substituir_documento(
    documento: str,
    ids: list[str],
    documentos: list[str],
    embeddings: list[list[float]],
    metadados: list[dict[str, Any]],
) -> None:
    """Publica novos chunks e retira os obsoletos em um unico lote Chroma."""
    if not ids or len({len(ids), len(documentos), len(embeddings), len(metadados)}) != 1:
        raise ValueError("Lote de chunks vazio ou inconsistente")
    with _lock:
        colecao = get_colecao()
        atuais = colecao.get(where=_filtro(documento=documento), include=[])["ids"]
        novos = set(ids)
        obsoletos = [i for i in atuais if i not in novos]
        if len(ids) + len(obsoletos) > _cliente.get_max_batch_size():
            raise RuntimeError("Documento excede o limite de publicacao em um lote do Chroma")
        ativos = [dict(m, status_indice="active") for m in metadados]
        if obsoletos:
            antigos = colecao.get(ids=obsoletos, include=["documents", "embeddings", "metadatas"])
            ids = ids + antigos["ids"]
            documentos = documentos + antigos["documents"]
            embeddings = embeddings + antigos["embeddings"].tolist()
            ativos += [dict(m, status_indice="archived") for m in antigos["metadatas"]]
        # A troca logica ocorre aqui. Se o upsert falhar, nao apagamos a versao anterior.
        colecao.upsert(ids=ids, documents=documentos, embeddings=embeddings, metadatas=ativos)
        if obsoletos:
            try:
                colecao.delete(ids=obsoletos)
            except Exception:
                logger.warning("Limpeza de chunks ja inativos falhou: %s", documento, exc_info=True)


def buscar(
    embedding: list[float], top_k: int, categoria: str | None = None
) -> list[dict[str, Any]]:
    """Busca semantica. Devolve chunks ordenados por similaridade (0 a 1)."""
    with _lock:
        colecao = get_colecao()
        total = colecao.count()
        if not total:
            return []
        bruto = colecao.query(
            query_embeddings=[embedding],
            n_results=min(top_k, total),
            where=_filtro(categoria=categoria) if categoria else _ATIVOS,
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
    with _lock:
        bruto = get_colecao().get(
            where=_filtro(documento=documento), include=["documents", "metadatas"]
        )
    itens = [
        {"chunk_id": cid, "texto": txt, "metadata": meta}
        for cid, txt, meta in zip(
            bruto["ids"], bruto["documents"], bruto["metadatas"], strict=False
        )
    ]
    return sorted(itens, key=lambda i: i["metadata"].get("indice", 0))


def estatisticas() -> dict[str, int]:
    contagem = contagem_por_documento()
    return {"documentos": len(contagem), "chunks": sum(contagem.values())}


def contagem_por_documento() -> dict[str, int]:
    with _lock:
        registros = get_colecao().get(where=_ATIVOS, include=["metadatas"])["metadatas"]
    contagem: dict[str, int] = {}
    for meta in registros:
        nome = meta.get("documento", "?")
        contagem[nome] = contagem.get(nome, 0) + 1
    return contagem
