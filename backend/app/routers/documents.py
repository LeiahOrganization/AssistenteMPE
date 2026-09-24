"""Rotas da Base de Conhecimento: listar, inspecionar, baixar, enviar e indexar."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.config import settings
from app.rag import ingest, loaders, vectorstore
from app.schemas import ChunkOut, DocumentOut, IngestReport

router = APIRouter(prefix="/api/documentos", tags=["documentos"])


def exigir_admin(x_admin_token: str = Header(default="")) -> None:
    """Protege as operacoes que alteram a base (upload, indexacao, remocao)."""
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Token de administrador invalido.")


def _resolver(nome: str) -> Path:
    """Resolve o nome relativo do documento impedindo path traversal."""
    raiz = settings.documents_path.resolve()
    caminho = (raiz / nome).resolve()
    if not caminho.is_relative_to(raiz) or not caminho.is_file():
        raise HTTPException(status_code=404, detail="Documento nao encontrado.")
    return caminho


@router.get("", response_model=list[DocumentOut])
def listar() -> list[DocumentOut]:
    raiz = settings.documents_path
    contagem = vectorstore.contagem_por_documento()
    saida: list[DocumentOut] = []

    for caminho in loaders.listar_documentos(raiz):
        nome = caminho.relative_to(raiz).as_posix()
        stat = caminho.stat()
        n_chunks = contagem.get(nome, 0)
        saida.append(
            DocumentOut(
                documento=nome,
                titulo=loaders.titulo_documento(caminho, raiz),
                categoria=loaders.inferir_categoria(caminho, raiz),
                extensao=caminho.suffix.lower().lstrip("."),
                tamanho_bytes=stat.st_size,
                modificado_em=datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                indexado=n_chunks > 0,
                n_chunks=n_chunks,
                url=loaders.url_origem(caminho, raiz),
            )
        )
    return saida


@router.get("/categorias", response_model=list[str])
def categorias() -> list[str]:
    raiz = settings.documents_path
    return sorted(
        {loaders.inferir_categoria(c, raiz) for c in loaders.listar_documentos(raiz)}
    )


@router.get("/estatisticas")
def estatisticas() -> dict:
    stats = vectorstore.estatisticas()
    arquivos = loaders.listar_documentos(settings.documents_path)
    return {
        "arquivos_na_pasta": len(arquivos),
        "documentos_indexados": stats["documentos"],
        "chunks": stats["chunks"],
        "modelo_embedding": settings.embedding_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "top_k": settings.retrieval_top_k,
    }


@router.get("/{nome:path}/chunks", response_model=list[ChunkOut])
def chunks(nome: str) -> list[ChunkOut]:
    _resolver(nome)
    itens = vectorstore.chunks_do_documento(nome)
    if not itens:
        raise HTTPException(status_code=404, detail="Documento ainda nao indexado.")
    saida = []
    for item in itens:
        pagina = item["metadata"].get("pagina", -1)
        saida.append(
            ChunkOut(
                chunk_id=item["chunk_id"],
                indice=item["metadata"].get("indice", 0),
                pagina=pagina if isinstance(pagina, int) and pagina > 0 else None,
                texto=item["texto"],
                n_caracteres=len(item["texto"]),
            )
        )
    return saida


@router.get("/{nome:path}/arquivo")
def arquivo(nome: str) -> FileResponse:
    """Serve o documento original para leitura/download na interface."""
    caminho = _resolver(nome)
    return FileResponse(caminho, filename=caminho.name)


@router.post("/upload", response_model=DocumentOut, dependencies=[Depends(exigir_admin)])
def upload(arquivo: UploadFile = File(...), categoria: str = "geral") -> DocumentOut:
    extensao = Path(arquivo.filename or "").suffix.lower()
    if extensao not in loaders.EXTENSOES_SUPORTADAS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato nao suportado. Aceitos: {sorted(loaders.EXTENSOES_SUPORTADAS)}",
        )

    pasta = settings.documents_path / categoria
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / Path(arquivo.filename or "documento").name
    destino.write_bytes(arquivo.file.read())

    n_chunks = ingest.indexar_documento(destino, settings.documents_path)
    stat = destino.stat()
    return DocumentOut(
        documento=destino.relative_to(settings.documents_path).as_posix(),
        titulo=loaders.inferir_titulo(destino),
        categoria=categoria,
        extensao=extensao.lstrip("."),
        tamanho_bytes=stat.st_size,
        modificado_em=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        indexado=True,
        n_chunks=n_chunks,
    )


@router.post("/reindexar", response_model=IngestReport, dependencies=[Depends(exigir_admin)])
def reindexar(reset: bool = False) -> IngestReport:
    """Reindexa a pasta inteira. Com reset=true, zera a base vetorial antes."""
    return IngestReport(**ingest.indexar_base(reset=reset))


@router.delete("/{nome:path}", dependencies=[Depends(exigir_admin)])
def remover(nome: str, background: BackgroundTasks) -> dict:
    caminho = _resolver(nome)
    vectorstore.limpar_documento(nome)
    background.add_task(caminho.unlink, missing_ok=True)
    return {"removido": nome}
