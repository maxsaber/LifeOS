"""
BM25 Index for LifeOS.

Provides keyword-based search using SQLite FTS5.
"""
import sqlite3
import logging
from pathlib import Path
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


def get_bm25_db_path() -> str:
    """Get the path to the BM25 database."""
    db_dir = Path(settings.chroma_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "bm25_index.db")


class BM25Index:
    """
    SQLite FTS5-backed BM25 keyword index.

    Provides fast keyword search to complement vector similarity.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize BM25 index.

        Args:
            db_path: Path to SQLite database (default from settings)
        """
        self.db_path = db_path or get_bm25_db_path()
        self._init_db()

    def _init_db(self):
        """Create FTS5 table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Create FTS5 virtual table for full-text search
            # Using porter tokenizer for stemming
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    doc_id,
                    content,
                    file_name,
                    people,
                    tokenize='porter unicode61'
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def add_document(
        self,
        doc_id: str,
        content: str,
        file_name: str,
        people: Optional[list[str]] = None
    ):
        """
        Add or update a document in the index.

        Args:
            doc_id: Unique document identifier
            content: Document text content
            file_name: Source file name
            people: List of people mentioned
        """
        people_str = " ".join(people) if people else ""

        conn = sqlite3.connect(self.db_path)
        try:
            # Delete existing entry if present (for updates)
            conn.execute(
                "DELETE FROM chunks_fts WHERE doc_id = ?",
                (doc_id,)
            )
            # Insert new entry
            conn.execute(
                "INSERT INTO chunks_fts (doc_id, content, file_name, people) VALUES (?, ?, ?, ?)",
                (doc_id, content, file_name, people_str)
            )
            conn.commit()
        finally:
            conn.close()

    def delete_document(self, doc_id: str):
        """
        Remove a document from the index.

        Args:
            doc_id: Document identifier to remove
        """
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "DELETE FROM chunks_fts WHERE doc_id = ?",
                (doc_id,)
            )
            conn.commit()
        finally:
            conn.close()

    def search(
        self,
        query: str,
        limit: int = 20
    ) -> list[dict]:
        """
        Search the index using BM25.

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of matching documents with doc_id and BM25 score
        """
        if not query.strip():
            return []

        conn = sqlite3.connect(self.db_path)
        try:
            # FTS5 MATCH query with BM25 ranking
            # Search across content, file_name, and people
            cursor = conn.execute(
                """
                SELECT doc_id, bm25(chunks_fts) as score
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (query, limit)
            )

            results = []
            for row in cursor.fetchall():
                results.append({
                    "doc_id": row[0],
                    "bm25_score": row[1]  # Note: BM25 scores are negative, lower is better
                })

            return results

        except sqlite3.OperationalError as e:
            # Handle invalid FTS query syntax
            logger.warning(f"BM25 search error for query '{query}': {e}")
            return []
        finally:
            conn.close()

    def bulk_add(self, documents: list[dict]):
        """
        Add multiple documents efficiently.

        Args:
            documents: List of dicts with doc_id, content, file_name, people
        """
        conn = sqlite3.connect(self.db_path)
        try:
            for doc in documents:
                people_str = " ".join(doc.get("people", [])) if doc.get("people") else ""
                conn.execute(
                    "DELETE FROM chunks_fts WHERE doc_id = ?",
                    (doc["doc_id"],)
                )
                conn.execute(
                    "INSERT INTO chunks_fts (doc_id, content, file_name, people) VALUES (?, ?, ?, ?)",
                    (doc["doc_id"], doc["content"], doc["file_name"], people_str)
                )
            conn.commit()
        finally:
            conn.close()

    def clear(self):
        """Clear all documents from the index."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM chunks_fts")
            conn.commit()
        finally:
            conn.close()

    def count(self) -> int:
        """Get total number of documents in index."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM chunks_fts")
            return cursor.fetchone()[0]
        finally:
            conn.close()


# Singleton instance
_bm25_instance: Optional[BM25Index] = None


def get_bm25_index() -> BM25Index:
    """Get the singleton BM25Index instance."""
    global _bm25_instance
    if _bm25_instance is None:
        _bm25_instance = BM25Index()
    return _bm25_instance
