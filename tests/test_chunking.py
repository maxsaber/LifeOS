"""
Tests for markdown parsing and chunking logic.
P1.1 Acceptance Criteria:
- Granola notes are chunked by section headers
- Long notes are chunked with overlap
- Short notes stored as single chunk
"""
import pytest

# All tests in this file are fast unit tests
pytestmark = pytest.mark.unit
from api.services.chunker import (
    parse_markdown,
    chunk_by_headers,
    chunk_by_tokens,
    chunk_document,
    extract_frontmatter,
)


class TestFrontmatterExtraction:
    """Test YAML frontmatter extraction."""

    def test_extracts_frontmatter_fields(self):
        """Should extract tags, type, and people from frontmatter."""
        content = """---
created: 2025-01-05
tags: [meeting, work, ml]
type: meeting
people: [Yoni, Madi]
---

# Meeting Notes
Some content here.
"""
        frontmatter, body = extract_frontmatter(content)
        assert frontmatter["tags"] == ["meeting", "work", "ml"]
        assert frontmatter["type"] == "meeting"
        assert frontmatter["people"] == ["Yoni", "Madi"]
        assert "# Meeting Notes" in body

    def test_handles_missing_frontmatter(self):
        """Should return empty dict if no frontmatter."""
        content = "# Just a Title\n\nSome content."
        frontmatter, body = extract_frontmatter(content)
        assert frontmatter == {}
        assert "# Just a Title" in body

    def test_handles_empty_frontmatter(self):
        """Should return empty dict for empty frontmatter."""
        content = """---
---
# Title
Content."""
        frontmatter, body = extract_frontmatter(content)
        assert frontmatter == {}


class TestParseMarkdown:
    """Test markdown parsing."""

    def test_parses_headers_and_content(self):
        """Should correctly identify headers and their content."""
        content = """# Main Title

Introduction paragraph.

## Section One

Content for section one.

## Section Two

Content for section two.
"""
        sections = parse_markdown(content)
        assert len(sections) >= 3
        assert any("Main Title" in s["header"] for s in sections)
        assert any("Section One" in s["header"] for s in sections)

    def test_handles_nested_headers(self):
        """Should handle nested header levels."""
        content = """# H1

## H2

### H3

Content under H3.
"""
        sections = parse_markdown(content)
        assert len(sections) >= 3


class TestChunkByHeaders:
    """Test Granola-style chunking by headers."""

    def test_chunks_by_h2_headers(self):
        """Should create separate chunks for each H2 section."""
        content = """# Meeting Title

## Attendees
- Yoni
- Nathan

## Agenda
1. Budget review
2. Q1 planning

## Action Items
- [ ] Nathan: Send budget proposal
- [ ] Yoni: Review Q1 targets
"""
        chunks = chunk_by_headers(content)
        # Should have chunks for: intro, Attendees, Agenda, Action Items
        assert len(chunks) >= 3

        # Action items should be in their own chunk
        action_chunk = [c for c in chunks if "Action Items" in c["content"]]
        assert len(action_chunk) >= 1
        assert "budget proposal" in action_chunk[0]["content"].lower()

    def test_includes_header_in_chunk(self):
        """Each chunk should include its header for context."""
        content = """## Important Section

This is the content.
"""
        chunks = chunk_by_headers(content)
        assert any("Important Section" in c["content"] for c in chunks)


class TestChunkByTokens:
    """Test token-based chunking for long notes."""

    def test_respects_chunk_size(self):
        """Chunks should not exceed max token size significantly."""
        # Create content with ~1000 words (roughly 1000+ tokens)
        long_content = "This is a test sentence. " * 200
        chunks = chunk_by_tokens(long_content, chunk_size=500, overlap=50)

        # Should create multiple chunks
        assert len(chunks) >= 2

    def test_maintains_overlap(self):
        """Adjacent chunks should have overlapping content."""
        long_content = " ".join([f"Word{i}" for i in range(200)])
        chunks = chunk_by_tokens(long_content, chunk_size=100, overlap=20)

        if len(chunks) >= 2:
            # Check for some overlap between consecutive chunks
            chunk1_end = chunks[0]["content"].split()[-20:]
            chunk2_start = chunks[1]["content"].split()[:20]
            # There should be some common words
            overlap = set(chunk1_end) & set(chunk2_start)
            assert len(overlap) > 0

    def test_single_chunk_for_short_content(self):
        """Short content should remain in single chunk."""
        short_content = "This is a very short note."
        chunks = chunk_by_tokens(short_content, chunk_size=500, overlap=50)
        assert len(chunks) == 1


class TestChunkDocument:
    """Test the main chunking dispatcher."""

    def test_uses_header_chunking_for_granola(self):
        """Granola notes should be chunked by headers."""
        content = """---
granola_id: abc123
type: meeting
---

# Meeting with Yoni

## Discussion
We talked about the budget.

## Action Items
- [ ] Review numbers
"""
        chunks = chunk_document(content, is_granola=True)
        # Should have multiple chunks (by section)
        assert len(chunks) >= 2

    def test_uses_token_chunking_for_long_notes(self):
        """Long notes should be chunked by tokens with overlap."""
        long_content = "# Long Note\n\n" + ("This is paragraph content. " * 200)
        chunks = chunk_document(long_content, is_granola=False)
        assert len(chunks) >= 2

    def test_single_chunk_for_short_notes(self):
        """Short notes should be single chunk."""
        short_content = "# Quick Note\n\nJust a brief thought."
        chunks = chunk_document(short_content, is_granola=False)
        assert len(chunks) == 1

    def test_chunk_includes_metadata(self):
        """Each chunk should include index metadata."""
        content = """# Note

## Section 1
Content 1.

## Section 2
Content 2.
"""
        chunks = chunk_document(content, is_granola=True)
        for i, chunk in enumerate(chunks):
            assert "chunk_index" in chunk
            assert chunk["chunk_index"] == i
