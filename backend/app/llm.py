"""Cliente para Gemini e outros provedores com endpoint compativel com OpenAI."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from functools import lru_cache
from urllib.parse import urlsplit

from openai import APIConnectionError, APIStatusError, OpenAI

from app.config import settings

# O ngrok gratuito injeta uma pagina de aviso no primeiro acesso do navegador;
# este cabecalho a desativa e evita respostas HTML no lugar do JSON.
HEADERS = {"ngrok-skip-browser-warning": "true"}
_CHAVE_PLACEHOLDER = "COLE_SUA_CHAVE_AQUI"
_CHAVE_AUSENTE = "Preencha LLM_API_KEY no backend/.env e reinicie o backend."

# Modelos da familia gpt-oss podem emitir o raciocinio antes da resposta final.
_PADROES_RACIOCINIO = [
    re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<\|channel\|>analysis.*?<\|(?:end|message)\|>", re.DOTALL),
    re.compile(r"<\|start\|>assistant<\|channel\|>final<\|message\|>", re.IGNORECASE),
]


def limpar_resposta(texto: str) -> str:
    for padrao in _PADROES_RACIOCINIO:
        texto = padrao.sub("", texto)
    return texto.strip()


def _gemini() -> bool:
    url = urlsplit(settings.llm_base_url)
    return url.scheme == "https" and url.hostname == "generativelanguage.googleapis.com"


def _chave_ausente() -> bool:
    return settings.llm_api_key.strip() in ("", _CHAVE_PLACEHOLDER)


@lru_cache
def get_client() -> OpenAI:
    if _gemini() and _chave_ausente():
        raise ValueError(_CHAVE_AUSENTE)
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key.strip(),
        timeout=settings.llm_timeout,
        max_retries=1,
        default_headers=None if _gemini() else HEADERS,
    )


def gerar(mensagens: list[dict[str, str]]) -> str:
    """Geracao sincrona (usada pelo endpoint /api/chat)."""
    resposta = get_client().chat.completions.create(
        model=settings.llm_model,
        messages=mensagens,  # type: ignore[arg-type]
        **({} if _gemini() else {"temperature": settings.llm_temperature}),
        max_tokens=settings.llm_max_tokens,
    )
    return limpar_resposta(resposta.choices[0].message.content or "")


def gerar_stream(mensagens: list[dict[str, str]]) -> Iterator[str]:
    """Geracao token a token (usada pelo endpoint /api/chat/stream)."""
    fluxo = get_client().chat.completions.create(
        model=settings.llm_model,
        messages=mensagens,  # type: ignore[arg-type]
        **({} if _gemini() else {"temperature": settings.llm_temperature}),
        max_tokens=settings.llm_max_tokens,
        stream=True,
    )
    dentro_do_raciocinio = False
    for parte in fluxo:
        if not parte.choices:
            continue
        pedaco = parte.choices[0].delta.content or ""
        if not pedaco:
            continue
        # filtro leve de raciocinio em streaming
        if "<think>" in pedaco:
            dentro_do_raciocinio = True
            pedaco = pedaco.split("<think>")[0]
        if dentro_do_raciocinio:
            if "</think>" in pedaco:
                dentro_do_raciocinio = False
                pedaco = pedaco.split("</think>")[-1]
            else:
                continue
        if pedaco:
            yield pedaco


def explicar_falha(exc: Exception) -> str:
    """Mensagens publicas sem incluir corpos de erro ou credenciais."""
    if _gemini() and _chave_ausente():
        return _CHAVE_AUSENTE
    if isinstance(exc, APIConnectionError):
        return "Nao foi possivel conectar ao provedor do modelo."
    if isinstance(exc, APIStatusError):
        orientacao = {
            400: "Verifique a configuracao da API e do modelo.",
            401: "Verifique a chave de API.",
            403: "Verifique a chave e as permissoes do projeto.",
            404: "Verifique se o modelo esta disponivel para o seu projeto.",
            429: "Verifique a cota ou o limite de requisicoes.",
        }.get(exc.status_code, "Verifique a disponibilidade do provedor.")
        return f"Provedor retornou HTTP {exc.status_code}. {orientacao}"
    return "Falha ao consultar o provedor do modelo. Confira a configuracao do backend."


@lru_cache(maxsize=1)
def _verificar_gemini(_janela: int) -> tuple[bool, str]:
    # O catalogo pode listar um modelo sem que o projeto tenha acesso a geracao.
    try:
        get_client().with_options(timeout=8, max_retries=0).chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": "Responda OK."}],
            max_tokens=16,
        )
    except Exception as exc:
        return False, explicar_falha(exc)
    return True, "Google Gemini aceitou uma solicitacao de geracao para o modelo configurado."


def verificar() -> tuple[bool, str]:
    """Checa o acesso ao modelo (usado em /api/health)."""
    if _gemini():
        if _chave_ausente():
            return False, _CHAVE_AUSENTE
        return _verificar_gemini(int(time.monotonic() // 300))
    try:
        modelos = get_client().models.list()
        disponiveis = [m.id for m in modelos.data]
        if settings.llm_model in disponiveis:
            return True, "O modelo configurado consta no catalogo do provedor."
        return False, "O modelo configurado nao consta no catalogo do provedor."
    except Exception as exc:
        return False, explicar_falha(exc)
