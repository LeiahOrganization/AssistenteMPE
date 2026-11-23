"""Coleta HTML e anexos publicos dentro do escopo do portal."""

from __future__ import annotations

import hashlib
import io
import posixpath
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser
from zipfile import BadZipFile, ZipFile

import httpx
from bs4 import BeautifulSoup

from app.rag.fontes import carregar_manifesto, gravar_atomico, hash_arquivo, salvar_manifesto
from app.rag.loaders import texto_html

USER_AGENT = (
    "AssistenteIFCEMaranguape/0.1 (pesquisa PIBIC Jr; "
    "contato: bessa.jessyca@ifce.edu.br)"
)
RUIDO = ["script", "style", "nav", "header", "footer", "form", "noscript", "iframe", "aside"]
RUIDO_LINHAS = frozenset([
    "ir para a página inicial", "ir para a busca", "ir para o menu principal",
    "ir para o conteúdo", "ir para o rodapé", "alto contraste", "acessibilidade",
    "login da área administrativa", "você está aqui:", "home", "campi",
    "instagram", "facebook", "youtube", "twitter", "linkedin", "flickr",
    "voltar ao topo", "compartilhar", "imprimir", "menu", "buscar", "pesquisar",
    "acesso à informação", "transparência e prestação de contas",
])
EXTENSOES_IGNORADAS = re.compile(
    r"\.(jpg|jpeg|png|gif|svg|webp|css|js|zip|rar|mp4|mp3|avi|ico|woff2?|ttf)$", re.I
)
ANEXO = re.compile(r"\.(pdf|docx)(?:/|$)", re.I)
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass
class Pagina:
    url: str
    titulo: str
    texto: str


@dataclass
class Relatorio:
    salvas: list[str] = field(default_factory=list)
    anexos_salvos: list[str] = field(default_factory=list)
    inalteradas: list[str] = field(default_factory=list)
    arquivadas: list[str] = field(default_factory=list)
    ignoradas: list[str] = field(default_factory=list)
    erros: list[str] = field(default_factory=list)
    requisicoes: int = 0
    duracao_s: float = 0.0


def _tipo_url(url: str) -> str:
    achado = ANEXO.search(_caminho_url(url))
    return achado[1].lower() if achado else ""


def _caminho_url(url: str) -> str:
    # Valide o caminho que o servidor pode interpretar apos decodificar a URL.
    caminho = unquote(urlparse(url).path).replace("\\", "/")
    return posixpath.normpath("/" + caminho.lstrip("/"))


def _no_escopo(url: str, semente: str, prefixo: str, anexo: bool = False) -> bool:
    parte, origem = urlparse(url), urlparse(semente)
    caminho = _caminho_url(url)
    return (
        parte.scheme in ("http", "https") and parte.netloc == origem.netloc
        and (origem.scheme != "https" or parte.scheme == "https")
        and (anexo or not prefixo or caminho == prefixo or caminho.startswith(prefixo + "/"))
    )


def _nome(url: str, extensao: str) -> str:
    caminho = urlparse(url).path.strip("/")
    nome = re.sub(r"[^a-zA-Z0-9_.-]+", "-", caminho).strip("-._")[:70] or "pagina"
    return f"{nome}-{hashlib.sha256(url.encode()).hexdigest()[:16]}.{extensao}"


def extrair(html: str, url: str) -> Pagina | None:
    sopa = BeautifulSoup(html, "lxml")
    h1 = sopa.find("h1")
    titulo = (h1 or sopa.title)
    titulo = titulo.get_text(" ", strip=True) if titulo else url
    titulo = re.sub(r"\s*[—|–-]\s*IFCE.*$", "", titulo).strip() or url
    for tag in sopa(RUIDO):
        tag.decompose()
    for principal in (sopa.find("article"), sopa.find("main"),
                      sopa.find(id=re.compile(r"content|conteudo", re.I)), sopa.body):
        if principal is None:
            continue
        texto = "\n".join(linha for linha in texto_html(principal).splitlines()
                          if linha.strip().lower() not in RUIDO_LINHAS).strip()
        if texto:
            return Pagina(url, titulo, texto)
    return None


def links_internos(html: str, base: str, prefixo: str) -> list[str]:
    sopa = BeautifulSoup(html, "lxml")
    links = {}
    for tag in sopa.find_all("a", href=True):
        try:
            url = urldefrag(urljoin(base, tag["href"])).url
            if not _no_escopo(url, base, prefixo, bool(_tipo_url(url))):
                continue
        except ValueError:  # href malformado nao invalida toda a pagina.
            continue
        if not EXTENSOES_IGNORADAS.search(urlparse(url).path):
            links[url] = None
    return list(links)


def _tipo_resposta(dados: bytes, mime: str, url: str) -> str:
    if mime in ("text/html", "application/xhtml+xml"):
        return "html"
    if b"%PDF-" in dados[:1024]:
        return "pdf"
    if (mime == MIME_DOCX or _tipo_url(url) == "docx" or dados.startswith(b"PK\x03\x04")):
        try:
            with ZipFile(io.BytesIO(dados)) as zip_doc:
                if {"[Content_Types].xml", "word/document.xml"} <= set(zip_doc.namelist()):
                    return "docx"
        except BadZipFile:
            pass
    return ""


class _Limite(Exception):
    pass


class _Bloqueado(Exception):
    pass


def coletar(
    semente: str,
    destino: Path,
    categoria: str = "portal",
    max_paginas: int = 30,
    profundidade: int = 2,
    intervalo: float = 1.0,
    max_requisicoes: int = 150,
    max_bytes: int = 25 * 1024 * 1024,
    transport: httpx.BaseTransport | None = None,
) -> Relatorio:
    if not re.fullmatch(r"[\w-]+", categoria) or categoria.startswith("_"):
        raise ValueError("Categoria invalida: use letras, numeros, hifens e underscores")
    if (max_paginas < 1 or max_requisicoes < 2 or max_bytes < 1 or profundidade < 0
            or not 0 <= intervalo < float("inf")):
        raise ValueError("Limites de coleta invalidos")
    semente = urldefrag(semente).url
    origem = urlparse(semente)
    if origem.scheme not in ("http", "https") or not origem.hostname or origem.username is not None:
        raise ValueError("Semente deve ser uma URL HTTP(S) sem credenciais")
    inicio = time.perf_counter()
    prefixo = _caminho_url(semente).rstrip("/")
    pasta = destino / categoria
    if not pasta.resolve().is_relative_to(destino.resolve()):
        raise ValueError("Categoria fora da raiz da coleta")
    manifesto = carregar_manifesto(destino)
    pasta.mkdir(parents=True, exist_ok=True)
    por_url = {}
    for nome, entrada in manifesto.items():
        if Path(nome).parent == Path(categoria):
            for chave in ("url_origem", "url", "url_solicitada"):
                if entrada.get(chave):
                    por_url[entrada[chave]] = nome
    relatorio = Relatorio()
    fila = deque([(semente, 0, "")])
    enfileiradas = {semente}
    vistas: set[str] = set()
    paginas = 0
    ultima: float | None = None

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=25, transport=transport) as cliente:
        def baixar(url: str, ler_somente: int) -> tuple[int, dict[str, str], bytes, str]:
            nonlocal ultima
            if relatorio.requisicoes >= max_requisicoes:
                raise _Limite
            if ultima is not None:
                time.sleep(max(0.0, intervalo - (time.monotonic() - ultima)))
            relatorio.requisicoes += 1
            ultima = time.monotonic()
            with cliente.stream("GET", url) as resp:
                dados = bytearray()
                if resp.is_success:
                    for bloco in resp.iter_bytes(chunk_size=64 * 1024):
                        if len(dados) + len(bloco) > ler_somente:
                            raise ValueError("resposta excede o limite de bytes")
                        dados.extend(bloco)
                return resp.status_code, dict(resp.headers), bytes(dados), resp.encoding or "utf-8"

        robots = RobotFileParser()
        url_robots = f"{origem.scheme}://{origem.netloc}/robots.txt"
        try:
            codigo, _, dados_robots, _ = baixar(url_robots, 512 * 1024)
            if codigo in (401, 403):
                robots.disallow_all = True
            elif codigo == 404 or codigo == 410:
                robots.allow_all = True
            elif 200 <= codigo < 300:
                robots.parse(dados_robots.decode("utf-8", errors="replace").splitlines())
            else:
                raise ValueError(f"HTTP {codigo}")
        except (httpx.HTTPError, ValueError) as exc:
            relatorio.erros.append(f"{url_robots}: {exc}; coleta interrompida")
            relatorio.duracao_s = round(time.perf_counter() - inicio, 2)
            return relatorio

        while fila:
            solicitada, nivel, pagina_origem = fila.popleft()
            if solicitada in vistas or (paginas >= max_paginas and not _tipo_url(solicitada)):
                continue
            vistas.add(solicitada)
            url = solicitada
            try:
                for _ in range(6):
                    if not _no_escopo(url, semente, prefixo, bool(_tipo_url(solicitada) or _tipo_url(url))):
                        raise ValueError("redirecionamento fora do escopo")
                    if not robots.can_fetch(USER_AGENT, url):
                        raise _Bloqueado
                    codigo, cabecalhos, dados, encoding = baixar(url, max_bytes)
                    if codigo not in (301, 302, 303, 307, 308):
                        break
                    url = urldefrag(urljoin(url, cabecalhos.get("location", ""))).url
                else:
                    raise ValueError("limite de redirecionamentos excedido")
            except _Limite:
                relatorio.ignoradas.append("Limite total de requisicoes atingido")
                break
            except _Bloqueado:
                relatorio.ignoradas.append(f"{url}: bloqueado pelo robots.txt")
                continue
            except (httpx.HTTPError, ValueError) as exc:
                relatorio.erros.append(f"{solicitada}: {exc}")
                continue

            anterior = por_url.get(url) or por_url.get(solicitada)
            if codigo in (404, 410) and anterior:
                entrada = manifesto[anterior]
                if entrada.get("status") != "archived":
                    entrada["status"] = "archived"
                    relatorio.arquivadas.append(anterior)
                continue
            if not 200 <= codigo < 300:
                relatorio.erros.append(f"{url}: HTTP {codigo}")
                continue
            if url != solicitada and url in vistas:
                continue
            vistas.add(url)
            mime = cabecalhos.get("content-type", "").partition(";")[0].strip().lower()
            tipo = _tipo_resposta(dados, mime, url)
            if tipo == "html" and _no_escopo(url, semente, prefixo) and not _tipo_url(url):
                if paginas >= max_paginas:
                    continue
                paginas += 1
                html = dados.decode(encoding, errors="replace")
                for link in links_internos(html, url, prefixo):
                    if (nivel < profundidade or _tipo_url(link)) and link not in enfileiradas:
                        enfileiradas.add(link)
                        fila.append((link, nivel + 1, url))
                pagina = extrair(html, url)
                if pagina is None:
                    relatorio.ignoradas.append(f"{url}: HTML sem conteudo textual")
                    continue
                titulo = pagina.titulo
                dados = f"# {titulo}\n\n{pagina.texto}\n".encode()
                extensao = "md"
            elif tipo in ("pdf", "docx"):
                titulo = Path(urlparse(url).path).stem.replace("-", " ").replace("_", " ") or url
                extensao = tipo
            else:
                relatorio.ignoradas.append(f"{url}: formato nao suportado ou conteudo invalido ({mime})")
                continue

            relativo = (anterior if anterior and Path(anterior).suffix.lower() == f".{extensao}"
                        else f"{categoria}/{_nome(url, extensao)}")
            caminho = destino / relativo
            checksum = hashlib.sha256(dados).hexdigest()
            entrada = manifesto.get(relativo, {})
            identico = caminho.is_file() and hash_arquivo(caminho) == checksum
            if identico:
                relatorio.inalteradas.append(relativo)
            else:
                gravar_atomico(caminho, dados)
                (relatorio.salvas if tipo == "html" else relatorio.anexos_salvos).append(relativo)
            data_coleta = (entrada.get("data_coleta") or entrada.get("coletado_em")) if identico else None
            manifesto[relativo] = {
                "url_origem": url, "url_solicitada": solicitada, "titulo": titulo,
                "tipo": tipo, "status": "active", "hash_arquivo": checksum,
                "data_coleta": data_coleta or datetime.now(timezone.utc).isoformat(),
                "pagina_origem": pagina_origem,
            }
            if anterior and anterior != relativo:
                manifesto[anterior]["status"] = "archived"
                relatorio.arquivadas.append(anterior)
            por_url[url] = por_url[solicitada] = relativo

    salvar_manifesto(destino, manifesto)
    relatorio.duracao_s = round(time.perf_counter() - inicio, 2)
    return relatorio
