"""
Chat API endpoints with streaming support.
"""
import json
import asyncio
import logging
import re
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.services.vectorstore import VectorStore
from api.services.synthesizer import construct_prompt, get_synthesizer
from api.services.query_router import QueryRouter
from api.services.conversation_store import get_store, generate_title
from api.services.calendar import CalendarService
from api.services.drive import DriveService
from api.services.gmail import GmailService

logger = logging.getLogger(__name__)


def extract_date_context(query: str) -> Optional[str]:
    """
    Extract date references from query and convert to YYYY-MM-DD format.

    Supports: today, yesterday, this week, specific dates
    """
    query_lower = query.lower()
    today = datetime.now()

    if "today" in query_lower:
        return today.strftime("%Y-%m-%d")
    elif "yesterday" in query_lower:
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    elif "this week" in query_lower:
        # Return start of week (Monday)
        start_of_week = today - timedelta(days=today.weekday())
        return start_of_week.strftime("%Y-%m-%d")

    # Check for explicit date patterns like "January 7" or "Jan 7"
    month_pattern = r'(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})'
    match = re.search(month_pattern, query_lower)
    if match:
        month_str, day = match.groups()
        month_map = {
            'january': 1, 'jan': 1, 'february': 2, 'feb': 2,
            'march': 3, 'mar': 3, 'april': 4, 'apr': 4,
            'may': 5, 'june': 6, 'jun': 6, 'july': 7, 'jul': 7,
            'august': 8, 'aug': 8, 'september': 9, 'sep': 9,
            'october': 10, 'oct': 10, 'november': 11, 'nov': 11,
            'december': 12, 'dec': 12
        }
        month = month_map.get(month_str)
        if month:
            year = today.year
            # If the date is in the future, assume last year
            try:
                date = datetime(year, month, int(day))
                if date > today:
                    date = datetime(year - 1, month, int(day))
                return date.strftime("%Y-%m-%d")
            except ValueError:
                pass

    return None

router = APIRouter(prefix="/api", tags=["chat"])


class AskStreamRequest(BaseModel):
    """Request for streaming ask endpoint."""
    question: str
    include_sources: bool = True
    conversation_id: Optional[str] = None


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
            # Get or create conversation
            store = get_store()
            conversation_id = request.conversation_id

            if not conversation_id:
                # Create new conversation
                conv = store.create_conversation()
                conversation_id = conv.id
                # Generate title from question
                title = generate_title(request.question)
                store.update_title(conversation_id, title)
                print(f"Created new conversation: {conversation_id} - {title}")

            # Send conversation ID to client
            yield f"data: {json.dumps({'type': 'conversation_id', 'conversation_id': conversation_id})}\n\n"

            # Save user message
            store.add_message(conversation_id, "user", request.question)

            # Route query to determine sources
            query_router = QueryRouter()
            routing_result = await query_router.route(request.question)

            # Console logging for debugging
            print(f"\n{'='*60}")
            print(f"QUERY: {request.question}")
            print(f"CONVERSATION: {conversation_id}")
            print(f"{'='*60}")
            print(f"ROUTING: {routing_result.sources}")
            print(f"  Reasoning: {routing_result.reasoning}")
            print(f"  Confidence: {routing_result.confidence}")
            print(f"  Latency: {routing_result.latency_ms}ms")

            logger.info(
                f"Query routed to: {routing_result.sources} "
                f"(latency: {routing_result.latency_ms}ms, "
                f"confidence: {routing_result.confidence})"
            )

            # Send routing info first
            yield f"data: {json.dumps({'type': 'routing', 'sources': routing_result.sources, 'reasoning': routing_result.reasoning, 'latency_ms': routing_result.latency_ms})}\n\n"

            # Get relevant data based on routing
            chunks = []
            extra_context = []  # For calendar/drive/gmail results

            # Handle calendar queries
            if "calendar" in routing_result.sources:
                print("FETCHING CALENDAR DATA...")
                try:
                    calendar = CalendarService()
                    # Parse date from query
                    date_ref = extract_date_context(request.question)
                    if date_ref:
                        from datetime import datetime
                        target_date = datetime.strptime(date_ref, "%Y-%m-%d")
                        events = calendar.get_events_in_range(
                            target_date,
                            target_date + timedelta(days=1)
                        )
                    else:
                        # Default to upcoming events
                        events = calendar.get_upcoming_events(max_results=10)

                    if events:
                        event_text = "Calendar Events:\n"
                        for e in events:
                            start = e.start.strftime("%Y-%m-%d %H:%M") if e.start else "TBD"
                            event_text += f"- {e.title} ({start})"
                            if e.attendees:
                                event_text += f" with {', '.join(e.attendees[:3])}"
                            event_text += "\n"
                        extra_context.append({"source": "calendar", "content": event_text})
                        print(f"  Found {len(events)} calendar events")
                except Exception as e:
                    print(f"  Calendar error: {e}")

            # Handle drive queries
            if "drive" in routing_result.sources:
                print("FETCHING DRIVE DATA...")
                try:
                    drive = DriveService()
                    files = drive.search(request.question, max_results=5)
                    if files:
                        drive_text = "Google Drive Files:\n"
                        for f in files:
                            drive_text += f"- {f.get('name', 'Unknown')} ({f.get('mimeType', 'file')})\n"
                            if f.get('snippet'):
                                drive_text += f"  Preview: {f.get('snippet')[:200]}...\n"
                        extra_context.append({"source": "drive", "content": drive_text})
                        print(f"  Found {len(files)} drive files")
                except Exception as e:
                    print(f"  Drive error: {e}")

            # Handle gmail queries
            if "gmail" in routing_result.sources:
                print("FETCHING GMAIL DATA...")
                try:
                    gmail = GmailService()
                    messages = gmail.search(request.question, max_results=5)
                    if messages:
                        email_text = "Recent Emails:\n"
                        for m in messages:
                            email_text += f"- From: {m.get('from', 'Unknown')}\n"
                            email_text += f"  Subject: {m.get('subject', 'No subject')}\n"
                            if m.get('snippet'):
                                email_text += f"  Preview: {m.get('snippet')[:150]}...\n"
                        extra_context.append({"source": "gmail", "content": email_text})
                        print(f"  Found {len(messages)} emails")
                except Exception as e:
                    print(f"  Gmail error: {e}")

            # Handle vault queries (always include as fallback)
            if "vault" in routing_result.sources or not routing_result.sources or not extra_context:
                vector_store = VectorStore()

                # Check for date context in query
                date_filter = extract_date_context(request.question)
                if date_filter:
                    print(f"DATE CONTEXT DETECTED: {date_filter}")
                    # Filter to files from that date
                    chunks = vector_store.search(
                        query=request.question,
                        top_k=10,
                        filters={"modified_date": date_filter}
                    )
                    # If no results with date filter, fall back to regular search
                    if not chunks:
                        print("  No results with date filter, falling back to regular search")
                        chunks = vector_store.search(query=request.question, top_k=10)
                else:
                    chunks = vector_store.search(query=request.question, top_k=10)

                # Log search results
                print(f"\nVAULT SEARCH RESULTS (top {len(chunks)}):")
                for i, chunk in enumerate(chunks):
                    fn = chunk.get('file_name', 'unknown')
                    score = chunk.get('score', 0)
                    semantic = chunk.get('semantic_score', 0)
                    recency = chunk.get('recency_score', 0)
                    mod_date = chunk.get('modified_date', 'unknown')
                    print(f"  {i+1}. {fn} ({mod_date})")
                    print(f"      combined={score:.3f} semantic={semantic:.3f} recency={recency:.3f}")

            print(f"{'='*60}\n")

            # Collect sources
            sources = []
            if chunks:
                seen_files = set()
                for chunk in chunks:
                    # Metadata is spread directly on chunk, not nested
                    file_name = chunk.get('file_name', '')
                    if file_name and file_name not in seen_files:
                        seen_files.add(file_name)
                        sources.append({
                            'file_name': file_name,
                            'file_path': chunk.get('file_path', ''),
                        })

            # Send sources to client
            if request.include_sources:
                yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

            # Construct prompt with all context
            # Add extra context (calendar/drive/gmail) to chunks
            for ctx in extra_context:
                chunks.insert(0, {
                    "content": ctx["content"],
                    "file_name": f"[{ctx['source'].upper()}]",
                    "file_path": ctx["source"],
                    "metadata": {"source": ctx["source"]}
                })

            prompt = construct_prompt(request.question, chunks)

            # Stream from Claude
            synthesizer = get_synthesizer()
            full_response = ""

            async for content in synthesizer.stream_response(prompt):
                full_response += content
                yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                await asyncio.sleep(0)  # Allow other tasks to run

            # Save assistant response
            store.add_message(
                conversation_id,
                "assistant",
                full_response,
                sources=sources,
                routing={
                    "sources": routing_result.sources,
                    "reasoning": routing_result.reasoning
                }
            )
            print(f"Saved assistant response ({len(full_response)} chars)")

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
