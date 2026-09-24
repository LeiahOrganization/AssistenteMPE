"""Cliente do LLM gratuito servido via ngrok.

O endpoint precisa ser compativel com a API OpenAI (/v1/chat/completions), o que
cobre vLLM, llama.cpp server, LM Studio e Ollama. O modelo de referencia do
projeto e o openai/gpt-oss-20b, mas trocar de modelo e so mudar LLM_MODEL no .env
-- o que torna direta a avaliacao comparativa prevista na Meta 2.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import lru_cache

from openai import OpenAI

from app.config import settings

# O ngrok gratuito injeta uma pagina de aviso no primeiro acesso do navegador;
# este cabecalho a desativa e evita respostas HTML no lugar do JSON.
HEADERS = {"ngrok-skip-browser-warning": "true"}

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


@lru_cache
def get_client() -> OpenAI:
    return OpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
        max_retries=1,
        default_headers=HEADERS,
    )


def gerar(mensagens: list[dict[str, str]]) -> str:
    """Geracao sincrona (usada pelo endpoint /api/chat)."""
    resposta = get_client().chat.completions.create(
        model=settings.llm_model,
        messages=mensagens,  # type: ignore[arg-type]
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
    )
    return limpar_resposta(resposta.choices[0].message.content or "")


def gerar_stream(mensagens: list[dict[str, str]]) -> Iterator[str]:
    """Geracao token a token (usada pelo endpoint /api/chat/stream)."""
    fluxo = get_client().chat.completions.create(
        model=settings.llm_model,
        messages=mensagens,  # type: ignore[arg-type]
        temperature=settings.llm_temperature,
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


def verificar() -> tuple[bool, str]:
    """Checa se o tunel ngrok e o modelo estao no ar (usado em /api/health)."""
    try:
        modelos = get_client().models.list()
        disponiveis = [m.id for m in modelos.data]
        if settings.llm_model in disponiveis or not disponiveis:
            return True, f"conectado ({settings.llm_base_url})"
        return True, f"conectado, mas o modelo configurado nao esta na lista: {disponiveis[:5]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"falha ao conectar em {settings.llm_base_url}: {exc}"
