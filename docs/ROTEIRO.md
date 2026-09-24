# Roteiro: do PT ao código

Mapa entre as etapas do projeto (PT PIBIC AF Jr 2026) e o que já existe no repositório.

| Etapa do PT | Período | Situação | Onde mexer |
|---|---|---|---|
| **1.** Construção da base de conhecimento | Mês 1–2 | Estrutura pronta; **falta coletar os documentos reais** | `backend/data/documentos/<categoria>/` + `app/rag/loaders.py` |
| **2.** Indexação semântica e estudo dos LLMs gratuitos | Mês 2–3 | Pipeline funcionando com `multilingual-e5-small` + ChromaDB | `.env` (`EMBEDDING_MODEL`, `CHUNK_SIZE`) + `app/rag/chunking.py` |
| **3.** Desenvolvimento do pipeline RAG | Mês 3–6 | Implementado ponta a ponta com citação de fontes | `app/rag/pipeline.py` (prompt) + `.env` (`RETRIEVAL_TOP_K`) |
| **4.** Coleta de 100 perguntas reais e avaliação | Mês 6–8 | **A fazer** — infraestrutura de coleta pronta | `backend/data/logs/feedback.jsonl` |
| **5.** Interface web acessível | Mês 8–10 | Implementada (chat + base de conhecimento, WCAG 2.1) | `frontend/` |
| **6.** Validação, documentação e disseminação | Mês 10–12 | **A fazer** | relatório e resumo expandido |

---

## Próximos passos concretos

### Etapa 1 — alimentar a base (prioridade)
1. Baixar do portal do campus: calendário acadêmico, regimento/organização didática,
   ementas dos cursos, editais vigentes, FAQ, normativas.
2. Salvar em `backend/data/documentos/<categoria>/`, com nomes descritivos
   (o nome do arquivo vira o título exibido na interface).
3. Rodar `python -m scripts.ingest` e conferir na aba **Base de Conhecimento**
   se cada documento gerou uma quantidade razoável de trechos.
4. **Atenção a PDFs digitalizados (imagem):** eles não têm texto extraível e serão
   ignorados com o aviso "nenhum texto extraído". Nesse caso é preciso OCR
   (ex.: `ocrmypdf`) antes da indexação.

### Etapa 2 — experimentos de recuperação
Planilha sugerida (uma linha por configuração):

| # | embedding | chunk_size | overlap | top_k | acertos em 20 perguntas |
|---|---|---|---|---|---|

Basta alterar o `.env`, rodar `python -m scripts.ingest --reset` e repetir o conjunto
de perguntas de teste.

### Etapa 3 — comparação entre LLMs (Meta 2)
Cada modelo é uma combinação de `LLM_BASE_URL` + `LLM_MODEL` no `.env`:

| Modelo | Como servir | Observação |
|---|---|---|
| `openai/gpt-oss-20b` | vLLM/Ollama + ngrok | modelo de referência do projeto |
| Llama 3 (Groq) | `https://api.groq.com/openai/v1` | já é compatível com OpenAI, dispensa ngrok |
| DeepSeek | `https://api.deepseek.com/v1` | idem |
| Gemini | precisa de adaptador OpenAI-compatible | ver Google AI Studio |

Registrar, para cada modelo: acurácia factual, completude, clareza e adequação da fonte
(a rubrica da Etapa 4).

### Etapa 4 — avaliação com perguntas reais
- Coletar ≥ 100 perguntas com a comunidade (formulário ou entrevistas).
- Para cada pergunta: resposta do chatbot × resposta do servidor da secretaria.
- Registrar em planilha com a rubrica; os 👍/👎 da interface entram como dado complementar
  (`backend/data/logs/feedback.jsonl`).
- Consentimento informado e anonimização, conforme previsto no PT.

---

## Achado experimental: scores comprimidos

O modelo `multilingual-e5-small` devolve similaridades numa faixa estreita — nos
testes com o PPC e o portal, **todos** os trechos ficaram entre 0,86 e 0,90,
inclusive os irrelevantes. Consequências práticas:

- `RETRIEVAL_MIN_SCORE=0.30` nunca corta nada; o valor é decorativo hoje.
- Não dá para usar o score como medida de confiança na interface.
- O que separa o trecho certo do errado é a **ordem**, não a distância.

Isso é material de relatório, não defeito. Duas linhas de investigação para a Meta 2:
1. medir a faixa real de scores por modelo de embedding e calibrar o corte por modelo;
2. testar um *reranker* (cross-encoder) sobre os 20 primeiros resultados — é onde a
   diferença entre trechos volta a aparecer.

---

## Lição da coleta web (registrar na metodologia)

Duas falhas reais encontradas ao indexar o portal, ambas típicas de RAG e que rendem
discussão no relatório:

1. **Chunk pequeno demais vence a busca.** O título isolado de uma página virou um
   chunk de 108 caracteres. Ele casava com o *assunto* da pergunta (contatos) sem
   conter a *informação* (o telefone) — e foi recuperado no lugar do trecho útil.
   Correção: blocos abaixo de 250 caracteres são fundidos no seguinte
   (`_juntar_pequenos` em `app/rag/chunking.py`).
2. **Boilerplate de navegação polui os vetores.** "Ir para a busca", "Alto contraste"
   e links de redes sociais apareciam em toda página, aproximando páginas que não têm
   nada a ver entre si. Correção: lista de linhas-ruído em `app/rag/crawler.py`.

Ambas mostram que, em RAG, **a qualidade do pré-processamento pesa mais que a escolha
do LLM** — uma boa frase de conclusão para o resumo expandido.

---

## Limitações conhecidas (importantes para o relatório)

- **Sem OCR**: PDFs digitalizados não são indexados.
- **Coleta web sem JavaScript**: o coletor lê o HTML servido. Páginas cujo conteúdo é
  montado por JS no navegador podem vir incompletas — conferir sempre uma amostra do
  Markdown gerado antes de confiar nas respostas.
- **Sem reranking**: a recuperação é só por similaridade de cosseno. Um *cross-encoder*
  de reranking é uma evolução natural (e gratuita) a documentar como trabalho futuro.
- **Histórico não persistido**: a conversa vive apenas na aba do navegador.
- **Sem autenticação de usuário**: as rotas de escrita são protegidas apenas pelo
  `ADMIN_TOKEN` do `.env` — suficiente para uso interno, insuficiente para exposição pública.
- **Dependência do ngrok**: a URL do túnel gratuito muda a cada reinício; é preciso
  atualizar `LLM_BASE_URL` no `.env` e reiniciar o backend.
