# Query-Aware Reranker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable cross-encoder reranking that preserves exact BM25 matches for factual queries while applying reranking to semantic queries.

**Architecture:** Add query type detection to classify queries as "factual" (exact lookups) or "semantic" (discovery). For factual queries, protect top BM25 exact matches from being displaced by reranking. This allows the cross-encoder to improve semantic queries without hurting factual lookups.

**Tech Stack:** Python, pytest, SQLite FTS5, sentence-transformers CrossEncoder

---

## Problem Statement

The cross-encoder reranker is valuable for semantic queries ("prepare me for meeting with Sarah") but **hurts factual queries** ("Taylor's KTN") by pushing exact BM25 keyword matches out of top results.

### Evidence

- Query: "Taylor's KTN"
- BM25 alone: Taylor.md #1 (correct)
- Hybrid without reranker: Taylor.md #1 (correct)
- Hybrid WITH reranker: Taylor.md pushed out of top 5 (wrong)

### Root Cause

Cross-encoders optimize for semantic relevance, not exact keyword matching. When a query contains a specific code/identifier (KTN, phone, passport), the cross-encoder doesn't understand that BM25's exact match should be preserved.

---

## Solution Design

### Query Types

| Type | Signals | Example | Reranker Behavior |
|------|---------|---------|-------------------|
| **Factual** | Possessives, proper nouns, codes/IDs, "what is X" | "Taylor's KTN", "Alex's phone" | Protect top 3 BM25 matches |
| **Semantic** | Concepts, verbs, discovery words | "prepare me for meeting", "what files mention budget" | Full reranking |

### Detection Heuristics

**Factual indicators (any match = factual):**
1. Possessive pattern: `'s` or `s'` with proper noun
2. Query contains person name from ALIAS_MAP
3. Identifier keywords: passport, KTN, SSN, phone, email, address, birthday
4. "What is [person]'s" pattern
5. Short query (< 5 words) with proper noun

**Semantic indicators (none of above = semantic):**
1. Action verbs: prepare, summarize, brief, analyze
2. Discovery words: files, documents, about, regarding, related
3. Longer queries (> 8 words)

### Protected Reranking Algorithm

```
For factual queries:
  1. Get hybrid results (top 50 candidates)
  2. Identify "protected" results: top 3 where content contains query keywords
  3. Apply cross-encoder to remaining candidates
  4. Merge: protected first, then reranked
  5. Return top_k

For semantic queries:
  1. Get hybrid results (top 50 candidates)
  2. Apply cross-encoder to all candidates
  3. Return top_k
```

---

## Task 1: Query Classifier

**Files:**
- Create: `api/services/query_classifier.py`
- Test: `tests/test_query_classifier.py`

### Step 1: Write the failing tests

```python
# tests/test_query_classifier.py
"""Tests for query type classification."""
import pytest

pytestmark = pytest.mark.unit


class TestQueryClassifier:
    """Test query type detection."""

    def test_possessive_with_identifier_is_factual(self):
        """Possessive + identifier keyword = factual."""
        from api.services.query_classifier import classify_query

        assert classify_query("Taylor's KTN") == "factual"
        assert classify_query("Alex's phone number") == "factual"
        assert classify_query("What is John's passport?") == "factual"

    def test_possessive_with_person_name_is_factual(self):
        """Possessive with known person name = factual."""
        from api.services.query_classifier import classify_query

        # Uses ALIAS_MAP to detect known names
        assert classify_query("Taylor's birthday") == "factual"
        assert classify_query("What is Alex's email?") == "factual"

    def test_discovery_queries_are_semantic(self):
        """Discovery and preparation queries = semantic."""
        from api.services.query_classifier import classify_query

        assert classify_query("prepare me for meeting with Sarah") == "semantic"
        assert classify_query("what files discuss the Q4 budget") == "semantic"
        assert classify_query("summarize my notes about the project") == "semantic"

    def test_action_verbs_are_semantic(self):
        """Action verbs indicate semantic queries."""
        from api.services.query_classifier import classify_query

        assert classify_query("brief me on the Johnson account") == "semantic"
        assert classify_query("analyze the sales trends") == "semantic"

    def test_short_lookup_is_factual(self):
        """Short queries with proper nouns = factual."""
        from api.services.query_classifier import classify_query

        assert classify_query("Taylor birthday") == "factual"
        assert classify_query("Alex phone") == "factual"

    def test_complex_semantic_query(self):
        """Long conceptual queries = semantic."""
        from api.services.query_classifier import classify_query

        result = classify_query(
            "what are the key takeaways from our strategic planning session"
        )
        assert result == "semantic"

    def test_identifier_keywords_are_factual(self):
        """Queries with identifier keywords = factual."""
        from api.services.query_classifier import classify_query

        assert classify_query("passport number") == "factual"
        assert classify_query("SSN") == "factual"
        assert classify_query("phone number") == "factual"
        assert classify_query("email address") == "factual"
```

### Step 2: Run tests to verify they fail

```bash
uv run pytest tests/test_query_classifier.py -v
```

Expected: `ModuleNotFoundError: No module named 'api.services.query_classifier'`

### Step 3: Implement the query classifier

```python
# api/services/query_classifier.py
"""
Query type classifier for LifeOS.

Detects whether a query is "factual" (exact lookup) or "semantic" (discovery/conceptual).
Used by hybrid search to determine reranking strategy.

## Query Types

- **Factual**: Exact lookups (person's info, codes, IDs)
  - Reranker protects top BM25 matches
  - Examples: "Taylor's KTN", "Alex's phone"

- **Semantic**: Discovery and conceptual queries
  - Full cross-encoder reranking
  - Examples: "prepare me for meeting", "what files discuss budget"
"""
import re
import logging
from typing import Literal

logger = logging.getLogger(__name__)

# Keywords that indicate factual/identifier lookups
IDENTIFIER_KEYWORDS = {
    "passport", "ktn", "ssn", "phone", "email", "address",
    "birthday", "number", "id", "code", "pin", "account"
}

# Action verbs that indicate semantic queries
ACTION_VERBS = {
    "prepare", "summarize", "brief", "analyze", "review",
    "explain", "describe", "tell", "help", "find", "show"
}

# Discovery words that indicate semantic queries
DISCOVERY_WORDS = {
    "files", "documents", "notes", "about", "regarding",
    "related", "discuss", "mention", "contain", "cover"
}


def classify_query(query: str) -> Literal["factual", "semantic"]:
    """
    Classify a query as factual or semantic.

    Args:
        query: Search query string

    Returns:
        "factual" for exact lookups, "semantic" for discovery queries
    """
    query_lower = query.lower()
    words = query_lower.split()

    # Check for possessive patterns with proper nouns
    possessive_pattern = r"(\w+)'s\s+(\w+)"
    possessive_match = re.search(possessive_pattern, query_lower)

    if possessive_match:
        # Check if followed by identifier keyword
        following_word = possessive_match.group(2)
        if following_word in IDENTIFIER_KEYWORDS:
            logger.debug(f"Factual: possessive + identifier '{following_word}'")
            return "factual"

        # Check if the name is known (from ALIAS_MAP)
        try:
            from api.services.people import ALIAS_MAP
            name = possessive_match.group(1)
            if name in ALIAS_MAP or name.capitalize() in ALIAS_MAP:
                logger.debug(f"Factual: known person '{name}'")
                return "factual"
        except ImportError:
            pass

    # Check for known person names anywhere in query
    try:
        from api.services.people import ALIAS_MAP
        for word in words:
            clean = re.sub(r"[''`]s?$", "", word)  # Remove possessive
            if clean in ALIAS_MAP or clean.capitalize() in ALIAS_MAP:
                # Short query with known name = factual
                if len(words) <= 5:
                    logger.debug(f"Factual: short query with known name '{clean}'")
                    return "factual"
    except ImportError:
        pass

    # Check for identifier keywords
    if any(kw in words for kw in IDENTIFIER_KEYWORDS):
        # Short query with identifier = factual
        if len(words) <= 5:
            logger.debug(f"Factual: identifier keyword in short query")
            return "factual"

    # Check for action verbs (semantic indicators)
    if any(verb in words for verb in ACTION_VERBS):
        logger.debug(f"Semantic: action verb detected")
        return "semantic"

    # Check for discovery words (semantic indicators)
    if any(word in words for word in DISCOVERY_WORDS):
        logger.debug(f"Semantic: discovery word detected")
        return "semantic"

    # Long queries tend to be semantic
    if len(words) > 8:
        logger.debug(f"Semantic: long query ({len(words)} words)")
        return "semantic"

    # Default: short/medium queries without clear signals = factual
    # (better to preserve exact matches when unsure)
    logger.debug(f"Factual: default for ambiguous query")
    return "factual"
```

### Step 4: Run tests to verify they pass

```bash
uv run pytest tests/test_query_classifier.py -v
```

Expected: All 7 tests PASS

### Step 5: Commit

```bash
git add api/services/query_classifier.py tests/test_query_classifier.py
git commit -m "feat: add query classifier for factual vs semantic detection

Classifies queries to determine reranking strategy:
- Factual: possessives, person names, identifier keywords
- Semantic: action verbs, discovery words, long queries

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Protected Reranking

**Files:**
- Modify: `api/services/reranker.py`
- Test: `tests/test_reranker.py` (add new tests)

### Step 1: Write the failing tests

Add to `tests/test_reranker.py`:

```python
class TestProtectedReranking:
    """Test protected reranking for factual queries."""

    def test_rerank_with_protected_indices(self):
        """Should preserve results at protected indices."""
        from api.services.reranker import RerankerService

        reranker = RerankerService()

        results = [
            {"id": "exact_match", "content": "Taylor's KTN: TT11YZS7J", "hybrid_score": 0.9},
            {"id": "semantic_1", "content": "General travel information", "hybrid_score": 0.8},
            {"id": "semantic_2", "content": "Passport and visa requirements", "hybrid_score": 0.7},
            {"id": "semantic_3", "content": "Airport security guidelines", "hybrid_score": 0.6},
        ]

        # Protect index 0 (the exact match)
        reranked = reranker.rerank(
            query="Taylor's KTN",
            results=results,
            top_k=3,
            protected_indices=[0]
        )

        # Protected result should be first
        assert reranked[0]["id"] == "exact_match"
        assert len(reranked) == 3

    def test_rerank_protected_multiple(self):
        """Should preserve multiple protected results in order."""
        from api.services.reranker import RerankerService

        reranker = RerankerService()

        results = [
            {"id": "match_1", "content": "Alex phone: 555-1234", "hybrid_score": 0.9},
            {"id": "match_2", "content": "Alex email: alex@example.com", "hybrid_score": 0.85},
            {"id": "unrelated_1", "content": "Random content", "hybrid_score": 0.8},
            {"id": "unrelated_2", "content": "More random content", "hybrid_score": 0.7},
        ]

        reranked = reranker.rerank(
            query="Alex contact info",
            results=results,
            top_k=3,
            protected_indices=[0, 1]
        )

        # First two should be protected results in order
        assert reranked[0]["id"] == "match_1"
        assert reranked[1]["id"] == "match_2"
        assert len(reranked) == 3

    def test_rerank_no_protection_full_rerank(self):
        """Without protection, should fully rerank."""
        from api.services.reranker import RerankerService

        reranker = RerankerService()

        results = [
            {"id": "doc1", "content": "Budget overview", "hybrid_score": 0.9},
            {"id": "doc2", "content": "Financial planning details", "hybrid_score": 0.8},
        ]

        # No protected_indices = full rerank
        reranked = reranker.rerank(
            query="test",
            results=results,
            top_k=2
        )

        # Should work normally
        assert len(reranked) == 2
```

### Step 2: Run tests to verify they fail

```bash
uv run pytest tests/test_reranker.py::TestProtectedReranking -v
```

Expected: `TypeError: rerank() got an unexpected keyword argument 'protected_indices'`

### Step 3: Modify reranker to support protected indices

Update `api/services/reranker.py`:

```python
def rerank(
    self,
    query: str,
    results: list[dict],
    top_k: int = 10,
    content_key: str = "content",
    protected_indices: list[int] | None = None
) -> list[dict]:
    """
    Re-rank search results using cross-encoder.

    Args:
        query: Search query string
        results: List of search results with content
        top_k: Number of results to return after re-ranking
        content_key: Key in result dict containing text to score
        protected_indices: Indices of results to protect from reranking.
                          These results will appear first in their original order,
                          followed by reranked remaining results.

    Returns:
        Re-ranked results with cross_encoder_score added
    """
    if not results:
        return []

    # Handle protected indices
    protected_results = []
    unprotected_results = []

    if protected_indices:
        protected_set = set(protected_indices)
        for i, result in enumerate(results):
            if i in protected_set:
                result["cross_encoder_score"] = result.get("hybrid_score", 1.0)
                result["protected"] = True
                protected_results.append(result)
            else:
                unprotected_results.append(result)
    else:
        unprotected_results = results

    # If not enough unprotected results to rerank meaningfully
    if len(unprotected_results) <= max(0, top_k - len(protected_results)):
        for r in unprotected_results:
            r["cross_encoder_score"] = r.get("hybrid_score", 0.5)
        return (protected_results + unprotected_results)[:top_k]

    model = self._get_model()

    # Prepare query-document pairs for unprotected results
    pairs = [(query, r.get(content_key, "")) for r in unprotected_results]

    # Score all pairs
    try:
        scores = model.predict(pairs, show_progress_bar=False)
    except Exception as e:
        logger.error(f"Cross-encoder scoring failed: {e}")
        for r in unprotected_results:
            r["cross_encoder_score"] = r.get("hybrid_score", 0.5)
        return (protected_results + unprotected_results)[:top_k]

    # Add scores to unprotected results
    for result, score in zip(unprotected_results, scores):
        result["cross_encoder_score"] = float(score)

    # Sort unprotected by cross-encoder score (descending)
    reranked_unprotected = sorted(
        unprotected_results,
        key=lambda x: -x["cross_encoder_score"]
    )

    # Combine: protected first, then reranked unprotected
    final_results = protected_results + reranked_unprotected

    logger.debug(
        f"Reranked {len(unprotected_results)} results, "
        f"protected {len(protected_results)}, "
        f"top score: {final_results[0]['cross_encoder_score']:.3f}"
    )

    return final_results[:top_k]
```

### Step 4: Run tests to verify they pass

```bash
uv run pytest tests/test_reranker.py -v
```

Expected: All tests PASS

### Step 5: Commit

```bash
git add api/services/reranker.py tests/test_reranker.py
git commit -m "feat: add protected indices to reranker

Allows protecting specific results from being displaced by reranking.
Protected results appear first in their original order.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Integrate Query-Aware Reranking into Hybrid Search

**Files:**
- Modify: `api/services/hybrid_search.py`
- Modify: `config/settings.py` (re-enable reranker)
- Test: `tests/test_hybrid_search.py` (add new tests)

### Step 1: Write the failing tests

Add to `tests/test_hybrid_search.py`:

```python
class TestQueryAwareReranking:
    """Test query-aware reranking in hybrid search."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database file."""
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            yield f.name
        os.unlink(f.name)

    def test_factual_query_preserves_bm25_matches(self, temp_db):
        """Factual queries should preserve top BM25 exact matches."""
        from api.services.hybrid_search import HybridSearch, find_protected_indices
        from api.services.bm25_index import BM25Index
        from unittest.mock import MagicMock

        bm25 = BM25Index(db_path=temp_db)
        bm25.add_document("taylor_ktn", "Taylor's KTN: TT11YZS7J", "Taylor.md")
        bm25.add_document("travel_1", "General travel tips", "Travel.md")
        bm25.add_document("travel_2", "Airport information", "Airport.md")

        mock_vector_store = MagicMock()
        mock_vector_store.search.return_value = [
            {"id": "travel_1", "content": "General travel tips", "metadata": {}},
            {"id": "travel_2", "content": "Airport information", "metadata": {}},
            {"id": "taylor_ktn", "content": "Taylor's KTN: TT11YZS7J", "metadata": {}},
        ]

        hybrid = HybridSearch(vector_store=mock_vector_store, bm25_index=bm25)

        # find_protected_indices should identify Taylor.md for factual query
        results = [
            {"id": "taylor_ktn", "content": "Taylor's KTN: TT11YZS7J"},
            {"id": "travel_1", "content": "General travel tips"},
        ]
        protected = find_protected_indices("Taylor's KTN", results, max_protected=3)

        # Should protect the exact match
        assert 0 in protected

    def test_semantic_query_no_protection(self, temp_db):
        """Semantic queries should not protect any results."""
        from api.services.hybrid_search import find_protected_indices

        results = [
            {"id": "doc1", "content": "Meeting with Sarah about project"},
            {"id": "doc2", "content": "Sarah's feedback on design"},
        ]

        protected = find_protected_indices(
            "prepare me for meeting with Sarah",
            results,
            max_protected=3
        )

        # Semantic query = no protection
        assert len(protected) == 0

    def test_find_protected_indices_checks_content(self, temp_db):
        """Should only protect results that contain query keywords."""
        from api.services.hybrid_search import find_protected_indices

        results = [
            {"id": "doc1", "content": "Random unrelated content"},
            {"id": "doc2", "content": "Alex's phone: 555-1234"},
            {"id": "doc3", "content": "More unrelated stuff"},
        ]

        protected = find_protected_indices("Alex's phone", results, max_protected=3)

        # Should only protect doc2 (contains "Alex" and "phone")
        assert 1 in protected
        assert 0 not in protected
        assert 2 not in protected
```

### Step 2: Run tests to verify they fail

```bash
uv run pytest tests/test_hybrid_search.py::TestQueryAwareReranking -v
```

Expected: `ImportError: cannot import name 'find_protected_indices' from 'api.services.hybrid_search'`

### Step 3: Implement find_protected_indices and update hybrid search

Add to `api/services/hybrid_search.py` (after imports):

```python
from api.services.query_classifier import classify_query


def find_protected_indices(
    query: str,
    results: list[dict],
    max_protected: int = 3
) -> list[int]:
    """
    Find indices of results to protect from reranking.

    For factual queries, protects top results that contain query keywords.
    For semantic queries, returns empty list (no protection).

    Args:
        query: Search query string
        results: Hybrid search results
        max_protected: Maximum number of results to protect

    Returns:
        List of indices to protect (may be empty)
    """
    query_type = classify_query(query)

    if query_type == "semantic":
        return []

    # Factual query: find results containing query keywords
    query_lower = query.lower()

    # Extract significant keywords (skip common words)
    stop_words = {"what", "is", "the", "a", "an", "of", "for", "to", "'s", "s"}
    keywords = []
    for word in query_lower.split():
        clean = re.sub(r"[''`]s?$", "", word)  # Remove possessive
        clean = re.sub(r"[^a-z0-9]", "", clean)  # Remove punctuation
        if clean and clean not in stop_words and len(clean) >= 2:
            keywords.append(clean)

    if not keywords:
        return []

    protected = []
    for i, result in enumerate(results):
        if len(protected) >= max_protected:
            break

        content = result.get("content", "").lower()

        # Check if content contains any significant keyword
        matches = sum(1 for kw in keywords if kw in content)
        if matches >= 1:  # At least one keyword match
            protected.append(i)

    return protected
```

Update the `search` method in `HybridSearch` class to use protected reranking:

```python
# Replace the reranking section (lines 438-454) with:

# Apply cross-encoder re-ranking if enabled and we have enough candidates
if use_reranker and len(final_results) > top_k:
    try:
        from api.services.reranker import get_reranker

        # Find protected indices for factual queries
        protected = find_protected_indices(
            expanded_query,
            final_results,
            max_protected=3
        )

        reranker = get_reranker()
        final_results = reranker.rerank(
            query=expanded_query,
            results=final_results,
            top_k=top_k,
            content_key="content",
            protected_indices=protected if protected else None
        )

        if protected:
            logger.debug(f"Protected {len(protected)} results from reranking")
        logger.debug(f"Re-ranked {len(final_results)} results with cross-encoder")
    except Exception as e:
        logger.warning(f"Re-ranking failed, using hybrid scores: {e}")
        final_results = final_results[:top_k]
else:
    final_results = final_results[:top_k]
```

### Step 4: Re-enable reranker in settings

Update `config/settings.py`:

```python
# Cross-encoder re-ranking (P9.2)
# Query-aware reranking: protects BM25 exact matches for factual queries
reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
reranker_enabled: bool = True  # Re-enabled with query-aware protection
reranker_candidates: int = 50
```

### Step 5: Run tests to verify they pass

```bash
uv run pytest tests/test_hybrid_search.py::TestQueryAwareReranking -v
uv run pytest tests/test_query_classifier.py -v
uv run pytest tests/test_reranker.py -v
```

Expected: All tests PASS

### Step 6: Commit

```bash
git add api/services/hybrid_search.py config/settings.py tests/test_hybrid_search.py
git commit -m "feat: integrate query-aware reranking into hybrid search

- Add find_protected_indices() to identify BM25 matches to protect
- For factual queries: protect top 3 results containing query keywords
- For semantic queries: apply full cross-encoder reranking
- Re-enable reranker with query-aware protection

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Update Integration Tests

**Files:**
- Modify: `tests/test_phase9_integration.py`

### Step 1: Update reranker settings test

```python
def test_reranker_settings(self):
    """Verify reranker settings are configured."""
    from config.settings import settings

    assert settings.reranker_model == "cross-encoder/ms-marco-MiniLM-L6-v2"
    # Reranker re-enabled with query-aware protection
    assert settings.reranker_enabled is True
    assert settings.reranker_candidates == 50
```

### Step 2: Add query classifier integration test

```python
def test_query_classifier_integration(self):
    """Verify query classifier works with hybrid search."""
    from api.services.query_classifier import classify_query
    from api.services.hybrid_search import find_protected_indices

    # Factual query should be classified correctly
    assert classify_query("Taylor's KTN") == "factual"

    # And should result in protection
    results = [{"content": "Taylor's KTN: TT11YZS7J"}]
    protected = find_protected_indices("Taylor's KTN", results)
    assert len(protected) > 0
```

### Step 3: Run integration tests

```bash
uv run pytest tests/test_phase9_integration.py -v
```

### Step 4: Commit

```bash
git add tests/test_phase9_integration.py
git commit -m "test: update Phase 9 integration tests for query-aware reranking

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Full Vault Reindex and Browser Validation

### Step 1: Restart server to pick up changes

```bash
./scripts/server.sh restart
```

### Step 2: Test via API

```bash
# Factual query - should find Taylor's KTN
curl -s -X POST "http://localhost:8000/api/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "Taylor'\''s KTN", "top_k": 5}' | \
  python3 -c "import sys,json; r=json.load(sys.stdin)['results']; print(f'Top result: {r[0][\"file_name\"]}'); print(f'Has KTN: {\"KTN\" in r[0][\"content\"]}')"
```

Expected:
```
Top result: Taylor.md
Has KTN: True
```

```bash
# Semantic query - should work normally
curl -s -X POST "http://localhost:8000/api/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "prepare me for meeting with Sarah", "top_k": 5}' | \
  python3 -c "import sys,json; r=json.load(sys.stdin)['results']; print(f'Found {len(r)} results')"
```

### Step 3: Browser validation

Open Chrome and navigate to `http://localhost:8000`

**Test 1: Factual Query**
- Enter: "What is Taylor's KTN?"
- Expected: Response includes "TT11YZS7J" from Taylor.md

**Test 2: Semantic Query**
- Enter: "Prepare me for meeting with Sarah"
- Expected: Synthesized briefing from multiple sources

**Test 3: Another Factual Query**
- Enter: "Alex's phone number"
- Expected: Returns Alex's actual phone number

### Step 4: Final commit

```bash
git add .
git commit -m "feat: complete query-aware reranking implementation

Phase 9.2 enhancement complete:
- Query classifier detects factual vs semantic queries
- Protected reranking preserves BM25 exact matches for factual queries
- Cross-encoder improves semantic query ranking
- Verified via browser: Taylor's KTN, Alex's phone, meeting prep

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary of Changes

| File | Changes |
|------|---------|
| `api/services/query_classifier.py` | NEW - Query type detection |
| `api/services/reranker.py` | Add `protected_indices` parameter |
| `api/services/hybrid_search.py` | Add `find_protected_indices()`, integrate query-aware reranking |
| `config/settings.py` | Re-enable `reranker_enabled = True` |
| `tests/test_query_classifier.py` | NEW - 7 unit tests |
| `tests/test_reranker.py` | Add 3 tests for protected reranking |
| `tests/test_hybrid_search.py` | Add 3 tests for query-aware reranking |
| `tests/test_phase9_integration.py` | Update for re-enabled reranker |

---

## Validation Checklist

Before marking complete, verify:

- [ ] `uv run pytest tests/test_query_classifier.py -v` - all pass
- [ ] `uv run pytest tests/test_reranker.py -v` - all pass
- [ ] `uv run pytest tests/test_hybrid_search.py -v` - all pass
- [ ] `uv run pytest tests/test_phase9_integration.py -v` - all pass
- [ ] API test: "Taylor's KTN" returns Taylor.md with KTN value
- [ ] API test: "Alex's phone" returns correct phone number
- [ ] Browser test: Factual queries return exact matches
- [ ] Browser test: Semantic queries return synthesized content
