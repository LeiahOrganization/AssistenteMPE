"""Etapa 1 - leitura dos documentos institucionais em formatos diversos.

Cada loader devolve uma lista de paginas: [(numero_da_pagina, texto)].
Formatos sem paginacao (DOCX, HTML, TXT, MD) devolvem uma unica "pagina" None.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path

from app.rag.fontes import carregar_manifesto

Pagina = tuple[int | None, str]

EXTENSOES_SUPORTADAS = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
logger = logging.getLogger(__name__)


def limpar_texto(texto: str) -> str:
    """Normaliza o texto bruto extraido dos documentos."""
    texto = unicodedata.normalize("NFKC", texto)
    texto = re.sub(r"<!--.*?-->", "", texto, flags=re.DOTALL)  # comentarios HTML
    texto = texto.replace("­", "")            # hifen de quebra invisivel
    texto = re.sub(r"-\n(?=[a-zà-ú])", "", texto)  # junta palavra quebrada na linha
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _tabela_markdown(linhas: list[list[str]], primeira_cabecalho: bool = True) -> str:
    if not linhas or (largura := max(map(len, linhas))) == 0:
        return ""
    tabela = []
    for linha in linhas:
        celulas = [re.sub(r"\s+", " ", c).strip().replace("|", r"\|") for c in linha]
        tabela.append(celulas + [""] * (largura - len(celulas)))
    if not primeira_cabecalho:
        tabela.insert(0, [f"Coluna {i}" for i in range(1, largura + 1)])
    tabela.insert(1, ["---"] * largura)
    return "\n".join("| " + " | ".join(linha) + " |" for linha in tabela)


def _pdf_com_tabelas(pagina, texto: str) -> str:
    import fitz

    tabelas = []
    for tabela in pagina.find_tables().tables:
        markdown = tabela.to_markdown().strip()
        if markdown:
            caixas = [fitz.Rect(tabela.bbox)]
            if tabela.header.external:
                caixas.append(fitz.Rect(tabela.header.bbox))
            tabelas.append((caixas, markdown))
    if not tabelas:
        return texto
    partes = [(min(c.y0 for c in caixas), caixas[0].x0, f"\n{md}\n") for caixas, md in tabelas]
    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
    for bloco in pagina.get_text("dict", flags=flags)["blocks"]:
        for linha in bloco.get("lines", []):
            fora = []
            for trecho in linha["spans"]:
                x0, y0, x1, y1 = trecho["bbox"]
                centro = fitz.Point((x0 + x1) / 2, (y0 + y1) / 2)
                if not any(centro in caixa for caixas, _ in tabelas for caixa in caixas):
                    fora.append(trecho["text"])
            if fora:
                x, y, *_ = linha["bbox"]
                partes.append((y, x, "".join(fora)))
    return "\n".join(parte for _, _, parte in sorted(partes))


def _ler_pdf(caminho: Path) -> list[Pagina]:
    import fitz

    paginas: list[Pagina] = []
    with fitz.open(caminho) as doc:
        for numero, pagina in enumerate(doc, start=1):
            nativo = limpar_texto(pagina.get_text("text", sort=True))
            texto = nativo
            if len(nativo) < 50:
                logger.warning("%s p.%d: menos de 50 caracteres; tentando OCR", caminho, numero)
                try:
                    ocr = pagina.get_textpage_ocr(
                        language=os.getenv("OCR_LANGUAGE", "por"), dpi=300, full=True
                    )
                    reconhecido = limpar_texto(pagina.get_text("text", sort=True, textpage=ocr))
                    if len(reconhecido) > len(nativo):
                        texto = reconhecido
                except (RuntimeError, ValueError, OSError, fitz.mupdf.FzErrorBase) as exc:
                    logger.warning("%s p.%d: OCR falhou: %s", caminho, numero, exc)
            try:
                estruturado = limpar_texto(_pdf_com_tabelas(pagina, nativo))
                if texto == nativo:
                    texto = estruturado or nativo
                elif estruturado != nativo and estruturado:
                    # O OCR pode acrescentar texto de imagens, mas nao substitui
                    # a estrutura identificada nas tabelas nativas.
                    texto = f"{estruturado}\n\n{texto}"
            except (RuntimeError, ValueError, TypeError, fitz.mupdf.FzErrorBase) as exc:
                logger.warning("%s p.%d: extracao de tabelas falhou: %s", caminho, numero, exc)
            if texto:
                paginas.append((numero, texto))
            else:
                logger.warning("%s p.%d: sem texto extraivel", caminho, numero)
    return paginas


def _ler_docx(caminho: Path) -> list[Pagina]:
    from docx import Document
    from docx.table import Table

    doc = Document(str(caminho))
    partes = []
    for bloco in doc.iter_inner_content():
        if isinstance(bloco, Table):
            linhas = [
                [""] * linha.grid_cols_before + [c.text for c in linha.cells]
                for linha in bloco.rows
            ]
            partes.append(_tabela_markdown(linhas))
        elif bloco.text.strip():
            partes.append(bloco.text)
    texto = limpar_texto("\n\n".join(partes))
    return [(None, texto)] if texto else []


def texto_html(sopa) -> str:
    """Converte tabelas em Markdown antes de extrair o restante do texto."""
    def span(celula, nome: str) -> int:
        try:
            return max(1, min(int(celula.get(nome, 1)), 100))
        except (TypeError, ValueError):
            return 1

    for tabela in list(sopa.find_all("table"))[::-1]:
        linhas = []
        primeira_cabecalho = False
        mescladas: dict[int, tuple[int, str]] = {}
        for numero, linha in enumerate(tabela.find_all("tr")):
            celulas = linha.find_all(["th", "td"], recursive=False)
            colunas = {i: v for i, (ate, v) in mescladas.items() if numero < ate}
            if not celulas and not colunas:
                continue
            if not linhas:
                primeira_cabecalho = any(c.name == "th" for c in celulas)
            i = 0
            for celula in celulas:
                valor = celula.get_text(" ", strip=True)
                largura = span(celula, "colspan")
                while any(j in colunas for j in range(i, i + largura)):
                    i += 1
                for j in range(i, i + largura):
                    colunas[j] = valor
                    mescladas[j] = (numero + span(celula, "rowspan"), valor)
                i += largura
            linhas.append([colunas.get(j, "") for j in range(max(colunas) + 1)])
        markdown = _tabela_markdown(linhas, primeira_cabecalho)
        if markdown:
            legenda = tabela.find("caption")
            prefixo = legenda.get_text(" ", strip=True) + "\n\n" if legenda else ""
            tabela.replace_with(f"\n\n{prefixo}{markdown}\n\n")
    return limpar_texto(sopa.get_text("\n"))


def _ler_html(caminho: Path) -> list[Pagina]:
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(caminho.read_text(encoding="utf-8", errors="ignore"), "lxml")
    for tag in sopa(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    texto = texto_html(sopa)
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


def listar_documentos(pasta: Path, manifesto: dict[str, dict] | None = None) -> list[Path]:
    """Lista recursivamente os documentos suportados da base de conhecimento."""
    manifesto = carregar_manifesto(pasta) if manifesto is None else manifesto
    return sorted(
        caminho
        for caminho in pasta.rglob("*")
        if caminho.is_file()
        and caminho.suffix.lower() in EXTENSOES_SUPORTADAS
        and not caminho.name.startswith((".", "~$", "_"))
        and manifesto.get(caminho.relative_to(pasta).as_posix(), {}).get("status") != "archived"
    )


def origem_web(caminho: Path, raiz: Path) -> dict:
    """Dados da pagina web de onde o arquivo veio, se foi coletado do portal.

    Devolve {} para documentos locais (PDF, DOCX etc.).
    """
    relativo = caminho.relative_to(raiz).as_posix()
    return carregar_manifesto(raiz).get(relativo, {})


def url_origem(caminho: Path, raiz: Path) -> str:
    fonte = origem_web(caminho, raiz)
    return fonte.get("url_origem") or fonte.get("url") or ""


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
