"""
Markdown parsing and chunking service for LifeOS.

Chunking strategies:
- Granola notes: by section headers + action items as separate chunks
- Long notes (>500 tokens): ~500 token chunks with 50 token overlap
- Short notes (<500 tokens): whole note as single chunk
"""
import re
from typing import Optional
import frontmatter
import tiktoken


# Use cl100k_base tokenizer (same as GPT-4/Claude)
try:
    TOKENIZER = tiktoken.get_encoding("cl100k_base")
except Exception:
    TOKENIZER = None


def count_tokens(text: str) -> int:
    """Count tokens in text using tiktoken."""
    if TOKENIZER is None:
        # Fallback: rough estimate of 4 chars per token
        return len(text) // 4
    return len(TOKENIZER.encode(text))


def extract_frontmatter(content: str) -> tuple[dict, str]:
    """
    Extract YAML frontmatter from markdown content.

    Returns:
        Tuple of (frontmatter_dict, body_content)
    """
    try:
        post = frontmatter.loads(content)
        return dict(post.metadata), post.content
    except Exception:
        return {}, content


def parse_markdown(content: str) -> list[dict]:
    """
    Parse markdown into sections by headers.

    Returns list of dicts with 'header', 'level', 'content' keys.
    """
    sections = []

    # Split by headers (# ## ### etc)
    header_pattern = r'^(#{1,6})\s+(.+)$'
    lines = content.split('\n')

    current_section = {
        "header": "",
        "level": 0,
        "content": ""
    }

    for line in lines:
        header_match = re.match(header_pattern, line)
        if header_match:
            # Save previous section if it has content
            if current_section["content"].strip():
                sections.append(current_section)

            # Start new section
            level = len(header_match.group(1))
            header = header_match.group(2).strip()
            current_section = {
                "header": header,
                "level": level,
                "content": line + "\n"
            }
        else:
            current_section["content"] += line + "\n"

    # Don't forget the last section
    if current_section["content"].strip():
        sections.append(current_section)

    return sections


def chunk_by_headers(content: str) -> list[dict]:
    """
    Chunk content by H2 headers (Granola-style).

    Each H2 section becomes its own chunk.
    Action items are extracted as separate chunks if present.
    """
    chunks = []
    sections = parse_markdown(content)

    for i, section in enumerate(sections):
        chunk_content = section["content"].strip()
        if not chunk_content:
            continue

        chunk = {
            "content": chunk_content,
            "header": section["header"],
            "chunk_index": len(chunks)
        }
        chunks.append(chunk)

    # If no chunks created, return whole content as single chunk
    if not chunks:
        chunks.append({
            "content": content.strip(),
            "header": "",
            "chunk_index": 0
        })

    return chunks


def chunk_by_tokens(
    content: str,
    chunk_size: int = 500,
    overlap: int = 50
) -> list[dict]:
    """
    Chunk content by token count with overlap.

    Args:
        content: Text to chunk
        chunk_size: Target tokens per chunk
        overlap: Token overlap between chunks

    Returns:
        List of chunk dicts with 'content' and 'chunk_index'
    """
    if not content.strip():
        return []

    # Simple word-based chunking (approximates tokens)
    words = content.split()

    # Estimate tokens per word (roughly 1.3 tokens per word)
    words_per_chunk = int(chunk_size / 1.3)
    overlap_words = int(overlap / 1.3)

    if len(words) <= words_per_chunk:
        return [{
            "content": content.strip(),
            "chunk_index": 0
        }]

    chunks = []
    start = 0

    while start < len(words):
        end = min(start + words_per_chunk, len(words))
        chunk_words = words[start:end]
        chunk_content = " ".join(chunk_words)

        chunks.append({
            "content": chunk_content,
            "chunk_index": len(chunks)
        })

        # Move start forward, accounting for overlap
        start = end - overlap_words
        if start >= len(words) - overlap_words:
            break

    return chunks


def chunk_document(
    content: str,
    is_granola: bool = False,
    chunk_size: int = 500,
    chunk_overlap: int = 50
) -> list[dict]:
    """
    Main chunking dispatcher.

    Determines chunking strategy based on document type and size:
    - Granola notes: chunk by headers
    - Long notes (>chunk_size tokens): chunk by tokens with overlap
    - Short notes: single chunk

    Args:
        content: Document content
        is_granola: Whether this is a Granola meeting note
        chunk_size: Target tokens per chunk (for long notes)
        chunk_overlap: Token overlap for long notes

    Returns:
        List of chunk dicts with 'content', 'chunk_index', and optionally 'header'
    """
    # Extract frontmatter first
    metadata, body = extract_frontmatter(content)

    # Check if Granola note (has granola_id in frontmatter or explicit flag)
    if is_granola or metadata.get("granola_id"):
        chunks = chunk_by_headers(body)
    else:
        # Check document length
        token_count = count_tokens(body)

        if token_count <= chunk_size:
            # Short note: single chunk
            chunks = [{
                "content": body.strip(),
                "chunk_index": 0
            }]
        else:
            # Long note: chunk by tokens
            chunks = chunk_by_tokens(body, chunk_size, chunk_overlap)

    # Ensure all chunks have chunk_index
    for i, chunk in enumerate(chunks):
        chunk["chunk_index"] = i

    return chunks
