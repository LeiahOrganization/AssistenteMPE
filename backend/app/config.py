"""Configuracao central do Assistente Inteligente do IFCE Campus Maranguape.

Todos os parametros do pipeline RAG (chunking, top-k, modelo de embedding,
endpoint do LLM) ficam aqui para facilitar os experimentos previstos na
Etapa 2 e na Etapa 3 do projeto.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent      # .../backend
PROJECT_DIR = BASE_DIR.parent                          # .../AssistenteMPE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM (endpoint compativel com OpenAI, exposto pelo ngrok) ---
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "openai/gpt-oss-20b"
    llm_api_key: str = "nao-usada-mas-obrigatoria"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 900
    llm_timeout: int = 120

    # --- Embeddings ---
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_query_prefix: str = "query:"
    embedding_passage_prefix: str = "passage:"

    # --- Recuperacao ---
    chunk_size: int = 900
    chunk_overlap: int = 150
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.30

    # --- Caminhos ---
    documents_dir: str = "data/documentos"
    chroma_dir: str = "data/chroma"
    logs_dir: str = "data/logs"
    collection_name: str = "ifce_maranguape"

    # --- API ---
    cors_origins: str = "*"
    admin_token: str = "troque-este-token"

    # ---------- caminhos absolutos ----------
    @property
    def documents_path(self) -> Path:
        return self._abs(self.documents_dir)

    @property
    def chroma_path(self) -> Path:
        return self._abs(self.chroma_dir)

    @property
    def logs_path(self) -> Path:
        return self._abs(self.logs_dir)

    @property
    def frontend_path(self) -> Path:
        return PROJECT_DIR / "frontend"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @staticmethod
    def _abs(value: str) -> Path:
        path = Path(value)
        path = path if path.is_absolute() else BASE_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
