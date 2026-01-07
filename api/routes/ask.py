"""
RAG Synthesis (Ask) API endpoint.

POST /api/ask - Ask questions and get synthesized answers from the vault.
"""
import time
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.services.vectorstore import VectorStore
from api.services.synthesizer import get_synthesizer, construct_prompt
from config.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["ask"])

# Initialize vector store (singleton)
_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get or create vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(persist_directory=str(settings.chroma_path))
    return _vector_store


class AskRequest(BaseModel):
    """Ask request schema."""
    question: str = Field(..., min_length=1, description="Question to answer")
    include_sources: bool = Field(default=True, description="Include source citations")

    @field_validator('question')
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Question cannot be empty')
        return v.strip()


class SourceInfo(BaseModel):
    """Source citation info."""
    file_name: str
    file_path: str
    relevance: float


class AskResponse(BaseModel):
    """Ask response schema."""
    answer: str
    sources: list[SourceInfo]
    retrieval_time_ms: int
    synthesis_time_ms: int


def get_claude_response(prompt: str) -> dict:
    """
    Call Claude API and parse response.

    Args:
        prompt: Full prompt with context

    Returns:
        Dict with 'answer' and 'sources_used'
    """
    synthesizer = get_synthesizer()
    answer = synthesizer.synthesize(prompt)

    return {
        "answer": answer,
        "sources_used": []  # Claude response doesn't explicitly list sources
    }


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """
    Ask a question and get a synthesized answer from the vault.

    Args:
        request: Ask request with question

    Returns:
        Synthesized answer with sources and timing info
    """
    # Step 1: Retrieve relevant context
    retrieval_start = time.time()

    vector_store = get_vector_store()
    chunks = vector_store.search(
        query=request.question,
        top_k=10  # Get top 10 chunks for context
    )

    retrieval_ms = int((time.time() - retrieval_start) * 1000)

    # Step 2: Construct prompt and call Claude
    synthesis_start = time.time()

    try:
        prompt = construct_prompt(request.question, chunks)
        result = get_claude_response(prompt)
        answer = result["answer"]
    except Exception as e:
        logger.error(f"Synthesis error: {e}")
        # Return graceful error response
        answer = f"I encountered an error while processing your question. Please try again. (Error: {str(e)[:100]})"

    synthesis_ms = int((time.time() - synthesis_start) * 1000)

    # Step 3: Build deduplicated sources list
    sources = []
    seen_paths = set()

    if request.include_sources:
        for chunk in chunks:
            file_path = chunk.get("file_path", "")
            if file_path and file_path not in seen_paths:
                seen_paths.add(file_path)
                sources.append(SourceInfo(
                    file_name=chunk.get("file_name", "Unknown"),
                    file_path=file_path,
                    relevance=chunk.get("score", 0.0)
                ))

    return AskResponse(
        answer=answer,
        sources=sources,
        retrieval_time_ms=retrieval_ms,
        synthesis_time_ms=synthesis_ms
    )
