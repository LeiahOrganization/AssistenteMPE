"""Etapa 1/2 - segmentacao dos documentos em chunks para indexacao semantica.

Estrategia: divisao recursiva por separadores naturais (paragrafo -> linha ->
frase -> palavra), com sobreposicao configuravel. Manter o texto coeso importa
mais do que o tamanho exato: chunks que cortam uma tabela ou um artigo do
regimento no meio degradam a recuperacao.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEPARADORES = ["\n\n", "\n", ". ", "; ", ", ", " "]


@dataclass
class Chunk:
    texto: str
    indice: int
    pagina: int | None


def _dividir(texto: str, tamanho: int, separadores: list[str]) -> list[str]:
    if len(texto) <= tamanho:
        return [texto]
    if not separadores:
        return [texto[i : i + tamanho] for i in range(0, len(texto), tamanho)]

    sep, *resto = separadores
    partes = texto.split(sep)
    blocos: list[str] = []
    atual = ""

    for parte in partes:
        candidato = f"{atual}{sep}{parte}" if atual else parte
        if len(candidato) <= tamanho:
            atual = candidato
            continue
        if atual:
            blocos.append(atual)
        if len(parte) > tamanho:
            blocos.extend(_dividir(parte, tamanho, resto))
            atual = ""
        else:
            atual = parte

    if atual:
        blocos.append(atual)
    return blocos


def _cauda(texto: str, tamanho: int) -> str:
    """Ultimos caracteres do bloco anterior, cortando em limite de palavra."""
    if tamanho <= 0 or not texto:
        return ""
    trecho = texto[-tamanho:]
    espaco = trecho.find(" ")
    return trecho[espaco + 1 :] if espaco != -1 else trecho


def _juntar_pequenos(blocos: list[str], tamanho: int, minimo: int) -> list[str]:
    """Funde blocos curtos demais no seguinte.

    Sem isso, um titulo isolado vira um chunk de ~100 caracteres que compete na
    busca com o trecho que realmente responde a pergunta -- e costuma ganhar,
    porque casa com o assunto sem conter a informacao.
    """
    saida: list[str] = []
    pendente = ""

    for bloco in blocos:
        candidato = f"{pendente}\n{bloco}".strip() if pendente else bloco
        if len(candidato) < minimo:
            pendente = candidato
            continue
        # so funde se o resultado nao estourar demais o tamanho alvo
        if pendente and len(candidato) <= tamanho * 1.4:
            saida.append(candidato)
        else:
            if pendente:
                saida.append(pendente)
            saida.append(bloco)
        pendente = ""

    if pendente:
        if saida:
            saida[-1] = f"{saida[-1]}\n{pendente}"
        else:
            saida.append(pendente)
    return saida


def segmentar(
    paginas: list[tuple[int | None, str]],
    tamanho: int = 900,
    sobreposicao: int = 150,
    minimo: int = 250,
) -> list[Chunk]:
    """Transforma paginas de texto em chunks com metadados de pagina."""
    chunks: list[Chunk] = []
    indice = 0

    for pagina, texto in paginas:
        blocos = _dividir(texto.strip(), tamanho, SEPARADORES)
        blocos = _juntar_pequenos(blocos, tamanho, minimo)
        anterior = ""
        for bloco in blocos:
            bloco = bloco.strip()
            if not bloco:
                continue
            # sobreposicao: reaproveita o final do bloco anterior como contexto
            cauda = _cauda(anterior, sobreposicao)
            corpo = f"{cauda} {bloco}".strip() if cauda else bloco
            corpo = re.sub(r"\s+", " ", corpo).strip()
            if len(corpo) < minimo:
                anterior = bloco
                continue
            chunks.append(Chunk(texto=corpo, indice=indice, pagina=pagina))
            indice += 1
            anterior = bloco

    return chunks
