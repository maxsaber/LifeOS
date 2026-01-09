"""
Chat API endpoints with streaming support.
"""
import json
import asyncio
import logging
import re
import base64
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from api.services.vectorstore import VectorStore
from api.services.synthesizer import construct_prompt, get_synthesizer
from api.services.query_router import QueryRouter
from api.services.conversation_store import get_store, generate_title
from api.services.calendar import CalendarService
from api.services.drive import DriveService
from api.services.gmail import GmailService
from api.services.usage_store import get_usage_store
from config.settings import settings

logger = logging.getLogger(__name__)


def extract_search_keywords(query: str) -> list[str]:
    """
    Extract meaningful search keywords from a natural language query.

    Removes common words and extracts proper nouns and key terms.
    """
    # Common words to filter out
    stop_words = {
        'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
        'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
        'from', 'up', 'about', 'into', 'over', 'after', 'beneath', 'under',
        'above', 'and', 'but', 'or', 'nor', 'so', 'yet', 'both', 'either',
        'neither', 'not', 'only', 'own', 'same', 'than', 'too', 'very',
        'just', 'also', 'now', 'here', 'there', 'when', 'where', 'why',
        'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most',
        'other', 'some', 'such', 'no', 'any', 'i', 'me', 'my', 'myself',
        'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 'yourself',
        'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself',
        'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves',
        'what', 'which', 'who', 'whom', 'this', 'that', 'these', 'those',
        'am', 'been', 'being', 'if', 'then', 'else', 'review', 'tell',
        'show', 'find', 'get', 'give', 'look', 'help', 'please', 'thanks',
        'summarize', 'summary', 'reference', 'notes', 'note', 'recent',
        'previous', 'likely', 'talk', 'meeting', 'meetings', 'agenda',
        'agendas', 'doc', 'document', 'google', 'file', 'files',
        'later', 'today', 'tomorrow', 'week', 'month', 'year'
    }

    # Extract words, keeping proper nouns (capitalized words)
    words = re.findall(r'\b[A-Za-z]+\b', query)
    keywords = []

    for word in words:
        # Keep capitalized words (likely names) regardless of stop words
        if word[0].isupper() and len(word) > 1:
            keywords.append(word)
        # Keep non-stop words that are at least 3 chars
        elif word.lower() not in stop_words and len(word) >= 3:
            keywords.append(word)

    # Deduplicate while preserving order
    seen = set()
    unique_keywords = []
    for kw in keywords:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            unique_keywords.append(kw)

    return unique_keywords[:5]  # Limit to top 5 keywords


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

# Attachment configuration
ALLOWED_MEDIA_TYPES = {
    # Images - 5MB each
    "image/png": 5 * 1024 * 1024,
    "image/jpeg": 5 * 1024 * 1024,
    "image/jpg": 5 * 1024 * 1024,
    "image/gif": 5 * 1024 * 1024,
    "image/webp": 5 * 1024 * 1024,
    # PDFs - 10MB
    "application/pdf": 10 * 1024 * 1024,
    # Text files - 1MB
    "text/plain": 1 * 1024 * 1024,
    "text/markdown": 1 * 1024 * 1024,
    "text/csv": 1 * 1024 * 1024,
    "application/json": 1 * 1024 * 1024,
}
MAX_ATTACHMENTS = 5
MAX_TOTAL_SIZE = 20 * 1024 * 1024  # 20MB


class Attachment(BaseModel):
    """Single attachment in a message."""
    filename: str
    media_type: str
    data: str  # Base64 encoded content

    @field_validator("media_type")
    @classmethod
    def validate_media_type(cls, v):
        if v not in ALLOWED_MEDIA_TYPES:
            raise ValueError(f"Unsupported file type: {v}. Allowed types: images (PNG, JPG, GIF, WebP), PDFs, and text files (TXT, MD, CSV, JSON)")
        return v

    def get_size_bytes(self) -> int:
        """Calculate the size of the decoded data."""
        # Base64 encoding adds ~33% overhead
        return len(self.data) * 3 // 4

    def validate_size(self):
        """Validate the attachment size against limits."""
        size = self.get_size_bytes()
        max_size = ALLOWED_MEDIA_TYPES.get(self.media_type, 0)
        if size > max_size:
            max_mb = max_size / (1024 * 1024)
            actual_mb = size / (1024 * 1024)
            raise ValueError(
                f"File '{self.filename}' ({actual_mb:.1f}MB) exceeds "
                f"limit for {self.media_type} ({max_mb:.0f}MB)"
            )


class AskStreamRequest(BaseModel):
    """Request for streaming ask endpoint."""
    question: str
    include_sources: bool = True
    conversation_id: Optional[str] = None
    attachments: Optional[list[Attachment]] = None

    @field_validator("attachments")
    @classmethod
    def validate_attachments(cls, v):
        if v is None:
            return v
        if len(v) > MAX_ATTACHMENTS:
            raise ValueError(f"Maximum {MAX_ATTACHMENTS} attachments allowed, got {len(v)}")

        # Validate each attachment's size
        total_size = 0
        for att in v:
            att.validate_size()
            total_size += att.get_size_bytes()

        if total_size > MAX_TOTAL_SIZE:
            total_mb = total_size / (1024 * 1024)
            max_mb = MAX_TOTAL_SIZE / (1024 * 1024)
            raise ValueError(f"Total attachment size ({total_mb:.1f}MB) exceeds limit ({max_mb:.0f}MB)")

        return v


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

            # Add "attachment" to sources if attachments are present
            effective_sources = list(routing_result.sources)
            if request.attachments:
                effective_sources.append("attachment")
                # Log attachment metadata (not content)
                for att in request.attachments:
                    size_kb = att.get_size_bytes() / 1024
                    print(f"  Attachment: {att.filename} ({att.media_type}, {size_kb:.1f}KB)")

            # Send routing info first (with attachment source if applicable)
            yield f"data: {json.dumps({'type': 'routing', 'sources': effective_sources, 'reasoning': routing_result.reasoning, 'latency_ms': routing_result.latency_ms})}\n\n"

            # Get relevant data based on routing
            chunks = []
            extra_context = []  # For calendar/drive/gmail results

            # Handle calendar queries - ALWAYS query both personal and work calendars
            if "calendar" in routing_result.sources:
                print("FETCHING CALENDAR DATA (both personal and work)...")
                from api.services.google_auth import GoogleAccount
                all_events = []

                for account_type in [GoogleAccount.PERSONAL, GoogleAccount.WORK]:
                    try:
                        calendar = CalendarService(account_type)
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

                        all_events.extend(events)
                        print(f"  Found {len(events)} events from {account_type.value} calendar")
                    except Exception as e:
                        print(f"  {account_type.value} calendar error: {e}")

                # Sort all events by start time
                all_events.sort(key=lambda e: e.start_time)

                if all_events:
                    event_text = "Calendar Events (Personal + Work):\n"
                    calendar_sources = []  # Track individual events for source links
                    for e in all_events:
                        start = e.start_time.strftime("%Y-%m-%d %H:%M") if e.start_time else "TBD"
                        account_label = f"[{e.source_account}]" if e.source_account else ""
                        event_text += f"- {e.title} ({start}) {account_label}"
                        if e.attendees:
                            event_text += f" with {', '.join(e.attendees[:3])}"
                        event_text += "\n"
                        # Store event for source linking
                        calendar_sources.append({
                            "title": e.title,
                            "start_time": start,
                            "html_link": e.html_link,
                            "source_account": e.source_account
                        })
                    extra_context.append({
                        "source": "calendar",
                        "content": event_text,
                        "events": calendar_sources  # Include event links
                    })
                    print(f"  Total: {len(all_events)} calendar events from both accounts")

            # Handle drive queries - query both personal and work accounts
            if "drive" in routing_result.sources:
                print("FETCHING DRIVE DATA (both personal and work)...")
                from api.services.google_auth import GoogleAccount

                # Extract keywords for search
                keywords = extract_search_keywords(request.question)
                search_term = " ".join(keywords) if keywords else None
                print(f"  Search keywords: {keywords}")

                name_matched_files = []  # Files matching by name (higher priority)
                content_matched_files = []  # Files matching by content
                seen_file_ids = set()

                for account_type in [GoogleAccount.PERSONAL, GoogleAccount.WORK]:
                    try:
                        drive = DriveService(account_type)
                        if search_term:
                            # Search by BOTH name and full_text to catch more results
                            # Name search finds "Nathan/Kevin 1:1 notes" when searching "Kevin"
                            name_files = drive.search(name=search_term, max_results=5)
                            content_files = drive.search(full_text=search_term, max_results=5)

                            # Track name matches separately (higher priority for reading content)
                            for f in name_files:
                                if f.file_id not in seen_file_ids:
                                    seen_file_ids.add(f.file_id)
                                    name_matched_files.append(f)

                            for f in content_files:
                                if f.file_id not in seen_file_ids:
                                    seen_file_ids.add(f.file_id)
                                    content_matched_files.append(f)

                            print(f"  Found {len(name_files)} by name, {len(content_files)} by content from {account_type.value} drive")
                        else:
                            pass
                    except Exception as e:
                        print(f"  {account_type.value} drive error: {e}")

                # Prioritize name matches first, then content matches
                all_files = name_matched_files + content_matched_files
                print(f"  Prioritizing {len(name_matched_files)} name-matched files")

                # Adaptive retrieval settings
                INITIAL_MAX_FILES = 2  # Read content from 2 files initially
                INITIAL_CHAR_LIMIT = 1000  # 1000 chars per file initially
                EXPANDED_CHAR_LIMIT = 4000  # Can expand to 4000 chars on request

                if all_files:
                    drive_text = "Google Drive Files:\n"
                    files_with_content = 0

                    # Track all available files for potential follow-up reads
                    available_for_deeper_read = []

                    for f in all_files:
                        name = f.name if hasattr(f, 'name') else f.get('name', 'Unknown')
                        mime = f.mime_type if hasattr(f, 'mime_type') else f.get('mimeType', 'file')
                        account = f.source_account if hasattr(f, 'source_account') else ''
                        file_id = f.file_id if hasattr(f, 'file_id') else f.get('id', '')

                        # Track file for potential deeper reading
                        available_for_deeper_read.append({
                            "name": name,
                            "file_id": file_id,
                            "mime_type": mime,
                            "account": account
                        })

                        drive_text += f"\n### {name} [{account}]\n"

                        # For Google Docs/Sheets, fetch actual content (limited initially)
                        if files_with_content < INITIAL_MAX_FILES and file_id:
                            try:
                                account_type = GoogleAccount.WORK if account == 'work' else GoogleAccount.PERSONAL
                                drive_for_content = DriveService(account_type)
                                content = drive_for_content.get_file_content(file_id, mime)
                                if content:
                                    # Initial read is limited to INITIAL_CHAR_LIMIT
                                    if len(content) > INITIAL_CHAR_LIMIT:
                                        content = content[:INITIAL_CHAR_LIMIT] + f"\n... [truncated - {len(content)} total chars available, use [EXPAND:{name}] to read more]"
                                    drive_text += f"{content}\n"
                                    files_with_content += 1
                                    print(f"    Read {min(len(content), INITIAL_CHAR_LIMIT)} chars from: {name}")
                            except Exception as e:
                                print(f"    Could not read {name}: {e}")
                                drive_text += f"(Could not read content)\n"
                        else:
                            drive_text += f"(Preview not loaded - use [READ_MORE:{name}] to read this document)\n"

                    # Add instructions for adaptive retrieval
                    if len(all_files) > INITIAL_MAX_FILES:
                        unread_files = [f["name"] for f in available_for_deeper_read[INITIAL_MAX_FILES:]]
                        drive_text += f"\n---\nAdditional documents available (not yet read): {', '.join(unread_files)}\n"
                        drive_text += "Use [READ_MORE:filename] to read any unread document, or [EXPAND:filename] to get more content from a truncated document.\n"

                    extra_context.append({"source": "drive", "content": drive_text})
                    # Store available files for follow-up (will be used by adaptive retrieval)
                    extra_context.append({"source": "_drive_files_available", "files": available_for_deeper_read})
                    print(f"  Total: {len(all_files)} drive files, {files_with_content} with initial content")

            # Handle gmail queries - query both personal and work accounts
            if "gmail" in routing_result.sources:
                print("FETCHING GMAIL DATA (both personal and work)...")
                from api.services.google_auth import GoogleAccount

                # Extract keywords for search
                keywords = extract_search_keywords(request.question)
                search_term = " ".join(keywords) if keywords else None
                print(f"  Search keywords: {keywords}")

                all_messages = []
                for account_type in [GoogleAccount.PERSONAL, GoogleAccount.WORK]:
                    try:
                        gmail = GmailService(account_type)
                        if search_term:
                            messages = gmail.search(keywords=search_term, max_results=5)
                        else:
                            messages = gmail.search(max_results=5)  # Recent emails
                        all_messages.extend(messages)
                        print(f"  Found {len(messages)} emails from {account_type.value} gmail")
                    except Exception as e:
                        print(f"  {account_type.value} gmail error: {e}")

                if all_messages:
                    email_text = "Recent Emails:\n"
                    for m in all_messages:
                        sender = m.sender if hasattr(m, 'sender') else m.get('from', 'Unknown')
                        subject = m.subject if hasattr(m, 'subject') else m.get('subject', 'No subject')
                        snippet = m.snippet if hasattr(m, 'snippet') else m.get('snippet', '')
                        account = m.source_account if hasattr(m, 'source_account') else ''
                        email_text += f"- From: {sender} [{account}]\n"
                        email_text += f"  Subject: {subject}\n"
                        if snippet:
                            email_text += f"  Preview: {snippet[:150]}...\n"
                    extra_context.append({"source": "gmail", "content": email_text})
                    print(f"  Total: {len(all_messages)} emails from both accounts")

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
            vault_prefix = str(settings.vault_path) + "/"
            if chunks:
                seen_files = set()
                for chunk in chunks:
                    # Metadata is spread directly on chunk, not nested
                    file_name = chunk.get('file_name', '')
                    file_path = chunk.get('file_path', '')
                    if file_name and file_name not in seen_files:
                        seen_files.add(file_name)
                        # Compute relative path from vault for Obsidian links
                        if file_path.startswith(vault_prefix):
                            obsidian_path = file_path[len(vault_prefix):]
                        else:
                            obsidian_path = file_name  # Fallback to filename
                        sources.append({
                            'file_name': file_name,
                            'file_path': file_path,
                            'obsidian_path': obsidian_path,
                            'source_type': 'vault',
                        })

            # Add calendar event sources with Google Calendar links
            for ctx in extra_context:
                if ctx.get("source") == "calendar" and ctx.get("events"):
                    for event in ctx["events"]:
                        sources.append({
                            'file_name': f"📅 {event['title']} ({event['start_time']})",
                            'source_type': 'calendar',
                            'url': event.get('html_link'),
                            'source_account': event.get('source_account'),
                        })

            # Send sources to client
            if request.include_sources:
                yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

            # Construct prompt with all context
            # Add extra context (calendar/drive/gmail) to chunks
            # Skip internal metadata entries (prefixed with _)
            for ctx in extra_context:
                if ctx.get("source", "").startswith("_"):
                    continue  # Skip internal metadata like _drive_files_available
                chunks.insert(0, {
                    "content": ctx["content"],
                    "file_name": f"[{ctx['source'].upper()}]",
                    "file_path": ctx["source"],
                    "metadata": {"source": ctx["source"]}
                })

            prompt = construct_prompt(request.question, chunks)

            # Prepare attachments for synthesizer (convert Pydantic models to dicts)
            attachments_for_api = None
            if request.attachments:
                attachments_for_api = [
                    {
                        "filename": att.filename,
                        "media_type": att.media_type,
                        "data": att.data
                    }
                    for att in request.attachments
                ]

            # Stream from Claude with adaptive retrieval support
            synthesizer = get_synthesizer()
            full_response = ""

            # Get available files for adaptive retrieval (if any)
            available_files = {}
            for ctx in extra_context:
                if ctx.get("source") == "_drive_files_available":
                    for f in ctx.get("files", []):
                        available_files[f["name"]] = f

            async for chunk in synthesizer.stream_response(prompt, attachments=attachments_for_api):
                if isinstance(chunk, dict) and chunk.get("type") == "usage":
                    # Record usage to database for historical tracking
                    usage_store = get_usage_store()
                    usage_store.record_usage(
                        model=chunk.get("model", "sonnet"),
                        input_tokens=chunk.get("input_tokens", 0),
                        output_tokens=chunk.get("output_tokens", 0),
                        cost_usd=chunk.get("cost_usd", 0.0),
                        conversation_id=conversation_id
                    )
                    yield f"data: {json.dumps(chunk)}\n\n"
                else:
                    full_response += chunk
                    yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                await asyncio.sleep(0)

            # Check for adaptive retrieval requests in the response
            read_more_pattern = r'\[READ_MORE:([^\]]+)\]'
            expand_pattern = r'\[EXPAND:([^\]]+)\]'

            read_more_matches = re.findall(read_more_pattern, full_response)
            expand_matches = re.findall(expand_pattern, full_response)

            if (read_more_matches or expand_matches) and available_files:
                print(f"ADAPTIVE RETRIEVAL: Detected requests - READ_MORE: {read_more_matches}, EXPAND: {expand_matches}")
                yield f"data: {json.dumps({'type': 'status', 'message': 'Fetching additional document content...'})}\n\n"

                # Fetch additional content
                additional_content = []
                files_fetched = 0
                MAX_FOLLOW_UP_FILES = 2

                for filename in (read_more_matches + expand_matches)[:MAX_FOLLOW_UP_FILES]:
                    # Find the file in available files (fuzzy match)
                    matched_file = None
                    for name, file_info in available_files.items():
                        if filename.lower() in name.lower() or name.lower() in filename.lower():
                            matched_file = file_info
                            break

                    if matched_file and files_fetched < MAX_FOLLOW_UP_FILES:
                        try:
                            account_type = GoogleAccount.WORK if matched_file["account"] == 'work' else GoogleAccount.PERSONAL
                            drive = DriveService(account_type)
                            content = drive.get_file_content(matched_file["file_id"], matched_file["mime_type"])
                            if content:
                                # Expanded read gets up to 4000 chars
                                if len(content) > 4000:
                                    content = content[:4000] + "\n... [truncated at 4000 chars]"
                                additional_content.append(f"\n### Expanded: {matched_file['name']}\n{content}")
                                files_fetched += 1
                                print(f"  Fetched expanded content for: {matched_file['name']} ({len(content)} chars)")
                        except Exception as e:
                            print(f"  Failed to fetch {filename}: {e}")

                if additional_content:
                    # Make a follow-up call with the additional content
                    follow_up_prompt = f"""Based on your previous response, here is the additional document content you requested:

{chr(10).join(additional_content)}

Please continue your response, incorporating this additional information. Do NOT repeat your previous response - just provide the additional insights from this new content."""

                    yield f"data: {json.dumps({'type': 'content', 'content': '\\n\\n---\\n*Additional content retrieved:*\\n\\n'})}\n\n"

                    async for chunk in synthesizer.stream_response(follow_up_prompt, attachments=None):
                        if isinstance(chunk, dict) and chunk.get("type") == "usage":
                            # Record usage to database for historical tracking
                            usage_store = get_usage_store()
                            usage_store.record_usage(
                                model=chunk.get("model", "sonnet"),
                                input_tokens=chunk.get("input_tokens", 0),
                                output_tokens=chunk.get("output_tokens", 0),
                                cost_usd=chunk.get("cost_usd", 0.0),
                                conversation_id=conversation_id
                            )
                            yield f"data: {json.dumps(chunk)}\n\n"
                        else:
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                        await asyncio.sleep(0)

            # Save assistant response
            store.add_message(
                conversation_id,
                "assistant",
                full_response,
                sources=sources,
                routing={
                    "sources": effective_sources,
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
