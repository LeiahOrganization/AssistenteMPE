#!/usr/bin/env python3
"""Coleta paginas do portal do campus para a base de conhecimento.

Uso (a partir da pasta backend/):
    python -m scripts.crawl https://ifce.edu.br/maranguape
    python -m scripts.crawl https://ifce.edu.br/maranguape/noticias \
        --categoria noticias --max-paginas 40 --profundidade 2

Depois de coletar, rode a indexacao:
    python -m scripts.ingest
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings        # noqa: E402
from app.rag import crawler            # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Coletor de paginas do portal do campus")
    parser.add_argument("url", help="URL semente (ex.: https://ifce.edu.br/maranguape)")
    parser.add_argument("--categoria", default="portal", help="subpasta/categoria de destino")
    parser.add_argument("--max-paginas", type=int, default=30)
    parser.add_argument("--profundidade", type=int, default=2)
    parser.add_argument("--intervalo", type=float, default=1.0,
                        help="segundos de espera entre requisicoes")
    args = parser.parse_args()

    print(f"Semente......: {args.url}")
    print(f"Destino......: {settings.documents_path / args.categoria}")
    print(f"Limites......: {args.max_paginas} paginas, profundidade {args.profundidade}")
    print(f"Intervalo....: {args.intervalo}s entre requisicoes\n")

    r = crawler.coletar(
        semente=args.url,
        destino=settings.documents_path,
        categoria=args.categoria,
        max_paginas=args.max_paginas,
        profundidade=args.profundidade,
        intervalo=args.intervalo,
    )

    print("\n" + "-" * 50)
    print(f"Paginas salvas: {len(r.salvas)}")
    print(f"Ignoradas.....: {len(r.ignoradas)}")
    print(f"Erros.........: {len(r.erros)}")
    print(f"Duracao.......: {r.duracao_s}s")
    for item in r.erros[:10]:
        print(f"  [ER] {item}")
    print("\nAgora rode:  python -m scripts.ingest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
