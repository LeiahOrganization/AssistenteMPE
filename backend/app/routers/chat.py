"""Rotas de conversa: resposta completa e resposta em streaming."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import llm
from app.config import settings
from app.rag import pipeline
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    inicio = time.perf_counter()
    resultados = pipeline.recuperar(req.question, req.top_k, req.categoria)

    if not resultados:
        return ChatResponse(
            answer=pipeline.SEM_CONTEXTO,
            sources=[],
            used_context=False,
            model=settings.llm_model,
            elapsed_ms=int((time.perf_counter() - inicio) * 1000),
        )

    mensagens = pipeline.montar_mensagens(
        req.question, resultados, [m.model_dump() for m in req.history]
    )
    try:
        resposta = llm.gerar(mensagens)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=(
                "Nao foi possivel falar com o modelo de linguagem. Verifique se o "
                f"tunel ngrok esta ativo em {settings.llm_base_url}. Detalhe: {exc}"
            ),
        ) from exc

    return ChatResponse(
        answer=resposta,
        sources=pipeline.formatar_fontes(resultados),  # type: ignore[arg-type]
        used_context=True,
        model=settings.llm_model,
        elapsed_ms=int((time.perf_counter() - inicio) * 1000),
    )


@router.post("/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """Server-Sent Events: as fontes vao primeiro, depois a resposta token a token."""
    resultados = pipeline.recuperar(req.question, req.top_k, req.categoria)

    def evento(tipo: str, dados) -> str:
        return f"data: {json.dumps({'type': tipo, 'data': dados}, ensure_ascii=False)}\n\n"

    def gerar():
        if not resultados:
            yield evento("sources", [])
            yield evento("token", pipeline.SEM_CONTEXTO)
            yield evento("done", {"used_context": False, "model": settings.llm_model})
            return

        yield evento("sources", pipeline.formatar_fontes(resultados))
        mensagens = pipeline.montar_mensagens(
            req.question, resultados, [m.model_dump() for m in req.history]
        )
        try:
            for pedaco in llm.gerar_stream(mensagens):
                yield evento("token", pedaco)
        except Exception as exc:  # noqa: BLE001
            yield evento(
                "error",
                f"Falha ao contatar o modelo em {settings.llm_base_url}. "
                f"Confira se o ngrok esta ativo. Detalhe: {exc}",
            )
            return
        yield evento("done", {"used_context": True, "model": settings.llm_model})

    return StreamingResponse(
        gerar(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
