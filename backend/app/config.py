"""Application settings, loaded from environment variables / .env (no hardcoded credentials)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # storage
    data_dir: Path = Path("data")
    seed_dir: Path = Path("seed")
    eval_questions_path: Path = Path("eval/questions.jsonl")

    # crawler
    site_base_url: str = "https://www.thecarepal.com"
    crawl_user_agent: str = "CarePalAssistBot/0.1 (internship prototype; public pages only)"
    crawl_delay_seconds: float = 1.0
    crawl_timeout_seconds: float = 20.0
    crawl_render_js: bool = False
    crawl_max_bytes: int = 2_000_000

    # embeddings
    embed_backend: Literal["sentence_transformers", "hashing"] = "sentence_transformers"
    embed_model: str = "BAAI/bge-m3"
    hashing_dim: int = 1024

    # llm
    llm_provider: Literal["extractive", "openai_compat"] = "extractive"
    llm_model: str = ""
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: float = 30.0

    # retrieval
    retrieval_mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    dense_top_n: int = 20
    bm25_top_n: int = 20
    rrf_k: int = 60
    rrf_weights: dict[str, float] = {}
    context_max_chunks: int = 5
    per_page_cap: int = 3
    fused_limit: int = 20
    gate_tau_dense: float = 0.35
    gate_tau_coverage: float = 0.5

    # security / ops
    admin_api_key: SecretStr | None = None
    cors_origins: list[str] = ["http://localhost:5173"]
    rate_limit_per_minute: int = 30
    handoff_retention_days: int = 30
    max_message_chars: int = 1000

    # langsmith (optional)
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "carepal-assist"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "carepal.sqlite3"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def bm25_path(self) -> Path:
        return self.data_dir / "bm25_index.json"

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langsmith_tracing and self.langsmith_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
