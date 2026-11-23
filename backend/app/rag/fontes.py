"""Manifesto de proveniencia compartilhado pela coleta e pela ingestao."""

import hashlib
import json
import tempfile
from pathlib import Path

MANIFESTO = "_fontes.json"


def carregar_manifesto(raiz: Path) -> dict[str, dict]:
    caminho = raiz / MANIFESTO
    if not caminho.exists():
        return {}
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, dict) or any(not isinstance(v, dict) for v in dados.values()):
        raise ValueError(f"Manifesto invalido: {caminho}")
    return dados


def gravar_atomico(caminho: Path, dados: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=caminho.parent, delete=False) as arquivo:
        temporario = Path(arquivo.name)
        try:
            arquivo.write(dados)
            arquivo.close()
            temporario.replace(caminho)
        finally:
            temporario.unlink(missing_ok=True)


def salvar_manifesto(raiz: Path, dados: dict[str, dict]) -> None:
    gravar_atomico(raiz / MANIFESTO, json.dumps(dados, ensure_ascii=False, indent=2).encode())


def hash_arquivo(caminho: Path) -> str:
    with caminho.open("rb") as arquivo:
        return hashlib.file_digest(arquivo, "sha256").hexdigest()
