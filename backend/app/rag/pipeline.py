"""Etapa 3 - pipeline RAG completo.

pergunta -> embedding -> recuperacao no Chroma -> prompt contextualizado ->
geracao pelo LLM -> resposta com indicacao explicita das fontes.
"""

from __future__ import annotations

from app.config import settings
from app.rag import embeddings, vectorstore

SYSTEM_PROMPT = """Voce e o Assistente Inteligente do IFCE Campus Maranguape.
Responda duvidas da comunidade academica (estudantes, familiares, servidores e
visitantes) sobre calendario academico, regimento, ementas, normativas internas,
editais, atividades e procedimentos administrativos do campus.

REGRAS OBRIGATORIAS:
1. Responda SOMENTE com base nos TRECHOS DOS DOCUMENTOS fornecidos abaixo.
2. Se os trechos nao contiverem a informacao, diga com franqueza que a base
   institucional consultada nao cobre essa duvida e oriente a pessoa a procurar
   a secretaria ou a coordenacao do curso. NUNCA invente datas, prazos, numeros
   de edital, artigos de regimento ou nomes.
3. Cite as fontes no fim da resposta usando o formato [Fonte N], referindo-se
   APENAS aos trechos que voce realmente usou para responder. Se nenhum trecho
   contiver a informacao pedida, NAO cite fonte nenhuma.
4. Escreva em portugues do Brasil, com linguagem clara e acessivel a quem nao
   esta habituado a documentos oficiais. Prefira frases curtas e listas.
5. Quando a informacao depender de prazo ou ano letivo, avise que o usuario deve
   conferir a versao vigente do documento citado.
6. Nao trate de assuntos fora do contexto institucional do IFCE Maranguape."""

SEM_CONTEXTO = (
    "Nao encontrei nenhum trecho relacionado a essa pergunta na base de documentos "
    "do IFCE Campus Maranguape.\n\n"
    "Isso pode acontecer se o documento ainda nao foi adicionado a base ou se a "
    "pergunta foge do escopo institucional. Voce pode:\n\n"
    "- reformular a pergunta com outras palavras;\n"
    "- consultar a aba **Base de Conhecimento** para ver o que ja esta indexado;\n"
    "- procurar diretamente a secretaria academica do campus."
)


def montar_contexto(resultados: list[dict]) -> str:
    """Formata os trechos recuperados no bloco de contexto do prompt."""
    blocos = []
    for i, item in enumerate(resultados, start=1):
        meta = item["metadata"]
        pagina = meta.get("pagina", -1)
        local = f", pagina {pagina}" if isinstance(pagina, int) and pagina > 0 else ""
        blocos.append(
            f"[Fonte {i}] {meta.get('titulo', meta.get('documento'))}"
            f" (categoria: {meta.get('categoria')}{local})\n{item['texto']}"
        )
    return "\n\n---\n\n".join(blocos)


def recuperar(pergunta: str, top_k: int | None = None, categoria: str | None = None) -> list[dict]:
    """Busca semantica com corte por score minimo."""
    top_k = top_k or settings.retrieval_top_k
    vetor = embeddings.embed_pergunta(pergunta)
    resultados = vectorstore.buscar(vetor, top_k=top_k, categoria=categoria)
    filtrados = [r for r in resultados if r["score"] >= settings.retrieval_min_score]
    # se o corte zerar tudo, devolve o melhor resultado para o LLM julgar
    return filtrados or resultados[:1]


def montar_mensagens(
    pergunta: str, resultados: list[dict], historico: list[dict] | None = None
) -> list[dict[str, str]]:
    mensagens: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # historico curto, apenas para manter o fio da conversa
    for msg in (historico or [])[-6:]:
        mensagens.append({"role": msg["role"], "content": msg["content"]})

    contexto = montar_contexto(resultados)
    mensagens.append(
        {
            "role": "user",
            "content": (
                f"TRECHOS DOS DOCUMENTOS DO IFCE CAMPUS MARANGUAPE:\n\n{contexto}\n\n"
                f"---\n\nPERGUNTA DA COMUNIDADE: {pergunta}\n\n"
                "Responda seguindo as regras, citando [Fonte N]."
            ),
        }
    )
    return mensagens


def formatar_fontes(resultados: list[dict]) -> list[dict]:
    """Prepara as fontes exibidas no painel lateral da interface."""
    fontes = []
    for item in resultados:
        meta = item["metadata"]
        pagina = meta.get("pagina", -1)
        texto = item["texto"]
        fontes.append(
            {
                "chunk_id": item["chunk_id"],
                "documento": meta.get("documento", ""),
                "titulo": meta.get("titulo", ""),
                "categoria": meta.get("categoria", "geral"),
                "pagina": pagina if isinstance(pagina, int) and pagina > 0 else None,
                "trecho": texto[:600] + ("..." if len(texto) > 600 else ""),
                "score": item["score"],
                "url": meta.get("url", ""),
            }
        )
    return fontes
