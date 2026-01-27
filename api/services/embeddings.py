"""
Embedding service using sentence-transformers.

Uses all-MiniLM-L6-v2 for local embedding generation.

NOTE: sentence_transformers is imported lazily to avoid slow startup.
This allows tests to import this module without loading the ML library.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class EmbeddingService:
    """Service for generating text embeddings."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding service.

        Args:
            model_name: Name of the sentence-transformers model to use.
        """
        self.model_name = model_name
        self._model: Any = None

    @property
    def model(self) -> "SentenceTransformer":
        """Lazy-load the model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            List of floats representing the embedding vector
        """
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return [emb.tolist() for emb in embeddings]

    @property
    def embedding_dimension(self) -> int:
        """Return the dimension of embeddings produced by this model."""
        # all-MiniLM-L6-v2 produces 384-dimensional embeddings
        return 384


# Singleton instance
_embedding_service: EmbeddingService | None = None


def get_embedding_service(model_name: str = "all-MiniLM-L6-v2") -> EmbeddingService:
    """
    Get or create the embedding service singleton.

    Args:
        model_name: Model to use (only used on first call)

    Returns:
        EmbeddingService instance
    """
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(model_name)
    return _embedding_service
