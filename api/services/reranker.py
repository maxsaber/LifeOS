"""
Cross-encoder re-ranking service for LifeOS.

Uses a cross-encoder model to re-rank search results by computing
query-document relevance scores. Much more accurate than bi-encoder
similarity because it sees query and document together.

## How It Works

Cross-encoders differ from bi-encoders:
- Bi-encoder: Embed query and document separately, compute similarity
- Cross-encoder: Process (query, document) pair together for direct relevance

This allows cross-encoders to catch nuances that bi-encoders miss,
like negation, specificity, and contextual relevance.

## Usage

    from api.services.reranker import get_reranker
    reranker = get_reranker()
    reranked = reranker.rerank(query, results, top_k=10)
"""
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


class RerankerService:
    """
    Cross-encoder re-ranking service.

    Lazy-loads model on first use to avoid slow startup.
    Caches model in memory for subsequent calls.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2"):
        """
        Initialize reranker service.

        Args:
            model_name: HuggingFace model name for cross-encoder.
                       Default is ms-marco-MiniLM-L6-v2 (~90MB, fast, accurate).
        """
        self.model_name = model_name
        self._model: Optional["CrossEncoder"] = None

    def _get_model(self) -> "CrossEncoder":
        """Lazy-load cross-encoder model."""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            logger.info(f"Loading cross-encoder model: {self.model_name}")
            self._model = CrossEncoder(self.model_name)
            logger.info("Cross-encoder model loaded")
        return self._model

    def rerank(
        self,
        query: str,
        results: list[dict],
        top_k: int = 10,
        content_key: str = "content"
    ) -> list[dict]:
        """
        Re-rank search results using cross-encoder.

        Args:
            query: Search query string
            results: List of search results with content
            top_k: Number of results to return after re-ranking
            content_key: Key in result dict containing text to score

        Returns:
            Re-ranked results with cross_encoder_score added
        """
        if not results:
            return []

        if len(results) <= top_k:
            # Not enough results to re-rank meaningfully
            # Still add cross_encoder_score for consistency
            for r in results:
                r["cross_encoder_score"] = r.get("hybrid_score", 0.5)
            return results

        model = self._get_model()

        # Prepare query-document pairs
        pairs = [(query, r.get(content_key, "")) for r in results]

        # Score all pairs
        try:
            scores = model.predict(pairs, show_progress_bar=False)
        except Exception as e:
            logger.error(f"Cross-encoder scoring failed: {e}")
            # Fall back to original ranking
            for r in results:
                r["cross_encoder_score"] = r.get("hybrid_score", 0.5)
            return results[:top_k]

        # Add scores to results
        for result, score in zip(results, scores):
            result["cross_encoder_score"] = float(score)

        # Sort by cross-encoder score (descending)
        reranked = sorted(results, key=lambda x: -x["cross_encoder_score"])

        logger.debug(
            f"Reranked {len(results)} results, "
            f"top score: {reranked[0]['cross_encoder_score']:.3f}"
        )

        return reranked[:top_k]

    def is_model_loaded(self) -> bool:
        """Check if model is already loaded."""
        return self._model is not None


# Singleton instance
_reranker_instance: Optional[RerankerService] = None


def get_reranker() -> RerankerService:
    """Get singleton reranker instance."""
    global _reranker_instance
    if _reranker_instance is None:
        from config.settings import settings
        model_name = getattr(settings, "reranker_model", "cross-encoder/ms-marco-MiniLM-L6-v2")
        _reranker_instance = RerankerService(model_name=model_name)
    return _reranker_instance
