"""Assistente Inteligente do IFCE Campus Maranguape - aplicacao FastAPI.

PIBIC AF Jr 2026 - Edital 14/2026 PRPI/REITORIA-IFCE
Coordenacao: Jessyca Almeida Bessa (IFCE Campus Maranguape)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import llm
from app.config import settings
from app.rag import vectorstore
from app.routers import chat, documents, feedback
from app.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 62)
    print(" Assistente Inteligente do IFCE Campus Maranguape")
    print(f" LLM.......: {settings.llm_model} @ {settings.llm_base_url}")
    print(f" Embeddings: {settings.embedding_model}")
    print(f" Documentos: {settings.documents_path}")
    print(f" Indice....: {settings.chroma_path}")
    print("=" * 62)
    yield


app = FastAPI(
    title="Assistente Inteligente do IFCE Campus Maranguape",
    description=(
        "Chatbot academico com LLM gratuito e Geracao Aumentada por Recuperacao "
        "(RAG) sobre os documentos publicos do campus."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(documents.router)
app.include_router(feedback.router)


@app.get("/api/health", response_model=HealthResponse, tags=["sistema"])
def health() -> HealthResponse:
    llm_ok, detalhe = llm.verificar()
    stats = vectorstore.estatisticas()
    return HealthResponse(
        api="ok",
        llm_ok=llm_ok,
        llm_detalhe=detalhe,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        documentos=stats["documentos"],
        chunks=stats["chunks"],
    )


# --- interface web servida pelo proprio backend ---
if settings.frontend_path.is_dir():
    app.mount(
        "/static",
        StaticFiles(directory=settings.frontend_path),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(settings.frontend_path / "index.html")
