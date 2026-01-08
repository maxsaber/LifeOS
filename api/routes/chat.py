"""
Chat API endpoints with streaming support.
"""
import json
import asyncio
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.services.vectorstore import VectorStore
from api.services.synthesizer import construct_prompt, get_synthesizer
from api.services.query_router import QueryRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


class AskStreamRequest(BaseModel):
    """Request for streaming ask endpoint."""
    question: str
    include_sources: bool = True


class SaveToVaultRequest(BaseModel):
    """Request for save to vault endpoint."""
    question: str
    answer: str


@router.post("/ask/stream")
async def ask_stream(request: AskStreamRequest):
    """
    Ask a question with streaming response.

    Returns Server-Sent Events (SSE) with:
    - type: "content" - streamed answer content
    - type: "sources" - list of source documents
    - type: "done" - completion signal
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    async def generate():
        try:
            # Route query to determine sources
            query_router = QueryRouter()
            routing_result = await query_router.route(request.question)

            logger.info(
                f"Query routed to: {routing_result.sources} "
                f"(latency: {routing_result.latency_ms}ms, "
                f"confidence: {routing_result.confidence})"
            )

            # Send routing info first
            yield f"data: {json.dumps({'type': 'routing', 'sources': routing_result.sources, 'reasoning': routing_result.reasoning, 'latency_ms': routing_result.latency_ms})}\n\n"

            # Get relevant chunks based on routing
            # Currently only vault is implemented, but routing prepares for multi-source
            chunks = []
            if "vault" in routing_result.sources or not routing_result.sources:
                vector_store = VectorStore()
                chunks = vector_store.search(query=request.question, top_k=10)

            # Send sources
            if request.include_sources and chunks:
                sources = []
                seen_files = set()
                for chunk in chunks:
                    file_name = chunk.get('metadata', {}).get('file_name', '')
                    if file_name and file_name not in seen_files:
                        seen_files.add(file_name)
                        sources.append({
                            'file_name': file_name,
                            'file_path': chunk.get('metadata', {}).get('file_path', ''),
                        })

                yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

            # Construct prompt
            prompt = construct_prompt(request.question, chunks)

            # Stream from Claude
            synthesizer = get_synthesizer()

            async for content in synthesizer.stream_response(prompt):
                yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                await asyncio.sleep(0)  # Allow other tasks to run

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/save-to-vault")
async def save_to_vault(request: SaveToVaultRequest):
    """
    Save conversation to vault as a note.

    Uses Claude to synthesize a proper note from the Q&A.
    """
    if not request.question.strip() or not request.answer.strip():
        raise HTTPException(status_code=400, detail="Question and answer required")

    try:
        synthesizer = get_synthesizer()

        # Ask Claude to create a proper note
        save_prompt = f"""Based on this Q&A conversation, create a well-structured note for my Obsidian vault.

Question: {request.question}

Answer: {request.answer}

Create a note with:
1. A clear, concise title (not "Q&A" or "Conversation")
2. YAML frontmatter with: created date, source: lifeos, relevant tags
3. A TL;DR section at the top
4. Well-organized content (not just the raw Q&A)
5. Any relevant insights or key takeaways

Output ONLY the markdown content for the note, starting with the frontmatter."""

        # Get synthesized note content
        note_content = await synthesizer.get_response(save_prompt)

        # Extract title from frontmatter or first heading
        lines = note_content.split('\n')
        title = "LifeOS Note"
        for line in lines:
            if line.startswith('# '):
                title = line[2:].strip()
                break
            if line.startswith('title:'):
                title = line.split(':', 1)[1].strip().strip('"\'')
                break

        # Clean filename
        safe_title = "".join(c for c in title if c.isalnum() or c in ' -_').strip()
        safe_title = safe_title[:50]  # Limit length
        timestamp = datetime.now().strftime("%Y%m%d-%H%M")
        filename = f"{safe_title} ({timestamp}).md"

        # Determine folder based on content
        folder = "LifeOS/Research"  # Default
        lower_content = note_content.lower()
        if any(word in lower_content for word in ['meeting', 'calendar', 'schedule']):
            folder = "LifeOS/Meetings"
        elif any(word in lower_content for word in ['todo', 'action', 'task']):
            folder = "LifeOS/Actions"
        elif any(word in lower_content for word in ['person', 'about', 'briefing']):
            folder = "LifeOS/People"

        # Write to vault
        from pathlib import Path
        vault_path = Path("/Users/nathanramia/Notes 2025")
        note_path = vault_path / folder / filename

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(note_content)

        # Return obsidian link
        obsidian_url = f"obsidian://open?vault=Notes%202025&file={folder}/{filename}"

        return {
            "status": "saved",
            "path": str(note_path),
            "obsidian_url": obsidian_url,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save: {e}")
