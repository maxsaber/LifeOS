"""
Document summarization service using local LLM.

Generates brief summaries for document discovery and high-level search.
Uses Ollama with llama3.2:3b for zero-cost local summarization.

## Usage

    from api.services.summarizer import generate_summary
    summary = generate_summary(content, "Meeting Notes.md")

## How It Works

1. Truncates document to first 2000 chars
2. Sends to Ollama for summarization
3. Returns 1-2 sentence summary
4. Falls back to first content line if LLM fails
"""
import httpx
import logging
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """Summarize this document in 1-2 sentences. Focus on:
- What type of document it is (meeting notes, personal profile, project doc, etc.)
- Key topics, people, or decisions it covers
- Any important dates or deadlines mentioned

Document content:
{content}

Summary:"""


def generate_summary(
    content: str,
    file_name: str,
    max_content_chars: int = 2000,
    timeout: int = 10
) -> Optional[str]:
    """
    Generate a document summary using local LLM.

    Args:
        content: Document content to summarize
        file_name: Name of file (for logging)
        max_content_chars: Max chars to send to LLM
        timeout: Timeout in seconds for LLM call

    Returns:
        1-2 sentence summary, or None if generation fails
    """
    if len(content) < 100:
        # Too short to summarize meaningfully
        return None

    try:
        # Truncate content if needed
        truncated = content[:max_content_chars]
        if len(content) > max_content_chars:
            truncated += "\n[... content truncated ...]"

        prompt = SUMMARY_PROMPT.format(content=truncated)

        # Call Ollama synchronously
        url = f"{settings.ollama_host}/api/generate"
        payload = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,  # Low temperature for factual summary
                "num_predict": 150,  # Summary should be brief
            }
        }

        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            summary = data.get("response", "").strip()

        # Validate summary
        if len(summary) < 20 or len(summary) > 500:
            logger.warning(f"Invalid summary length for {file_name}: {len(summary)}")
            return _fallback_summary(content, file_name)

        logger.debug(f"Generated summary for {file_name}: {summary[:50]}...")
        return summary

    except httpx.TimeoutException as e:
        logger.warning(f"Ollama timeout for {file_name}: {e}")
        return _fallback_summary(content, file_name)
    except httpx.ConnectError as e:
        logger.warning(f"Ollama connection failed for {file_name}: {e}")
        return _fallback_summary(content, file_name)
    except Exception as e:
        logger.warning(f"Summary generation failed for {file_name}: {e}")
        return _fallback_summary(content, file_name)


def _fallback_summary(content: str, file_name: str) -> str:
    """Generate fallback summary from first content lines."""
    # Extract first meaningful line (skip frontmatter, headers)
    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        # Skip empty lines, frontmatter markers, and headers
        if line and not line.startswith('#') and not line.startswith('---'):
            if len(line) > 20:
                # Clean up the line and truncate
                clean_line = line[:150]
                if len(line) > 150:
                    clean_line += "..."
                return f"Document '{file_name}': {clean_line}"

    return f"Document '{file_name}' containing various notes."


def is_ollama_available() -> bool:
    """Check if Ollama server is available for summarization."""
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(settings.ollama_host)
            return response.status_code == 200
    except Exception:
        return False


def create_summary_chunk(
    summary: str,
    file_path: str,
    file_name: str,
    metadata: dict
) -> dict:
    """
    Create a summary chunk for indexing.

    Args:
        summary: Generated summary text
        file_path: Full path to the document
        file_name: Name of the file
        metadata: Document metadata

    Returns:
        Chunk dict ready for indexing
    """
    return {
        "content": f"Document summary for {file_name}: {summary}",
        "chunk_index": -1,  # Special index for summary
        "is_summary": True,
        "file_path": file_path,
        "file_name": file_name,
        "metadata": {
            **metadata,
            "is_summary": True,
            "chunk_type": "summary"
        }
    }
