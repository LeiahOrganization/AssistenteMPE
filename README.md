# Assistente Inteligente do IFCE Campus Maranguape

Chatbot acadêmico com **LLM gratuito** e **RAG** (Retrieval-Augmented Generation) sobre os
documentos públicos do campus. Responde dúvidas sobre calendário, regimento, ementas,
normativas, editais e procedimentos administrativos — sempre **citando as fontes**.

> **PIBIC AF Jr 2026** — Edital nº 14/2026 PRPI/REITORIA-IFCE
> Coordenação: Jessyca Almeida Bessa · IFCE Campus Maranguape

---

## Arquitetura

```
Navegador (frontend estático)
        │  fetch /api/chat/stream  (Server-Sent Events)
        ▼
FastAPI (backend)
        │
        ├── 1. embed da pergunta ──► Sentence-Transformers (local, grátis)
        ├── 2. busca top-k ───────► ChromaDB (base vetorial persistente)
        ├── 3. prompt contextualizado (system prompt + trechos)
        └── 4. geração ───────────► LLM via ngrok  (openai/gpt-oss-20b)
                                     endpoint compatível com OpenAI /v1
```

| Camada | Escolha | Por quê |
|---|---|---|
| API | FastAPI + Uvicorn | streaming nativo, docs automáticas em `/docs` |
| Embeddings | `intfloat/multilingual-e5-small` | gratuito, roda local, bom em português |
| Base vetorial | ChromaDB persistente | gratuita, sem servidor, similaridade por cosseno |
| LLM | `openai/gpt-oss-20b` via ngrok | gratuito; trocar de modelo = 1 linha no `.env` |
| Frontend | HTML + CSS + JS puro | zero build, zero `npm`, fácil de manter |

Estrutura de pastas:

```
AssistenteMPE/
├── backend/
│   ├── app/
│   │   ├── main.py            # app FastAPI, health, monta o frontend
│   │   ├── config.py          # TODOS os parâmetros do RAG (via .env)
│   │   ├── llm.py             # cliente do LLM (ngrok, compatível com OpenAI)
│   │   ├── schemas.py         # contratos da API
│   │   ├── rag/
│   │   │   ├── loaders.py     # PDF, DOCX, HTML, TXT, MD → texto limpo
│   │   │   ├── chunking.py    # segmentação recursiva com sobreposição
│   │   │   ├── embeddings.py  # Sentence-Transformers
│   │   │   ├── vectorstore.py # ChromaDB
│   │   │   ├── ingest.py      # pipeline de ingestão
│   │   │   └── pipeline.py    # recuperação + prompt + fontes
│   │   └── routers/           # chat, documentos, feedback
│   ├── scripts/ingest.py      # indexação pela linha de comando
│   └── data/
│       ├── documentos/        # ◄── COLOQUE OS PDFs DO CAMPUS AQUI
│       ├── chroma/            # índice vetorial (gerado)
│       └── logs/              # feedback.jsonl (gerado)
└── frontend/
    ├── index.html
    ├── css/tokens.css         # ◄── PALETA (cores IFCE + LEIAH)
    ├── css/styles.css
    └── js/                    # api, chat, documentos, ui, app
```

---

## Como rodar

### 1. Configurar o LLM

**Google Gemini (configuração do `.env.example`):** copie o exemplo para
`backend/.env` se ele ainda não existir e substitua `COLE_SUA_CHAVE_AQUI` em
`LLM_API_KEY` pela chave do Google AI Studio. Para projetos sem acesso ao
`gemini-2.5-flash`, use `LLM_MODEL=gemini-3.5-flash-lite`. Reinicie o backend
após salvar. `/api/health` faz uma geração curta de teste com o Gemini quando
há uma chave, reutilizando o resultado por até cinco minutos. Essa consulta
pode consumir cota. Não coloque a chave no Git nem no frontend.

**Alternativa: servir o próprio LLM via ngrok.**

Em uma máquina com GPU (ou no Colab), suba um servidor compatível com a API OpenAI:

```bash
# opção A — vLLM
pip install vllm
vllm serve openai/gpt-oss-20b --port 8000

# opção B — Ollama
ollama serve && ollama pull gpt-oss:20b
```

Exponha com o ngrok:

```bash
ngrok http 8000
# → Forwarding: https://xxxx-xx-xx.ngrok-free.app
```

### 2. Backend

Use Python 3.11 ou 3.12. Para o OCR de PDFs, instale os dados de idioma do
Tesseract (`tesseract-ocr` e `tesseract-ocr-por` no Debian/Ubuntu). O PyMuPDF usa
`por` por padrão; se necessário, exporte `OCR_LANGUAGE` e `TESSDATA_PREFIX`
(diretório que contém os arquivos `.traineddata`) antes da ingestão.

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

test -e .env || cp .env.example .env
# edite o .env:
#   LLM_API_KEY=...                                    (chave do Google AI Studio)
# Ou, para o servidor próprio:
#   LLM_BASE_URL=https://xxxx-xx-xx.ngrok-free.app/v1   (não esqueça o /v1)
#   LLM_MODEL=openai/gpt-oss-20b                        (ou gpt-oss:20b no Ollama)
#   LLM_API_KEY=nao-usada-mas-obrigatoria               (se o servidor não exigir chave)
```

### 3. Alimentar a base de conhecimento

Coloque os documentos do campus em subpastas — **o nome da subpasta vira a categoria**:

```
backend/data/documentos/
├── calendario/calendario-academico-2026.pdf
├── regimento/regimento-interno.pdf
├── ementas/curso-informatica.pdf
├── editais/edital-monitoria-2026.pdf
└── faq/perguntas-frequentes.md
```

Formatos aceitos: `.pdf`, `.docx`, `.html`, `.txt`, `.md`.

```bash
python -m scripts.ingest          # indexa/atualiza
python -m scripts.ingest --forcar # recalcula mesmo para arquivos sem mudanças
python -m scripts.ingest --reset  # zera o índice e reindexa tudo
```

Prefira uma coleção nova (`COLLECTION_NAME`) para comparar modelos ou preparar um
índice piloto. `--reset` é destrutivo; a troca atômica é **por documento**, não para
a base inteira. Não faça coleta/ingestão simultâneas sobre o mesmo diretório nem
escreva na mesma coleção por processos diferentes.

#### Coletar páginas e anexos do portal do campus

O coletor salva HTML em Markdown e baixa PDFs/DOCXs vinculados nas páginas:

```bash
python -m scripts.crawl https://portal.ifce.edu.br/campus/maranguape/ \
    --categoria portal --max-paginas 30 --profundidade 2 --max-requisicoes 150
python -m scripts.ingest
```

O escopo padrão é o mesmo host e o prefixo de caminho da semente. Links PDF/DOCX
explícitos, descobertos nas páginas coletadas, também podem estar fora do
prefixo no mesmo host. O crawler verifica `robots.txt` e o escopo em cada salto,
aplica intervalo entre requisições e limita o tamanho dos downloads (`--max-mib`).

`data/documentos/_fontes.json` guarda `url_origem`, `tipo`, `status`, `data_coleta`
em UTC e `hash_arquivo` (SHA-256 do arquivo salvo, incluindo o Markdown gerado no
caso de HTML). A recoleta não regrava conteúdo idêntico; mantém a data da cópia
existente. Um HTTP 404/410 para fonte conhecida a marca como `archived`,
preservando a cópia local e retirando seus chunks na próxima ingestão. Não ter
encontrado o link numa coleta limitada **não** arquiva a fonte. Para arquivos
manuais, inclua URL e data no manifesto quando conhecidas: o pipeline calcula o
hash, mas não inventa proveniência. A data de coleta não é a data de publicação
nem indica vigência.

Revise avisos de OCR e amostras de tabelas antes de aceitar o índice. Tabelas de
PDF são preservadas quando detectadas na camada nativa; o OCR de imagens não
promete reconstruir a grade de uma tabela escaneada.

#### Avaliar a recuperação (sem LLM)

```bash
python -m scripts.eval_retrieval
python -m scripts.eval_retrieval --perguntas data/eval/perguntas_teste.json \
    --saida data/eval/relatorio_retrieval.md
python -m unittest discover -s tests -v
```

A avaliação usa a coleção e o limiar configurados. Hit@1, Hit@5 e MRR@5 são
calculados nas perguntas com resposta, por correspondência de documento
(caminho relativo à base) **e** categoria. A taxa de abstenção correta é a
fração das perguntas sem resposta que não recuperam nenhum chunk após o corte.
O limiar padrão não foi calibrado para o corpus oficial. As cinco perguntas
incluídas só servem para um teste com o **FAQ de exemplo**; remova esse FAQ e
rotule um novo conjunto ao avaliar documentos oficiais.

### 4. Subir a aplicação

```bash
uvicorn app.main:app --reload --port 8080
```

- Interface: <http://localhost:8080>
- Documentação da API: <http://localhost:8080/docs>

---

## Endpoints

| Método | Rota | Função |
|---|---|---|
| `POST` | `/api/chat` | pergunta → resposta completa + fontes |
| `POST` | `/api/chat/stream` | idem, token a token (SSE) |
| `GET`  | `/api/documentos` | lista os documentos da base |
| `GET`  | `/api/documentos/{nome}/chunks` | trechos indexados de um documento |
| `GET`  | `/api/documentos/{nome}/arquivo` | baixa/abre o documento original |
| `GET`  | `/api/documentos/estatisticas` | contagens e parâmetros do RAG |
| `POST` | `/api/documentos/upload` | envia documento (header `X-Admin-Token`) |
| `POST` | `/api/documentos/reindexar` | reindexa a base (header `X-Admin-Token`) |
| `POST` | `/api/feedback` | registra 👍/👎 do usuário |
| `GET`  | `/api/health` | estado do LLM, do índice e dos modelos |

---

## Experimentos previstos no projeto

Tudo que a Meta 2 pede comparar está no `.env` — nenhum código precisa mudar:

| Variável | O que testar |
|---|---|
| `LLM_MODEL` + `LLM_BASE_URL` | gpt-oss-20b × Llama 3 × Gemini × DeepSeek |
| `EMBEDDING_MODEL` | `multilingual-e5-small` × `e5-base` × `paraphrase-multilingual-MiniLM` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | estratégias de segmentação |
| `RETRIEVAL_TOP_K` / `RETRIEVAL_MIN_SCORE` | quantidade e qualidade dos trechos |

O prompt do sistema (regras anti-alucinação e de citação) fica em
[`backend/app/rag/pipeline.py`](backend/app/rag/pipeline.py).

Os 👍/👎 da interface vão para `backend/data/logs/feedback.jsonl` — é a matéria-prima
da avaliação qualitativa da Etapa 4.

---

## Acessibilidade (WCAG 2.1)

- link "pular para o conteúdo" e marcos semânticos (`aside`, `main`, `nav`);
- `aria-live` na área de mensagens, `aria-pressed` nos filtros e botões de feedback;
- foco visível com contraste alto, navegação completa por teclado (Enter/Shift+Enter/Esc);
- tema claro e escuro, respeito a `prefers-reduced-motion`;
- rótulos `sr-only` em todos os campos, alvos de toque ≥ 38 px.

## Cores

Toda a paleta está em [`frontend/css/tokens.css`](frontend/css/tokens.css).
Os valores atuais são uma **aproximação** (verde IFCE + azul-petróleo LEIAH):
ao receber o manual de identidade visual do LEIAH, basta trocar os seis valores
do bloco `MARCA` no topo do arquivo.
