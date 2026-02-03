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
    chroma_url: str = Field(
        default="http://localhost:8001",
        alias="LIFEOS_CHROMA_URL",
        description="ChromaDB server URL"
    )

    # Server (port 8000 is canonical - keep in sync with scripts/server.sh)
    port: int = Field(default=8000, alias="LIFEOS_PORT")
    host: str = Field(default="0.0.0.0", alias="LIFEOS_HOST")

    # API Keys (no prefix - standard env var names)
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # Embedding Model
    # mxbai-embed-large-v1: Top-tier 1024-dim model, stable and well-tested
    embedding_model: str = "mixedbread-ai/mxbai-embed-large-v1"
    embedding_cache_dir: str = Field(
        default="~/.cache/huggingface",
        alias="LIFEOS_EMBEDDING_CACHE",
        description="Directory for caching embedding model files"
    )

    # Chunking
    chunk_size: int = 500  # tokens
    chunk_overlap: int = 100  # tokens (20% overlap for better boundary handling)

    # Search
    default_top_k: int = 20

    # Local LLM Router (Ollama)
    ollama_host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    ollama_model: str = Field(default="qwen2.5:7b-instruct", alias="OLLAMA_MODEL")
    ollama_timeout: int = Field(default=45, alias="OLLAMA_TIMEOUT")  # 7B model needs more time
    ollama_retry_timeout: int = Field(default=60, alias="OLLAMA_RETRY_TIMEOUT")  # Longer timeout for retries

    # Cross-encoder re-ranking (P9.2)
    # Query-aware reranking: protects BM25 exact matches for factual queries
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_enabled: bool = True  # Re-enabled with query-aware protection
    reranker_candidates: int = 50

    # Notifications
    alert_email: str = Field(
        default="",
        alias="LIFEOS_ALERT_EMAIL",
        description="Email address for sync failure alerts"
    )

    # Slack Integration
    slack_client_id: str = Field(default="", alias="SLACK_CLIENT_ID")
    slack_client_secret: str = Field(default="", alias="SLACK_CLIENT_SECRET")
    slack_redirect_uri: str = Field(
        default="http://localhost:8000/api/crm/slack/callback",
        alias="SLACK_REDIRECT_URI"
    )

    # Work email domain for CRM category detection
    work_email_domain: str = Field(
        default="",
        alias="LIFEOS_WORK_DOMAIN",
        description="Your work email domain (e.g., yourcompany.com) for categorizing work contacts"
    )

    # CRM Owner (the user's person ID for relationship tracking)
    # WARNING: This ID is from people_entities.json and must remain stable.
    # If you rebuild people_entities.json from scratch, this ID will become
    # invalid and you'll need to find your new ID and update this value.
    # See data/README.md for why you should NEVER rebuild from scratch.
    my_person_id: str = Field(
        default="",
        alias="LIFEOS_MY_PERSON_ID",
        description="Your PersonEntity ID for relationship tracking"
    )

    # Apple Photos Integration
    photos_library_path: str = Field(
        default="~/Pictures/Photos Library.photoslibrary",
        alias="LIFEOS_PHOTOS_PATH",
        description="Path to Photos Library"
    )

    @property
    def photos_db_path(self) -> str:
        """Get path to Photos.sqlite database."""
        return f"{self.photos_library_path}/database/Photos.sqlite"

    @property
    def photos_enabled(self) -> bool:
        """Check if Photos database is available."""
        from pathlib import Path
        return Path(self.photos_db_path).exists()


settings = Settings()
