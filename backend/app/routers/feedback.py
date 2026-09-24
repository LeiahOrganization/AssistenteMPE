"""Etapa 5 - campo de feedback para melhoria continua.

Os registros vao para um JSONL, que tambem alimenta a avaliacao qualitativa
prevista na Etapa 4 (comparacao com as respostas humanas da secretaria).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import settings
from app.schemas import FeedbackRequest

router = APIRouter(prefix="/api", tags=["feedback"])

ARQUIVO = "feedback.jsonl"


@router.post("/feedback")
def registrar(req: FeedbackRequest) -> dict:
    registro = req.model_dump()
    registro["registrado_em"] = datetime.now(tz=timezone.utc).isoformat()
    registro["modelo"] = settings.llm_model

    destino = settings.logs_path / ARQUIVO
    with destino.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")

    return {"ok": True}


@router.get("/feedback/resumo")
def resumo() -> dict:
    destino = settings.logs_path / ARQUIVO
    if not destino.exists():
        return {"total": 0, "uteis": 0, "nao_uteis": 0}

    total = uteis = 0
    with destino.open(encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            total += 1
            if json.loads(linha).get("util"):
                uteis += 1
    return {"total": total, "uteis": uteis, "nao_uteis": total - uteis}
