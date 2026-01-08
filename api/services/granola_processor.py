"""
Granola Inbox Processor for LifeOS.

Processes the Granola/ folder every 5 minutes, automatically
classifying and moving meeting notes to the appropriate folder.

Per PRD P0.1:
- Watches Granola/ folder for new/modified files
- Classifies by content patterns
- Moves to appropriate destination folder
- Updates frontmatter with proper tags
- Logs all moves with rationale
"""
import re
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

import frontmatter

logger = logging.getLogger(__name__)


# Classification patterns from PRD P0.1
CLASSIFICATION_RULES = [
    {
        "name": "therapy",
        "patterns": [
            r"\btherapy\b", r"\btherapist\b",
            r"\bAmy\s*Morgan\b", r"\bErica\s*Turner\b", r"\bErika\s*Turner\b",
            r"\bcouples\s*therapy\b", r"\bindividual\s*therapy\b"
        ],
        "destination": "Personal/Self-Improvement/Therapy and coaching",
        "tags": ["meeting", "therapy", "personal"]
    },
    {
        "name": "hiring",
        "patterns": [
            r"\binterview\b", r"\bhiring\b", r"\bjob\s*description\b",
            r"\bcandidate\b", r"\brecruit", r"\bresume\b", r"\bJD\b"
        ],
        "destination": "Work/ML/People/Hiring",
        "tags": ["meeting", "work", "ml", "hiring"]
    },
    {
        "name": "finance",
        "patterns": [
            r"\bbudget\b", r"\brevenue\b", r"\bfinance\b", r"\bfinancial\b",
            r"\bexpense", r"\bspending\b", r"\bmoney\s*meeting\b"
        ],
        "destination": "Work/ML/Finance",
        "tags": ["meeting", "work", "ml", "finance"]
    },
    {
        "name": "strategy",
        "patterns": [
            r"\bstrategy\b", r"\bplanning\b", r"\bgoals?\b", r"\bOKRs?\b",
            r"\broadmap\b", r"\bquarterly\s*planning\b"
        ],
        "destination": "Work/ML/Strategy and planning",
        "tags": ["meeting", "work", "ml", "strategy"]
    },
    {
        "name": "union",
        "patterns": [
            r"\bunion\b", r"\bsteward\b", r"\bcollective\s*bargaining\b",
            r"\bgrievance\b"
        ],
        "destination": "Work/ML/People/Union",
        "tags": ["meeting", "work", "ml"]
    },
    {
        "name": "personal_relationship",
        "patterns": [
            r"\bTaylor\b", r"\bMalea\b", r"\bMalia\b",
            r"\bfamily\b", r"\bpersonal\b", r"\brelationship\b"
        ],
        "destination": "Personal/Relationship",
        "tags": ["meeting", "personal", "relationship"]
    }
]

# Known ML people for 1-1 detection
ML_PEOPLE = [
    "Yoni", "Madi", "Madeline", "Hayley", "Kevin", "Brandon", "Tamara",
    "Peter", "Zoe", "Kellie", "Kelly", "Jay", "Josh", "Mike", "Tonya",
    "James", "Oscar", "Dane"
]


class GranolaProcessor:
    """
    Process meeting notes from Granola inbox folder.

    Runs every 5 minutes (configurable) to classify and move notes
    to appropriate destinations based on content patterns defined in the PRD.
    """

    def __init__(self, vault_path: str, interval_seconds: int = 300):
        """
        Initialize Granola processor.

        Args:
            vault_path: Path to Obsidian vault
            interval_seconds: How often to check for new files (default: 300 = 5 minutes)
        """
        self.vault_path = Path(vault_path)
        self.granola_path = self.vault_path / "Granola"
        self.interval_seconds = interval_seconds
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._lock = threading.Lock()

    def classify_note(self, content: str, filename: str) -> tuple[str, list[str], str]:
        """
        Classify a note based on content patterns.

        Args:
            content: Full note content
            filename: Name of the file

        Returns:
            Tuple of (destination_folder, tags, classification_rationale)
        """
        content_lower = content.lower()
        filename_lower = filename.lower()
        combined = content_lower + " " + filename_lower

        # Check each classification rule
        for rule in CLASSIFICATION_RULES:
            for pattern in rule["patterns"]:
                if re.search(pattern, combined, re.IGNORECASE):
                    rationale = f"Matched pattern '{pattern}' for category '{rule['name']}'"
                    return rule["destination"], rule["tags"], rationale

        # Check for 1-1 meetings with ML people
        for person in ML_PEOPLE:
            person_lower = person.lower()
            patterns = [
                rf"\b{person_lower}\b",
                rf"nathan.*{person_lower}",
                rf"{person_lower}.*nathan",
                rf"{person_lower}\s*x\s*nathan",
                rf"nathan\s*x\s*{person_lower}",
                rf"{person_lower}[-/]nathan",
                rf"nathan[-/]{person_lower}"
            ]
            for pattern in patterns:
                if re.search(pattern, filename_lower):
                    if "weekly" in filename_lower or "check" in filename_lower or \
                       re.search(rf"^{person_lower}.*nathan|nathan.*{person_lower}", filename_lower):
                        return (
                            "Work/ML/Meetings",
                            ["meeting", "work", "ml", "1-1"],
                            f"1-1 meeting with {person}"
                        )

        # Default: Work/ML/Meetings for any other meeting notes
        return (
            "Work/ML/Meetings",
            ["meeting", "work", "ml"],
            "Default classification - work meeting"
        )

    def extract_people(self, content: str) -> list[str]:
        """Extract people mentions from content."""
        people_found = []
        for person in ML_PEOPLE:
            if re.search(rf"\b{person}\b", content, re.IGNORECASE):
                people_found.append(person)
        return list(set(people_found))

    def update_frontmatter(
        self,
        content: str,
        tags: list[str],
        people: list[str]
    ) -> str:
        """
        Update frontmatter with proper LifeOS fields.

        Preserves Granola-specific fields (granola_id, granola_url, created_at, updated_at).
        Adds: created, modified, tags, type, people.
        """
        try:
            post = frontmatter.loads(content)
        except Exception:
            post = frontmatter.Post(content)

        # Extract created date from Granola's created_at field
        if "created_at" in post.metadata:
            created_at = post.metadata["created_at"]
            if isinstance(created_at, str):
                try:
                    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    post.metadata["created"] = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass
            elif isinstance(created_at, datetime):
                post.metadata["created"] = created_at.strftime("%Y-%m-%d")

        # Set modified date
        post.metadata["modified"] = datetime.now().strftime("%Y-%m-%d")

        # Merge tags (preserve existing, add new)
        existing_tags = post.metadata.get("tags", [])
        if isinstance(existing_tags, str):
            existing_tags = [existing_tags]
        merged_tags = list(set(existing_tags + tags))
        post.metadata["tags"] = merged_tags

        # Set type
        post.metadata["type"] = "meeting"

        # Add people
        existing_people = post.metadata.get("people", [])
        if isinstance(existing_people, str):
            existing_people = [existing_people]
        merged_people = list(set(existing_people + people))
        if merged_people:
            post.metadata["people"] = merged_people

        return frontmatter.dumps(post)

    def process_file(self, file_path: str) -> Optional[str]:
        """
        Process a single Granola file.

        Args:
            file_path: Path to the file

        Returns:
            New path if moved, None if skipped
        """
        path = Path(file_path)

        if not path.exists():
            logger.warning(f"File no longer exists: {file_path}")
            return None

        if not path.suffix == ".md":
            return None

        # Check if file is in Granola folder
        try:
            path.relative_to(self.granola_path)
        except ValueError:
            logger.debug(f"File not in Granola folder, skipping: {file_path}")
            return None

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return None

        # Classify the note
        destination, tags, rationale = self.classify_note(content, path.name)

        # Extract people
        people = self.extract_people(content)

        # Update frontmatter
        updated_content = self.update_frontmatter(content, tags, people)

        # Determine destination path
        dest_folder = self.vault_path / destination
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_path = dest_folder / path.name

        # Handle filename conflicts
        if dest_path.exists() and dest_path != path:
            base = dest_path.stem
            suffix = dest_path.suffix
            counter = 1
            while dest_path.exists():
                dest_path = dest_folder / f"{base}_{counter}{suffix}"
                counter += 1

        # Write updated content to destination
        try:
            dest_path.write_text(updated_content, encoding="utf-8")
            logger.info(f"Wrote updated content to: {dest_path}")
        except Exception as e:
            logger.error(f"Failed to write to {dest_path}: {e}")
            return None

        # Remove original file (if different from destination)
        if path != dest_path:
            try:
                path.unlink()
                logger.info(f"Removed original file: {path}")
            except Exception as e:
                logger.error(f"Failed to remove original {path}: {e}")

        logger.info(f"Processed: {path.name} -> {destination} ({rationale})")
        return str(dest_path)

    def process_backlog(self) -> dict:
        """
        Process all existing files in the Granola folder.

        Returns:
            Dict with 'processed', 'failed', 'skipped' counts and 'moves' list
        """
        results = {
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "moves": []
        }

        if not self.granola_path.exists():
            logger.warning(f"Granola folder does not exist: {self.granola_path}")
            return results

        for md_file in self.granola_path.glob("*.md"):
            try:
                new_path = self.process_file(str(md_file))
                if new_path:
                    results["processed"] += 1
                    results["moves"].append({
                        "original": str(md_file),
                        "destination": new_path
                    })
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.error(f"Failed to process {md_file}: {e}")
                results["failed"] += 1

        logger.info(
            f"Backlog processed: {results['processed']} moved, "
            f"{results['skipped']} skipped, {results['failed']} failed"
        )
        return results

    def _run_cycle(self):
        """Run one processing cycle and schedule the next."""
        if not self._running:
            return

        logger.debug("Running Granola processor cycle")
        try:
            results = self.process_backlog()
            if results["processed"] > 0:
                logger.info(f"Granola cycle: processed {results['processed']} files")
        except Exception as e:
            logger.error(f"Granola processor cycle failed: {e}")

        # Schedule next run
        if self._running:
            self._timer = threading.Timer(self.interval_seconds, self._run_cycle)
            self._timer.daemon = True
            self._timer.start()

    def start(self) -> None:
        """Start the processor (runs every interval_seconds)."""
        with self._lock:
            if self._running:
                logger.debug("Granola processor already running")
                return

            if not self.granola_path.exists():
                logger.warning(f"Granola folder does not exist: {self.granola_path}")
                return

            self._running = True

            # Run immediately on start
            logger.info(f"Starting Granola processor (interval: {self.interval_seconds}s)")
            self._run_cycle()

    # Alias for backward compatibility
    def start_watching(self) -> None:
        """Alias for start() for backward compatibility."""
        self.start()

    def stop(self) -> None:
        """Stop the processor."""
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
            logger.info("Stopped Granola processor")

    @property
    def is_running(self) -> bool:
        """Check if processor is running."""
        return self._running

    # Alias for backward compatibility
    @property
    def is_watching(self) -> bool:
        """Alias for is_running for backward compatibility."""
        return self._running


# Singleton instance
_processor_instance: Optional[GranolaProcessor] = None


def get_granola_processor(vault_path: str) -> GranolaProcessor:
    """Get or create the Granola processor singleton."""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = GranolaProcessor(vault_path)
    return _processor_instance
