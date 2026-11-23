"""Documento -> texto -> chunks -> indice, com reindexacao incremental."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from app.config import settings
from app.rag import chunking, embeddings, loaders, vectorstore
from app.rag.fontes import carregar_manifesto, hash_arquivo

# Incrementar ao mudar a conversao/segmentacao de uma base ja publicada.
VERSAO_PIPELINE = 2


class DocumentoIgnorado(ValueError):
    """Fonte arquivada ou sem conteudo indexavel."""


def _id_chunk(documento: str, indice: int, texto: str) -> str:
    digest = hashlib.sha256(f"{documento}:{indice}:{texto}".encode()).hexdigest()[:16]
    return f"{documento}#{indice}#{digest}"


def _assinatura_pipeline() -> str:
    config = (
        VERSAO_PIPELINE, settings.embedding_model, settings.embedding_passage_prefix,
        settings.chunk_size, settings.chunk_overlap,
        os.getenv("OCR_LANGUAGE", "por"), os.getenv("TESSDATA_PREFIX", ""),
    )
    return hashlib.sha256(json.dumps(config).encode()).hexdigest()


def _indexar(
    caminho: Path, raiz: Path, manifesto: dict[str, dict], forcar: bool = False
) -> tuple[int, bool]:
    nome = caminho.relative_to(raiz).as_posix()
    fonte = manifesto.get(nome, {})
    if fonte.get("status") == "archived":
        raise DocumentoIgnorado("fonte arquivada")
    checksum = hash_arquivo(caminho)
    if fonte.get("hash_arquivo") and fonte["hash_arquivo"] != checksum:
        raise RuntimeError("arquivo nao confere com o hash do manifesto; recolete ou revise a fonte")
    comum = {
        "documento": nome,
        "titulo": fonte.get("titulo") or loaders.inferir_titulo(caminho),
        "categoria": loaders.inferir_categoria(caminho, raiz),
        "extensao": caminho.suffix.lower().lstrip("."),
        "url_origem": fonte.get("url_origem") or fonte.get("url") or "",
        "data_coleta": fonte.get("data_coleta") or fonte.get("coletado_em") or "",
        "hash_arquivo": checksum,
        "assinatura_pipeline": _assinatura_pipeline(),
    }
    if not forcar:
        existentes = vectorstore.contar_inalterados(nome, comum)
        if existentes:
            return existentes, False

    paginas = loaders.carregar_documento(caminho)
    if not paginas:
        raise DocumentoIgnorado("nenhum texto extraido; verifique o documento e os avisos de OCR")
    chunks = chunking.segmentar(paginas, tamanho=settings.chunk_size, sobreposicao=settings.chunk_overlap)
    if not chunks:
        raise DocumentoIgnorado("nenhum chunk gerado")

    textos = [c.texto for c in chunks]
    vetores = embeddings.embed_passagens(textos)
    if hash_arquivo(caminho) != checksum:
        raise RuntimeError("arquivo modificado durante a ingestao; tente novamente")
    ids = [_id_chunk(nome, c.indice, c.texto) for c in chunks]
    metadados = [
        dict(comum, pagina=c.pagina if c.pagina is not None else -1, indice=c.indice)
        for c in chunks
    ]
    vectorstore.substituir_documento(nome, ids, textos, vetores, metadados)
    return len(chunks), True


def indexar_documento(caminho: Path, raiz: Path | None = None) -> int:
    raiz = raiz or settings.documents_path
    return _indexar(caminho, raiz, carregar_manifesto(raiz))[0]


def indexar_base(reset: bool = False, forcar: bool = False) -> dict:
    inicio = time.perf_counter()
    raiz = settings.documents_path
    manifesto = carregar_manifesto(raiz)
    arquivos = loaders.listar_documentos(raiz, manifesto)
    if reset and not arquivos:
        raise ValueError("reset recusado: nao ha documentos ativos para indexar")
    if reset:
        vectorstore.resetar()

    total_chunks = processados = inalterados = removidos = 0
    erros: list[str] = []
    ignorados: list[str] = []

    for caminho in arquivos:
        nome = caminho.relative_to(raiz).as_posix()
        try:
            n, mudou = _indexar(caminho, raiz, manifesto, forcar)
            if mudou:
                total_chunks += n
                processados += 1
            else:
                inalterados += 1
            print(f"  [{'ok' if mudou else '=='}] {nome} -> {n} chunks")
        except DocumentoIgnorado as exc:
            ignorados.append(f"{nome}: {exc}")
            print(f"  [--] {nome}: {exc}")
        except Exception as exc:
            erros.append(f"{nome}: {exc}")
            print(f"  [ER] {nome}: {exc}")

    # Ausencia no disco por si so nao e uma decisao editorial de arquivar.
    indexados = vectorstore.contagem_por_documento()
    for nome, fonte in manifesto.items():
        if fonte.get("status") == "archived" and nome in indexados:
            try:
                vectorstore.limpar_documento(nome)
                removidos += 1
            except Exception as exc:
                erros.append(f"{nome}: falha ao retirar fonte arquivada: {exc}")

    return {
        "documentos_processados": processados,
        "documentos_inalterados": inalterados,
        "documentos_removidos": removidos,
        "chunks_indexados": total_chunks,
        "ignorados": ignorados,
        "erros": erros,
        "duracao_s": round(time.perf_counter() - inicio, 2),
    }
