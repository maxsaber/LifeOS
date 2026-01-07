"""
Indexer service for LifeOS.

Watches the Obsidian vault for file changes and indexes content to ChromaDB.
"""
import os
import time
import threading
import logging
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from api.services.chunker import chunk_document, extract_frontmatter
from api.services.vectorstore import VectorStore
from api.services.people import extract_people_from_text

logger = logging.getLogger(__name__)


class VaultEventHandler(FileSystemEventHandler):
    """Handle file system events in the vault."""

    def __init__(self, indexer: "IndexerService"):
        self.indexer = indexer
        self._debounce_timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _debounced_process(self, file_path: str, action: str):
        """Process file change with debouncing."""
        with self._lock:
            # Cancel existing timer for this file
            if file_path in self._debounce_timers:
                self._debounce_timers[file_path].cancel()

            # Create new timer
            def process():
                with self._lock:
                    self._debounce_timers.pop(file_path, None)
                if action == "delete":
                    self.indexer.delete_file(file_path)
                else:
                    self.indexer.index_file(file_path)

            timer = threading.Timer(1.0, process)  # 1 second debounce
            self._debounce_timers[file_path] = timer
            timer.start()

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith(".md"):
            logger.info(f"File created: {event.src_path}")
            self._debounced_process(event.src_path, "index")

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith(".md"):
            logger.info(f"File modified: {event.src_path}")
            self._debounced_process(event.src_path, "index")

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory and event.src_path.endswith(".md"):
            logger.info(f"File deleted: {event.src_path}")
            self._debounced_process(event.src_path, "delete")

    def on_moved(self, event: FileSystemEvent):
        if not event.is_directory:
            if hasattr(event, 'src_path') and event.src_path.endswith(".md"):
                logger.info(f"File moved from: {event.src_path}")
                self._debounced_process(event.src_path, "delete")
            if hasattr(event, 'dest_path') and event.dest_path.endswith(".md"):
                logger.info(f"File moved to: {event.dest_path}")
                self._debounced_process(event.dest_path, "index")


class IndexerService:
    """
    Main indexer service.

    Handles indexing of Obsidian vault files to ChromaDB.
    """

    def __init__(
        self,
        vault_path: str,
        db_path: str = "./data/chromadb"
    ):
        """
        Initialize indexer.

        Args:
            vault_path: Path to Obsidian vault
            db_path: Path to ChromaDB database
        """
        self.vault_path = Path(vault_path)
        self.db_path = Path(db_path)

        # Initialize vector store
        self.vector_store = VectorStore(persist_directory=str(db_path))

        # File watcher
        self._observer: Observer | None = None
        self._watching = False

    def index_all(self) -> int:
        """
        Index all markdown files in the vault.

        Returns:
            Number of files indexed
        """
        count = 0
        for md_file in self.vault_path.rglob("*.md"):
            try:
                self.index_file(str(md_file))
                count += 1
            except Exception as e:
                logger.error(f"Failed to index {md_file}: {e}")

        logger.info(f"Indexed {count} files")
        return count

    def index_file(self, file_path: str) -> None:
        """
        Index a single file.

        Args:
            file_path: Path to the file
        """
        path = Path(file_path)
        if not path.exists() or not path.suffix == ".md":
            return

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return

        # Extract frontmatter
        frontmatter, body = extract_frontmatter(content)

        # Determine if Granola note
        is_granola = (
            "granola_id" in frontmatter or
            "Granola" in str(path)
        )

        # Chunk the document
        chunks = chunk_document(content, is_granola=is_granola)

        # Extract people from content (in addition to frontmatter)
        extracted_people = extract_people_from_text(body)
        frontmatter_people = frontmatter.get("people", [])

        # Merge people lists (unique)
        all_people = list(set(extracted_people + frontmatter_people))

        # Build metadata - use resolve() to get real path (handles symlinks like /var -> /private/var)
        metadata = {
            "file_path": str(path.resolve()),
            "file_name": path.name,
            "modified_date": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            "note_type": self._infer_note_type(path),
            "people": all_people,
            "tags": frontmatter.get("tags", [])
        }

        # Update in vector store (handles deletion of old chunks)
        self.vector_store.update_document(chunks, metadata)
        logger.debug(f"Indexed {file_path} with {len(chunks)} chunks")

    def delete_file(self, file_path: str) -> None:
        """
        Remove a file from the index.

        Args:
            file_path: Path to the deleted file
        """
        # Use os.path.realpath to resolve symlinks (e.g., /var -> /private/var on macOS)
        # This works even for non-existent files
        real_path = os.path.realpath(file_path)
        self.vector_store.delete_document(real_path)
        logger.debug(f"Deleted {file_path} from index (resolved: {real_path})")

    def _infer_note_type(self, path: Path) -> str:
        """
        Infer note type from folder path.

        Args:
            path: Path to the file

        Returns:
            Note type string
        """
        path_str = str(path).lower()

        if "granola" in path_str:
            return "Granola"
        elif "personal" in path_str:
            return "Personal"
        elif "work" in path_str:
            return "Work"
        elif "lifeos" in path_str:
            return "LifeOS"
        else:
            return "Other"

    def start_watching(self) -> None:
        """Start watching the vault for changes."""
        if self._watching:
            return

        self._observer = Observer()
        event_handler = VaultEventHandler(self)
        self._observer.schedule(
            event_handler,
            str(self.vault_path),
            recursive=True
        )
        self._observer.start()
        self._watching = True
        logger.info(f"Started watching {self.vault_path}")

    def stop(self) -> None:
        """Stop watching and cleanup."""
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._watching = False
        logger.info("Stopped watching")

    @property
    def is_watching(self) -> bool:
        """Check if currently watching."""
        return self._watching
