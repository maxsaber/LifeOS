"""
Hybrid Search for LifeOS.

Combines vector similarity search with BM25 keyword search
using Reciprocal Rank Fusion (RRF).
"""
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional, TYPE_CHECKING

# Lazy imports to avoid slow ChromaDB initialization at import time
if TYPE_CHECKING:
    from api.services.vectorstore import VectorStore
    from api.services.bm25_index import BM25Index

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    vector_results: list[str],
    bm25_results: list[str],
    k: int = 60
) -> list[tuple[str, float]]:
    """
    Merge two ranked lists using Reciprocal Rank Fusion.

    RRF formula: score = sum(1 / (k + rank)) for each list
    k = 60 is the standard constant from the original paper.

    Args:
        vector_results: List of doc IDs ranked by vector similarity
        bm25_results: List of doc IDs ranked by BM25 relevance
        k: Ranking constant (default 60)

    Returns:
        List of (doc_id, rrf_score) tuples sorted by score descending
    """
    scores = defaultdict(float)

    # Score from vector results
    seen_vector = set()
    for rank, doc_id in enumerate(vector_results):
        if doc_id not in seen_vector:
            scores[doc_id] += 1 / (k + rank + 1)
            seen_vector.add(doc_id)

    # Score from BM25 results
    seen_bm25 = set()
    for rank, doc_id in enumerate(bm25_results):
        if doc_id not in seen_bm25:
            scores[doc_id] += 1 / (k + rank + 1)
            seen_bm25.add(doc_id)

    # Sort by score descending
    sorted_results = sorted(scores.items(), key=lambda x: -x[1])

    return sorted_results


def calculate_recency_boost(date_str: Optional[str], max_boost: float = 0.5) -> float:
    """
    Calculate recency boost based on document date.

    Args:
        date_str: ISO format date string
        max_boost: Maximum boost value (default 0.5)

    Returns:
        Boost value between 0.0 and max_boost
    """
    if not date_str:
        return 0.0

    try:
        # Parse various date formats
        if "T" in date_str:
            doc_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            doc_date = datetime.fromisoformat(date_str)

        # Make naive datetime for comparison
        if doc_date.tzinfo:
            doc_date = doc_date.replace(tzinfo=None)

        now = datetime.now()
        days_old = (now - doc_date).days

        # Decay function: newer = higher boost
        # 0 days old = max_boost, 365 days old = ~0
        if days_old <= 0:
            return max_boost
        elif days_old >= 365:
            return 0.0
        else:
            # Exponential decay
            return max_boost * (1 - (days_old / 365) ** 0.5)

    except (ValueError, TypeError):
        return 0.0


class HybridSearch:
    """
    Combines vector and BM25 search using RRF fusion.

    Falls back to vector-only search if BM25 is unavailable.
    """

    def __init__(
        self,
        vector_store: Optional["VectorStore"] = None,
        bm25_index: Optional["BM25Index"] = None
    ):
        """
        Initialize hybrid search.

        Args:
            vector_store: Vector store instance (default creates new)
            bm25_index: BM25 index instance (default uses singleton)
        """
        self.vector_store = vector_store
        self.bm25_index = bm25_index

    def _get_vector_store(self):
        """Lazy-load vector store."""
        if self.vector_store is None:
            from api.services.vectorstore import VectorStore
            self.vector_store = VectorStore()
        return self.vector_store

    def _get_bm25_index(self):
        """Get BM25 index, returns None if unavailable."""
        if self.bm25_index is not None:
            return self.bm25_index

        try:
            from api.services.bm25_index import get_bm25_index
            return get_bm25_index()
        except Exception as e:
            logger.warning(f"BM25 index unavailable: {e}")
            return None

    def search(
        self,
        query: str,
        top_k: int = 20,
        apply_recency_boost: bool = True
    ) -> list[dict]:
        """
        Perform hybrid search combining vector and BM25.

        Args:
            query: Search query string
            top_k: Maximum number of results to return
            apply_recency_boost: Whether to apply recency boosting

        Returns:
            List of search results with metadata
        """
        # Get vector results
        vector_store = self._get_vector_store()
        vector_results = vector_store.search(query=query, top_k=top_k * 2)

        # Extract doc IDs and create lookup
        vector_doc_ids = []
        results_by_id = {}

        for result in vector_results:
            doc_id = result.get("id")
            if doc_id:
                vector_doc_ids.append(doc_id)
                results_by_id[doc_id] = result

        # Get BM25 results
        bm25_index = self._get_bm25_index()
        bm25_doc_ids = []

        if bm25_index:
            try:
                bm25_results = bm25_index.search(query, limit=top_k * 2)
                bm25_doc_ids = [r["doc_id"] for r in bm25_results]
            except Exception as e:
                logger.warning(f"BM25 search failed: {e}")

        # If no BM25 results, return vector results directly
        if not bm25_doc_ids:
            logger.debug("No BM25 results, using vector-only search")
            return vector_results[:top_k]

        # Apply RRF fusion
        fused = reciprocal_rank_fusion(vector_doc_ids, bm25_doc_ids)

        # Build final results with recency boost
        final_results = []

        for doc_id, rrf_score in fused[:top_k * 2]:
            # Get full result data
            if doc_id in results_by_id:
                result = results_by_id[doc_id].copy()
            else:
                # BM25-only result, need to fetch from vector store
                # For now, create minimal result
                result = {"id": doc_id, "content": "", "metadata": {}}

            # Apply recency boost
            if apply_recency_boost:
                date_str = result.get("metadata", {}).get("date")
                recency_boost = calculate_recency_boost(date_str)
                final_score = rrf_score * (1 + recency_boost)
            else:
                final_score = rrf_score

            result["hybrid_score"] = final_score
            result["rrf_score"] = rrf_score
            final_results.append(result)

        # Re-sort by final score and limit
        final_results.sort(key=lambda x: -x.get("hybrid_score", 0))

        return final_results[:top_k]


# Singleton instance
_hybrid_search_instance: Optional[HybridSearch] = None


def get_hybrid_search() -> HybridSearch:
    """Get the singleton HybridSearch instance."""
    global _hybrid_search_instance
    if _hybrid_search_instance is None:
        _hybrid_search_instance = HybridSearch()
    return _hybrid_search_instance
