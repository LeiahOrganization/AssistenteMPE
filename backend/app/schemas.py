"""Contratos de entrada e saida da API."""

from typing import Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=2000)
    history: list[Message] = Field(default_factory=list, max_length=12)
    top_k: int | None = Field(default=None, ge=1, le=15)
    categoria: str | None = None      # filtra a busca por categoria de documento


class Source(BaseModel):
    """Trecho recuperado da base, exibido ao usuario como fonte da resposta."""

    chunk_id: str
    documento: str
    titulo: str
    categoria: str
    pagina: int | None = None
    trecho: str
    score: float
    url: str = ""          # link da pagina viva, quando a fonte veio do portal


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    used_context: bool
    model: str
    elapsed_ms: int


class ChunkOut(BaseModel):
    chunk_id: str
    indice: int
    pagina: int | None = None
    texto: str
    n_caracteres: int


class DocumentOut(BaseModel):
    documento: str
    titulo: str
    categoria: str
    extensao: str
    tamanho_bytes: int
    modificado_em: str
    indexado: bool
    n_chunks: int
    url: str = ""


class IngestReport(BaseModel):
    documentos_processados: int
    chunks_indexados: int
    ignorados: list[str]
    erros: list[str]
    duracao_s: float


class FeedbackRequest(BaseModel):
    question: str
    answer: str
    util: bool
    comentario: str | None = Field(default=None, max_length=1000)
    sources: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    api: str
    llm_ok: bool
    llm_detalhe: str
    llm_model: str
    embedding_model: str
    documentos: int
    chunks: int
