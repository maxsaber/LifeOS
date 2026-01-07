"""
LifeOS Configuration Settings
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="LIFEOS_",
        env_file=".env",
        extra="ignore"
    )

    # Paths
    vault_path: Path = Path(os.getenv("LIFEOS_VAULT_PATH", "/Users/nathanramia/Notes 2025"))
    chroma_path: Path = Path(os.getenv("LIFEOS_CHROMA_PATH", "./data/chromadb"))

    # Server
    port: int = int(os.getenv("LIFEOS_PORT", "8080"))
    host: str = os.getenv("LIFEOS_HOST", "0.0.0.0")

    # API Keys
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Embedding Model
    embedding_model: str = "all-MiniLM-L6-v2"

    # Chunking
    chunk_size: int = 500  # tokens
    chunk_overlap: int = 50  # tokens

    # Search
    default_top_k: int = 20


settings = Settings()
