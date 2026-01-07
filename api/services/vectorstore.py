"""
ChromaDB vector store service for LifeOS.

Handles storage and retrieval of document embeddings.
"""
import chromadb
from chromadb.config import Settings
from typing import Optional
import json

from api.services.embeddings import get_embedding_service


class VectorStore:
    """ChromaDB-backed vector store for document chunks."""

    def __init__(
        self,
        persist_directory: str = "./data/chromadb",
        collection_name: str = "lifeos_vault"
    ):
        """
        Initialize vector store.

        Args:
            persist_directory: Directory to persist ChromaDB data
            collection_name: Name of the collection
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name

        # Initialize ChromaDB client with persistence
        self._client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False)
        )

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

        # Get embedding service
        self._embedding_service = get_embedding_service()

    def add_document(
        self,
        chunks: list[dict],
        metadata: dict
    ) -> None:
        """
        Add document chunks to the store.

        Args:
            chunks: List of chunk dicts with 'content' and 'chunk_index'
            metadata: Document metadata (file_path, file_name, etc.)
        """
        if not chunks:
            return

        ids = []
        embeddings = []
        documents = []
        metadatas = []

        # Generate embeddings for all chunks
        contents = [c["content"] for c in chunks]
        chunk_embeddings = self._embedding_service.embed_texts(contents)

        for i, chunk in enumerate(chunks):
            # Create unique ID: file_path + chunk_index
            chunk_id = f"{metadata['file_path']}::{chunk['chunk_index']}"
            ids.append(chunk_id)

            embeddings.append(chunk_embeddings[i])
            documents.append(chunk["content"])

            # Prepare metadata - ChromaDB needs flat values
            chunk_meta = {
                "file_path": metadata["file_path"],
                "file_name": metadata["file_name"],
                "modified_date": metadata.get("modified_date", ""),
                "note_type": metadata.get("note_type", ""),
                "chunk_index": chunk["chunk_index"],
                # Store lists as JSON strings
                "people": json.dumps(metadata.get("people", [])),
                "tags": json.dumps(metadata.get("tags", []))
            }
            metadatas.append(chunk_meta)

        # Add to collection
        self._collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[dict] = None
    ) -> list[dict]:
        """
        Search for similar chunks.

        Args:
            query: Search query text
            top_k: Number of results to return
            filters: Optional metadata filters

        Returns:
            List of result dicts with content, metadata, and score
        """
        # Generate query embedding
        query_embedding = self._embedding_service.embed_text(query)

        # Build where clause for filters
        where = None
        if filters:
            where = {}
            for key, value in filters.items():
                if value is not None:
                    where[key] = value

        # Query collection
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where if where else None,
            include=["documents", "metadatas", "distances"]
        )

        # Format results
        formatted = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                result = {
                    "content": results["documents"][0][i],
                    "score": 1 - results["distances"][0][i],  # Convert distance to similarity
                    **results["metadatas"][0][i]
                }
                # Parse JSON fields
                if "people" in result and isinstance(result["people"], str):
                    try:
                        result["people"] = json.loads(result["people"])
                    except json.JSONDecodeError:
                        result["people"] = []
                if "tags" in result and isinstance(result["tags"], str):
                    try:
                        result["tags"] = json.loads(result["tags"])
                    except json.JSONDecodeError:
                        result["tags"] = []
                formatted.append(result)

        return formatted

    def delete_document(self, file_path: str) -> None:
        """
        Delete all chunks for a document.

        Args:
            file_path: Path of the document to delete
        """
        # Find all chunks with this file_path
        results = self._collection.get(
            where={"file_path": file_path},
            include=[]
        )

        if results["ids"]:
            self._collection.delete(ids=results["ids"])

    def update_document(
        self,
        chunks: list[dict],
        metadata: dict
    ) -> None:
        """
        Update a document by deleting old chunks and adding new ones.

        Args:
            chunks: New chunks
            metadata: Updated metadata
        """
        # Delete existing chunks
        self.delete_document(metadata["file_path"])
        # Add new chunks
        self.add_document(chunks, metadata)

    def get_document_count(self) -> int:
        """Get total number of chunks in the store."""
        return self._collection.count()

    def get_all_file_paths(self) -> set[str]:
        """Get set of all indexed file paths."""
        results = self._collection.get(include=["metadatas"])
        paths = set()
        if results["metadatas"]:
            for meta in results["metadatas"]:
                if meta and "file_path" in meta:
                    paths.add(meta["file_path"])
        return paths
