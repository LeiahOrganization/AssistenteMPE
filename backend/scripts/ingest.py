#!/usr/bin/env python3
"""Indexa a base de conhecimento institucional pela linha de comando.

Uso (a partir da pasta backend/):
    python -m scripts.ingest             # indexa/atualiza os documentos
    python -m scripts.ingest --reset     # zera o indice antes de reindexar
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings          # noqa: E402
from app.rag import ingest               # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Indexacao da base do IFCE Maranguape")
    parser.add_argument("--reset", action="store_true", help="zera o indice antes")
    parser.add_argument("--forcar", action="store_true", help="recalcula mesmo com hash identico")
    args = parser.parse_args()

    print(f"Pasta de documentos: {settings.documents_path}")
    print(f"Modelo de embedding: {settings.embedding_model}")
    print(f"Chunk: {settings.chunk_size} caracteres / sobreposicao {settings.chunk_overlap}\n")

    try:
        relatorio = ingest.indexar_base(reset=args.reset, forcar=args.forcar)
    except (ValueError, OSError) as exc:
        print(f"Ingestao interrompida: {exc}", file=sys.stderr)
        return 1

    print("\n" + "-" * 50)
    print(f"Documentos processados: {relatorio['documentos_processados']}")
    print(f"Documentos inalterados: {relatorio['documentos_inalterados']}")
    print(f"Documentos arquivados.: {relatorio['documentos_removidos']}")
    print(f"Chunks indexados......: {relatorio['chunks_indexados']}")
    print(f"Duracao...............: {relatorio['duracao_s']}s")
    if relatorio["ignorados"]:
        print(f"Ignorados: {len(relatorio['ignorados'])}")
        for item in relatorio["ignorados"]:
            print(f"  - {item}")
    if relatorio["erros"]:
        print(f"Erros: {len(relatorio['erros'])}")
        for item in relatorio["erros"]:
            print(f"  - {item}")
    return int(bool(relatorio["erros"]) or not (
        relatorio["documentos_processados"] or relatorio["documentos_inalterados"]
    ))


if __name__ == "__main__":
    raise SystemExit(main())
