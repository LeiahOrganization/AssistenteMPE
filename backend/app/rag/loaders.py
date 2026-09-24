"""Etapa 1 - leitura dos documentos institucionais em formatos diversos.

Cada loader devolve uma lista de paginas: [(numero_da_pagina, texto)].
Formatos sem paginacao (DOCX, HTML, TXT, MD) devolvem uma unica "pagina" None.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

Pagina = tuple[int | None, str]

EXTENSOES_SUPORTADAS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}


def limpar_texto(texto: str) -> str:
    """Normaliza o texto bruto extraido dos documentos."""
    texto = unicodedata.normalize("NFKC", texto)
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)  # comentarios HTML
    texto = texto.replace("­", "")            # hifen de quebra invisivel
    texto = re.sub(r"-\n(?=[a-zà-ú])", "", texto)  # junta palavra quebrada na linha
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _ler_pdf(caminho: Path) -> list[Pagina]:
    import fitz  # pymupdf

    paginas: list[Pagina] = []
    with fitz.open(caminho) as doc:
        for numero, pagina in enumerate(doc, start=1):
            texto = limpar_texto(pagina.get_text("text"))
            if texto:
                paginas.append((numero, texto))
    return paginas


def _ler_docx(caminho: Path) -> list[Pagina]:
    from docx import Document

    doc = Document(str(caminho))
    partes = [p.text for p in doc.paragraphs if p.text.strip()]
    for tabela in doc.tables:
        for linha in tabela.rows:
            celulas = [c.text.strip() for c in linha.cells if c.text.strip()]
            if celulas:
                partes.append(" | ".join(celulas))
    texto = limpar_texto("\n".join(partes))
    return [(None, texto)] if texto else []


def _ler_html(caminho: Path) -> list[Pagina]:
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(caminho.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in sopa(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    texto = limpar_texto(sopa.get_text("\n"))
    return [(None, texto)] if texto else []


def _ler_texto(caminho: Path) -> list[Pagina]:
    texto = limpar_texto(caminho.read_text(encoding="utf-8", errors="ignore"))
    return [(None, texto)] if texto else []


_LOADERS = {
    ".pdf": _ler_pdf,
    ".docx": _ler_docx,
    ".html": _ler_html,
    ".htm": _ler_html,
    ".txt": _ler_texto,
    ".md": _ler_texto,
}


def carregar_documento(caminho: Path) -> list[Pagina]:
    """Le um documento e devolve suas paginas de texto limpo."""
    extensao = caminho.suffix.lower()
    loader = _LOADERS.get(extensao)
    if loader is None:
        raise ValueError(f"Formato nao suportado: {extensao}")
    return loader(caminho)


def listar_documentos(pasta: Path) -> list[Path]:
    """Lista recursivamente os documentos suportados da base de conhecimento."""
    return sorted(
        caminho
        for caminho in pasta.rglob("*")
        if caminho.is_file()
        and caminho.suffix.lower() in EXTENSOES_SUPORTADAS
        and not caminho.name.startswith((".", "~$", "_"))
    )


def origem_web(caminho: Path, raiz: Path) -> dict:
    """Dados da pagina web de onde o arquivo veio, se foi coletado do portal.

    Devolve {} para documentos locais (PDF, DOCX etc.).
    """
    from app.rag.crawler import carregar_manifesto

    relativo = caminho.relative_to(raiz).as_posix()
    return carregar_manifesto(raiz).get(relativo, {})


def url_origem(caminho: Path, raiz: Path) -> str:
    return origem_web(caminho, raiz).get("url", "")


def inferir_categoria(caminho: Path, raiz: Path) -> str:
    """A subpasta dentro de data/documentos vira a categoria do documento.

    Ex.: data/documentos/editais/edital-14-2026.pdf  ->  categoria "editais".
    """
    relativo = caminho.relative_to(raiz)
    return relativo.parts[0] if len(relativo.parts) > 1 else "geral"


def titulo_documento(caminho: Path, raiz: Path) -> str:
    """Titulo exibido: o da pagina original, quando houver; senao o do arquivo."""
    return origem_web(caminho, raiz).get("titulo") or inferir_titulo(caminho)


def inferir_titulo(caminho: Path) -> str:
    """Titulo legivel a partir do nome do arquivo.

    Trata separadores e nomes em CamelCase:
      calendario-academico-2026      -> "Calendario Academico 2026"
      MaranguapePPC_IntegradoEmInfo  -> "Maranguape PPC Integrado Em Info"
    """
    bruto = caminho.stem.replace("_", " ").replace("-", " ")
    # separa CamelCase: "IntegradoEm" -> "Integrado Em"; "PPCIntegrado" -> "PPC Integrado"
    bruto = re.sub(r"(?<=[a-zà-ú])(?=[A-ZÀ-Ú])", " ", bruto)
    bruto = re.sub(r"(?<=[A-ZÀ-Ú])(?=[A-ZÀ-Ú][a-zà-ú])", " ", bruto)
    bruto = re.sub(r"\s+", " ", bruto).strip()
    # so normaliza a capitalizacao se o nome veio todo em minusculas
    return bruto.title() if bruto.islower() else bruto
