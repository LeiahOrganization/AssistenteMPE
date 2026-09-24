"""Etapa 1 + 2 - pipeline de ingestao: documento -> texto -> chunks -> indice."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from app.config import settings
from app.rag import chunking, embeddings, loaders, vectorstore


def _id_chunk(documento: str, indice: int, texto: str) -> str:
    digest = hashlib.sha1(f"{documento}:{indice}:{texto}".encode()).hexdigest()[:16]
    return f"{documento}#{indice}#{digest}"


def indexar_documento(caminho: Path, raiz: Path | None = None) -> int:
    """Indexa (ou reindexa) um unico documento. Devolve o numero de chunks."""
    raiz = raiz or settings.documents_path
    nome = caminho.relative_to(raiz).as_posix()

    paginas = loaders.carregar_documento(caminho)
    if not paginas:
        raise ValueError("nenhum texto extraido (PDF pode ser digitalizado/imagem)")

    chunks = chunking.segmentar(
        paginas, tamanho=settings.chunk_size, sobreposicao=settings.chunk_overlap
    )
    if not chunks:
        raise ValueError("nenhum chunk gerado")

    vectorstore.limpar_documento(nome)  # reindexacao idempotente

    url = loaders.url_origem(caminho, raiz)

    textos = [c.texto for c in chunks]
    vetores = embeddings.embed_passagens(textos)
    ids = [_id_chunk(nome, c.indice, c.texto) for c in chunks]
    metadados = [
        {
            "documento": nome,
            "titulo": loaders.titulo_documento(caminho, raiz),
            "categoria": loaders.inferir_categoria(caminho, raiz),
            "pagina": c.pagina if c.pagina is not None else -1,
            "indice": c.indice,
            "extensao": caminho.suffix.lower().lstrip("."),
            "url": url,
        }
        for c in chunks
    ]

    vectorstore.adicionar(ids, textos, vetores, metadados)
    return len(chunks)


def indexar_base(reset: bool = False) -> dict:
    """Indexa toda a pasta data/documentos."""
    inicio = time.perf_counter()
    raiz = settings.documents_path

    if reset:
        vectorstore.resetar()

    arquivos = loaders.listar_documentos(raiz)
    total_chunks = 0
    processados = 0
    erros: list[str] = []
    ignorados: list[str] = []

    for caminho in arquivos:
        nome = caminho.relative_to(raiz).as_posix()
        try:
            n = indexar_documento(caminho, raiz)
            total_chunks += n
            processados += 1
            print(f"  [ok] {nome} -> {n} chunks")
        except ValueError as exc:
            ignorados.append(f"{nome}: {exc}")
            print(f"  [--] {nome}: {exc}")
        except Exception as exc:  # noqa: BLE001 - queremos o relatorio completo
            erros.append(f"{nome}: {exc}")
            print(f"  [ER] {nome}: {exc}")

    return {
        "documentos_processados": processados,
        "chunks_indexados": total_chunks,
        "ignorados": ignorados,
        "erros": erros,
        "duracao_s": round(time.perf_counter() - inicio, 2),
    }
