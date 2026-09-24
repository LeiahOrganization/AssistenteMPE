"""Etapa 1 (extensao) - coleta de paginas web institucionais.

Percorre o portal do campus a partir de uma URL semente, extrai o conteudo
principal de cada pagina e salva em Markdown dentro de data/documentos/, para
que o pipeline de ingestao ja existente indexe normalmente.

Cuidados de boa conduta na coleta:
  - so segue links do mesmo dominio e sob o prefixo de caminho informado;
  - respeita o robots.txt quando ele existe;
  - espera um intervalo entre requisicoes (padrao 1s);
  - tem teto de paginas e de profundidade.

A URL de origem de cada pagina fica registrada em data/documentos/_fontes.json,
o que permite a interface citar o link vivo em vez do arquivo baixado.
"""

from __future__ import annotations

import json
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MANIFESTO = "_fontes.json"

USER_AGENT = (
    "AssistenteIFCEMaranguape/0.1 (pesquisa PIBIC Jr; "
    "contato: bessa.jessyca@ifce.edu.br)"
)

# blocos que nunca fazem parte do conteudo util de uma pagina institucional
RUIDO = ["script", "style", "nav", "header", "footer", "form", "noscript", "iframe", "aside"]

# linhas de navegacao/acessibilidade que se repetem em toda pagina do portal e
# so poluiriam os chunks (comparadas em minusculas, sem acentuacao de espacos)
RUIDO_LINHAS = frozenset(
    l.lower()
    for l in [
        "ir para a página inicial", "ir para a busca", "ir para o menu principal",
        "ir para o conteúdo", "ir para o rodapé", "alto contraste", "acessibilidade",
        "login da área administrativa", "você está aqui:", "home", "campi",
        "instagram", "facebook", "youtube", "twitter", "linkedin", "flickr",
        "voltar ao topo", "compartilhar", "imprimir", "menu", "buscar", "pesquisar",
        "acesso à informação", "transparência e prestação de contas",
    ]
)

EXTENSOES_IGNORADAS = re.compile(
    r"\.(jpg|jpeg|png|gif|svg|webp|css|js|zip|rar|mp4|mp3|avi|ico|woff2?|ttf)$", re.I
)


@dataclass
class Pagina:
    url: str
    titulo: str
    texto: str


@dataclass
class Relatorio:
    salvas: list[str] = field(default_factory=list)
    ignoradas: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)
    duracao_s: float = 0.0


# ------------------------------------------------------------------ extracao

def _limpar_nome(url: str) -> str:
    """Converte a URL em um nome de arquivo legivel e estavel."""
    caminho = urlparse(url).path.strip("/")
    nome = caminho.replace("/", "-") or "index"
    nome = re.sub(r"[^a-zA-Z0-9\-_.]", "-", nome)
    nome = re.sub(r"-{2,}", "-", nome).strip("-")
    return (nome[:90] or "pagina") + ".md"


def extrair(html: str, url: str) -> Pagina | None:
    """Extrai titulo e conteudo principal de uma pagina."""
    sopa = BeautifulSoup(html, "lxml")

    titulo = sopa.title.get_text(strip=True) if sopa.title else url
    titulo = re.sub(r"\s*[—|–-]\s*IFCE.*$", "", titulo).strip() or url

    for tag in sopa(RUIDO):
        tag.decompose()

    # escolhe o container com MAIS texto: em portais modernos o <main> as vezes
    # e so um esqueleto, e o conteudo real fica no body
    candidatos = [
        sopa.find("article"),
        sopa.find("main"),
        sopa.find(id=re.compile(r"content|conteudo", re.I)),
        sopa.body,
    ]
    principal = max(
        (c for c in candidatos if c is not None),
        key=lambda c: len(c.get_text(" ", strip=True)),
        default=None,
    )
    if principal is None:
        return None

    linhas = [l.strip() for l in principal.get_text("\n").split("\n")]
    # descarta linhas muito curtas (restos de menu) e o boilerplate do portal
    texto = "\n".join(
        l for l in linhas if len(l) > 2 and l.lower() not in RUIDO_LINHAS
    )
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()

    return Pagina(url=url, titulo=titulo, texto=texto) if len(texto) > 200 else None


def links_internos(html: str, base: str, prefixo: str) -> list[str]:
    """Links da mesma origem e sob o prefixo de caminho, sem ancora nem arquivo binario."""
    sopa = BeautifulSoup(html, "lxml")
    origem = urlparse(base)
    encontrados: list[str] = []

    for tag in sopa.find_all("a", href=True):
        destino = urldefrag(urljoin(base, tag["href"])).url
        parte = urlparse(destino)
        if parte.scheme not in ("http", "https"):
            continue
        if parte.netloc != origem.netloc:
            continue
        if not parte.path.startswith(prefixo):
            continue
        if EXTENSOES_IGNORADAS.search(parte.path):
            continue
        encontrados.append(destino)

    return list(dict.fromkeys(encontrados))


# ------------------------------------------------------------------ manifesto

def carregar_manifesto(raiz: Path) -> dict[str, dict]:
    caminho = raiz / MANIFESTO
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def salvar_manifesto(raiz: Path, dados: dict[str, dict]) -> None:
    (raiz / MANIFESTO).write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ------------------------------------------------------------------ coleta

def _robots(semente: str) -> urllib.robotparser.RobotFileParser | None:
    parte = urlparse(semente)
    leitor = urllib.robotparser.RobotFileParser()
    leitor.set_url(f"{parte.scheme}://{parte.netloc}/robots.txt")
    try:
        leitor.read()
        # portais que devolvem HTML no lugar do robots.txt nao tem regra valida
        return leitor if leitor.default_entry or leitor.entries else None
    except Exception:  # noqa: BLE001
        return None


def coletar(
    semente: str,
    destino: Path,
    categoria: str = "portal",
    max_paginas: int = 30,
    profundidade: int = 2,
    intervalo: float = 1.0,
) -> Relatorio:
    """Percorre o site a partir da semente e salva as paginas em Markdown."""
    inicio = time.perf_counter()
    relatorio = Relatorio()

    prefixo = urlparse(semente).path.rstrip("/") or "/"
    robots = _robots(semente)

    pasta = destino / categoria
    pasta.mkdir(parents=True, exist_ok=True)
    manifesto = carregar_manifesto(destino)

    fila: list[tuple[str, int]] = [(urldefrag(semente).url, 0)]
    vistas: set[str] = set()
    hoje = date.today().isoformat()

    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=25.0,
    ) as cliente:
        while fila and len(relatorio.salvas) < max_paginas:
            url, nivel = fila.pop(0)
            if url in vistas:
                continue
            vistas.add(url)

            if robots is not None and not robots.can_fetch(USER_AGENT, url):
                relatorio.ignoradas.append(f"{url}: bloqueado pelo robots.txt")
                continue

            try:
                resposta = cliente.get(url)
                resposta.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                relatorio.erros.append(f"{url}: {exc}")
                continue

            if "text/html" not in resposta.headers.get("content-type", ""):
                relatorio.ignoradas.append(f"{url}: nao e HTML")
                continue

            pagina = extrair(resposta.text, url)
            if pagina is None:
                relatorio.ignoradas.append(f"{url}: conteudo curto demais")
            else:
                nome = _limpar_nome(url)
                arquivo = pasta / nome
                arquivo.write_text(
                    f"# {pagina.titulo}\n\n"
                    f"<!-- origem: {url} | coletado em: {hoje} -->\n\n"
                    f"{pagina.texto}\n",
                    encoding="utf-8",
                )
                relativo = arquivo.relative_to(destino).as_posix()
                manifesto[relativo] = {
                    "url": url,
                    "titulo": pagina.titulo,
                    "coletado_em": hoje,
                }
                relatorio.salvas.append(relativo)
                print(f"  [ok] {url}\n       -> {relativo} ({len(pagina.texto)} caracteres)")

            if nivel < profundidade:
                for link in links_internos(resposta.text, url, prefixo):
                    if link not in vistas:
                        fila.append((link, nivel + 1))

            time.sleep(intervalo)

    salvar_manifesto(destino, manifesto)
    relatorio.duracao_s = round(time.perf_counter() - inicio, 2)
    return relatorio
