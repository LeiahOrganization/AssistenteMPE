#!/usr/bin/env python3
"""Avalia o recuperador configurado sem chamar o LLM."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.rag import pipeline  # noqa: E402

BASE = Path(__file__).resolve().parents[1] / "data" / "eval"


def ler_perguntas(caminho: Path) -> list[dict]:
    perguntas = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(perguntas, list) or not perguntas:
        raise ValueError("O JSON deve conter uma lista nao vazia de perguntas")
    for i, item in enumerate(perguntas, 1):
        if not isinstance(item, dict):
            raise ValueError(f"Item {i}: esperado um objeto")
        pergunta = item.get("pergunta")
        tem_resposta = item.get("tem_resposta")
        if not isinstance(pergunta, str) or not pergunta.strip() or type(tem_resposta) is not bool:
            raise ValueError(f"Item {i}: informe pergunta e tem_resposta (booleano)")
        for campo in ("documento_esperado", "categoria_esperada"):
            valor = item.get(campo)
            if campo not in item or (tem_resposta and (not isinstance(valor, str) or not valor.strip())):
                raise ValueError(f"Item {i}: informe {campo} (obrigatorio para perguntas com resposta)")
            if not tem_resposta and valor is not None and not isinstance(valor, str):
                raise ValueError(f"Item {i}: {campo} deve ser texto ou null")
    return perguntas


def avaliar(perguntas: list[dict]) -> dict:
    total_positivas = total_negativas = hit1 = hit5 = abstencoes = 0
    reciprocais = 0.0
    detalhes = []
    for item in perguntas:
        # Nao passe a categoria esperada como filtro: ela e o rotulo, nao uma entrada.
        encontrados = pipeline.recuperar(item["pergunta"], top_k=5)[:5]
        rank = None
        if item["tem_resposta"]:
            total_positivas += 1
            rank = next((i for i, r in enumerate(encontrados, 1)
                         if (r["metadata"].get("documento") == item["documento_esperado"]
                             and r["metadata"].get("categoria") == item["categoria_esperada"])), None)
            if rank is not None:
                hit1 += rank == 1
                hit5 += 1
                reciprocais += 1 / rank
        else:
            total_negativas += 1
            abstencoes += not encontrados
        detalhes.append({
            **item,
            "rank_esperado": rank,
            "absteve": not encontrados,
            "resultados": [
                {"chunk_id": r["chunk_id"], "score": r["score"],
                 "documento": r["metadata"].get("documento"),
                 "categoria": r["metadata"].get("categoria"),
                 "pagina": r["metadata"].get("pagina")}
                for r in encontrados
            ],
        })
    return {
        "perguntas_com_resposta": total_positivas,
        "perguntas_sem_resposta": total_negativas,
        "metricas": {
            "hit@1": hit1 / total_positivas if total_positivas else None,
            "hit@5": hit5 / total_positivas if total_positivas else None,
            "mrr@5": reciprocais / total_positivas if total_positivas else None,
            "taxa_abstencao_correta": abstencoes / total_negativas if total_negativas else None,
        },
        "perguntas": detalhes,
    }


def salvar_relatorio(relatorio: dict, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    bruto = json.dumps(relatorio, ensure_ascii=False, indent=2)
    if caminho.suffix.lower() == ".md":
        rotulos = {
            "hit@1": "Hit@1", "hit@5": "Hit@5", "mrr@5": "MRR@5",
            "taxa_abstencao_correta": "Taxa de Abstenção Correta",
        }
        linhas = ["# Avaliação da recuperação", "", "| Métrica | Valor |", "|---|---|"]
        for chave, valor in relatorio["metricas"].items():
            resultado = f"{valor:.2%}" if valor is not None else "N/A"
            linhas.append(f"| {rotulos[chave]} | {resultado} |")
        linhas += ["", "## Configuração e resultados por pergunta", "", "`````json", bruto, "`````"]
        bruto = "\n".join(linhas)
    caminho.write_text(bruto + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--perguntas", type=Path, default=BASE / "perguntas_teste.json")
    parser.add_argument("--saida", type=Path, default=BASE / "relatorio_retrieval.json")
    args = parser.parse_args(argv)
    if args.saida.suffix.lower() not in {".json", ".md"}:
        parser.error("--saida deve terminar em .json ou .md")
    if args.saida.resolve() == args.perguntas.resolve():
        parser.error("o relatorio nao pode sobrescrever o conjunto de perguntas")
    try:
        perguntas = ler_perguntas(args.perguntas)
        relatorio = avaliar(perguntas)
        relatorio.update(
            avaliado_em=datetime.now(timezone.utc).isoformat(), conjunto=str(args.perguntas),
            configuracao={
                "embedding_model": settings.embedding_model, "colecao": settings.collection_name,
                "top_k": 5, "retrieval_min_score": settings.retrieval_min_score,
                "chunk_size": settings.chunk_size, "chunk_overlap": settings.chunk_overlap,
            },
        )
        salvar_relatorio(relatorio, args.saida)
    except (ValueError, OSError) as exc:
        print(f"Falha na avaliacao: {exc}", file=sys.stderr)
        return 1
    print(f"Relatorio: {args.saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
