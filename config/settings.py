"""
LifeOS Configuration Settings
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Paths (use LIFEOS_ prefix)
    vault_path: Path = Field(
        default=Path("./vault"),
        alias="LIFEOS_VAULT_PATH"
    )
    chroma_path: Path = Field(
        default=Path("./data/chromadb"),
        alias="LIFEOS_CHROMA_PATH"
    )

    # Server (port 8000 is canonical - keep in sync with scripts/server.sh)
    port: int = Field(default=8000, alias="LIFEOS_PORT")
    host: str = Field(default="0.0.0.0", alias="LIFEOS_HOST")

    # API Keys (no prefix - standard env var names)
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # Embedding Model
    embedding_model: str = "all-MiniLM-L6-v2"

    # Chunking
    chunk_size: int = 500  # tokens
    chunk_overlap: int = 100  # tokens (20% overlap for better boundary handling)

    # Search
    default_top_k: int = 20

    # Local LLM Router (Ollama)
    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field(default="llama3.2:3b", alias="OLLAMA_MODEL")
    ollama_timeout: int = Field(default=10, alias="OLLAMA_TIMEOUT")

    # Cross-encoder re-ranking (P9.2)
    # DISABLED: reranker deprioritizes exact keyword matches for factual queries
    # e.g., "Taylor's KTN" gets pushed down by semantically similar but wrong results
    #
    # TODO: To re-enable, implement query-type detection in hybrid_search.py:
    # - Factual queries (proper nouns, codes): preserve top-k BM25 exact matches
    # - Semantic queries (concepts, discovery): apply cross-encoder reranking
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_enabled: bool = False
    reranker_candidates: int = 50  # Fetch this many for re-ranking


settings = Settings()
