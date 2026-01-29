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
from api.services.hybrid_search import HybridSearch
from api.services.synthesizer import construct_prompt, get_synthesizer
from api.services.query_router import QueryRouter
from api.services.conversation_store import get_store, generate_title
from api.services.calendar import CalendarService
from api.services.drive import DriveService
from api.services.gmail import GmailService
from api.services.usage_store import get_usage_store
from api.services.briefings import get_briefings_service
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


def expand_followup_query(query: str, conversation_history: list) -> str:
    """
    Expand a follow-up query with context from conversation history.

    Detects short queries with pronouns (our, their, they, them, he, she, it)
    or implicit references and expands them with context from previous messages.

    Args:
        query: The current user query
        conversation_history: List of previous messages in the conversation

    Returns:
        Expanded query with context, or original query if not a follow-up
    """
    if not conversation_history:
        return query

    query_lower = query.lower().strip()

    # Follow-up indicators: short query with pronouns or implicit references
    followup_patterns = [
        "what about", "how about", "and ", "but ",
        "their ", "they ", "them ", "he ", "she ", "it ",
        "our ", "his ", "her ", "its ",
        "the same", "more about", "anything else",
        "what else", "tell me more"
    ]

    is_followup = (
        len(query.split()) < 10 and  # Short query
        any(pattern in query_lower for pattern in followup_patterns)
    )

    if not is_followup:
        return query

    # Find the most recent user question that mentions a person or topic
    for msg in reversed(conversation_history):
        if msg.role == "user":
            # Extract person name or topic from previous query
            prev_query_lower = msg.content.lower()

            # Check for person-related queries
            person_patterns = [
                r"(?:with|about|from|to)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)",
                r"interactions?\s+with\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)",
            ]

            for pattern in person_patterns:
                match = re.search(pattern, msg.content, re.IGNORECASE)
                if match:
                    person_name = match.group(1).strip()
                    # Avoid matching common words
                    if person_name.lower() not in {'the', 'a', 'an', 'my', 'our', 'their'}:
                        # Expand the query with the person name
                        expanded = f"{query} (regarding {person_name})"
                        return expanded

            # If no person found but previous query exists, reference it
            if len(msg.content) < 200:  # Don't include very long queries
                expanded = f"{query} [Context: previous question was about '{msg.content[:100]}']"
                return expanded
            break

    return query


def detect_compose_intent(query: str) -> bool:
    """
    Detect if the query is asking to compose/draft an email.

    Returns True if the query indicates email composition intent.
    """
    query_lower = query.lower()

    # Compose intent patterns
    compose_patterns = [
        "draft an email",
        "draft email",
        "draft a message",
        "compose an email",
        "compose email",
        "write an email",
        "write email",
        "send an email",  # We'll create a draft, not send
        "send email",
        "email to ",  # "email to John about..."
        "write to ",  # "write to Sarah about..."
        "draft to ",
    ]

    return any(pattern in query_lower for pattern in compose_patterns)


async def extract_draft_params(query: str, conversation_history: list = None) -> Optional[dict]:
    """
    Use Claude to extract email draft parameters from a compose request.

    Returns dict with: to, subject, body, account (personal/work)
    Or None if extraction fails.
    """
    # Build context from conversation if available
    context = ""
    if conversation_history:
        recent_msgs = conversation_history[-6:]  # Last 3 exchanges
        context_parts = []
        for msg in recent_msgs:
            context_parts.append(f"{msg.role}: {msg.content[:500]}")
        if context_parts:
            context = "\n\nConversation context:\n" + "\n".join(context_parts)

    extraction_prompt = f"""Extract email draft parameters from this request.{context}

User request: {query}

Return a JSON object with these fields (leave empty string if not specified):
- "to": recipient email or name (required)
- "subject": email subject line
- "body": the email body content to write
- "account": "personal" or "work" (default to "personal" unless work/professional context is mentioned)

If the user is asking to draft a follow-up or reply based on conversation context, use that context to fill in the body.

Return ONLY valid JSON, no other text. Example:
{{"to": "john@example.com", "subject": "Follow up on meeting", "body": "Hi John,\\n\\nI wanted to follow up...", "account": "personal"}}"""

    try:
        synthesizer = get_synthesizer()
        response_text = await synthesizer.get_response(
            extraction_prompt,
            max_tokens=1024,
            model_tier="haiku"  # Fast, cheap for structured extraction
        )

        # Find JSON in response
        json_match = re.search(r'\{[^}]+\}', response_text, re.DOTALL)
        if json_match:
            params = json.loads(json_match.group())
            # Validate required field
            if params.get("to"):
                return params
    except Exception as e:
        logger.error(f"Failed to extract draft params: {e}")

    return None


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


def extract_message_date_range(query: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Extract date range for message queries.

    Supports: last month, last week, in December, this month, past N days/weeks/months,
              lately, recently
    Returns (start_date, end_date) tuple.
    """
    query_lower = query.lower()
    today = datetime.now()

    # "lately" - default to last 30 days
    if "lately" in query_lower:
        start = today - timedelta(days=30)
        return (start, today)

    # "recently" or "recent" - default to last 14 days
    if "recently" in query_lower or "recent " in query_lower:
        start = today - timedelta(days=14)
        return (start, today)

    # "last month" or "past month"
    if "last month" in query_lower or "past month" in query_lower:
        # First day of last month
        first_of_this_month = today.replace(day=1)
        last_month_end = first_of_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return (last_month_start, last_month_end)

    # "this month"
    if "this month" in query_lower:
        first_of_month = today.replace(day=1, hour=0, minute=0, second=0)
        return (first_of_month, today)

    # "last week" or "past week"
    if "last week" in query_lower or "past week" in query_lower:
        start = today - timedelta(days=7)
        return (start, today)

    # "past N days/weeks/months"
    past_pattern = r'(?:past|last)\s+(\d+)\s+(day|days|week|weeks|month|months)'
    match = re.search(past_pattern, query_lower)
    if match:
        num, unit = match.groups()
        num = int(num)
        if 'day' in unit:
            start = today - timedelta(days=num)
        elif 'week' in unit:
            start = today - timedelta(weeks=num)
        elif 'month' in unit:
            start = today - timedelta(days=num * 30)  # Approximate
        return (start, today)

    # "in December", "in January", etc.
    month_pattern = r'\bin\s+(january|february|march|april|may|june|july|august|september|october|november|december)\b'
    match = re.search(month_pattern, query_lower)
    if match:
        month_str = match.group(1)
        month_map = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12
        }
        month = month_map.get(month_str)
        if month:
            year = today.year
            # If month is in the future, use last year
            if month > today.month:
                year -= 1
            start = datetime(year, month, 1)
            # End of month
            if month == 12:
                end = datetime(year + 1, 1, 1) - timedelta(days=1)
            else:
                end = datetime(year, month + 1, 1) - timedelta(days=1)
            return (start, end)

    return (None, None)


def extract_message_search_terms(query: str, person_name: str) -> Optional[str]:
    """
    Extract search terms for message content from query.

    Looks for patterns like "about X", "regarding X", "mentioning X"
    """
    query_lower = query.lower()
    person_lower = person_name.lower()

    # Remove the person's name to focus on topic
    query_without_person = query_lower.replace(person_lower, "").strip()

    # Temporal words that shouldn't be search terms
    temporal_words = {'lately', 'recently', 'today', 'yesterday', 'tomorrow',
                      'last', 'this', 'next', 'week', 'month', 'year', 'now'}

    # Patterns that indicate topic search
    patterns = [
        r'about\s+(.+?)(?:\s+with|\s+in|\s+from|\s*\??\s*$)',
        r'regarding\s+(.+?)(?:\s+with|\s+in|\s+from|\s*\??\s*$)',
        r'mentioning\s+(.+?)(?:\s+with|\s+in|\s+from|\s*\??\s*$)',
        r'discussed?\s+(.+?)(?:\s+with|\s+in|\s+from|\s*\??\s*$)',
        r'talked?\s+about\s+(.+?)(?:\s+with|\s+in|\s+from|\s*\??\s*$)',
        r'talking\s+about\s+(.+?)(?:\s+with|\s+in|\s+from|\s*\??\s*$)',
    ]

    for pattern in patterns:
        match = re.search(pattern, query_without_person)
        if match:
            term = match.group(1).strip()
            # Clean up common words and punctuation
            term = re.sub(r'\b(the|a|an|our|my|her|his|their)\b', '', term).strip()
            term = term.rstrip('?').strip()
            # Filter out temporal words
            if term.lower() in temporal_words:
                return None
            if len(term) > 2:
                return term

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
    """Request for save to vault endpoint.

    Supports two modes:
    1. Full conversation mode: provide conversation_id
    2. Single Q&A mode: provide question and answer (backward compatible)
    """
    # Content - supports full conversation
    conversation_id: Optional[str] = None
    question: Optional[str] = None  # Fallback for single Q&A
    answer: Optional[str] = None

    # User customization
    title: Optional[str] = None
    folder: Optional[str] = None
    tags: Optional[list[str]] = None

    # Content toggles
    include_sources: bool = True
    include_raw_qa: bool = False
    full_conversation: bool = True

    # Custom guidance
    guidance: Optional[str] = None


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

            # Get conversation history for context in follow-up questions
            conversation_history = store.get_messages(conversation_id, limit=10)
            # Exclude current message to avoid duplication
            if conversation_history and conversation_history[-1].role == "user" and conversation_history[-1].content == request.question:
                conversation_history = conversation_history[:-1]

            # Check for email compose intent - handle as action, not search
            if detect_compose_intent(request.question):
                print("DETECTED COMPOSE INTENT - handling email draft")
                yield f"data: {json.dumps({'type': 'routing', 'sources': ['gmail_draft'], 'reasoning': 'Email composition detected', 'latency_ms': 0})}\n\n"

                draft_params = await extract_draft_params(request.question, conversation_history)
                if draft_params:
                    try:
                        from api.services.google_auth import GoogleAccount

                        # Determine account
                        account_str = draft_params.get("account", "personal").lower()
                        account_type = GoogleAccount.WORK if account_str == "work" else GoogleAccount.PERSONAL

                        gmail = GmailService(account_type)
                        draft = gmail.create_draft(
                            to=draft_params["to"],
                            subject=draft_params.get("subject", ""),
                            body=draft_params.get("body", ""),
                        )

                        if draft:
                            # Construct Gmail URL (same as API route)
                            gmail_url = f"https://mail.google.com/mail/u/0/#drafts?compose={draft.draft_id}"

                            response_text = f"I've created a draft email for you:\n\n"
                            response_text += f"**To:** {draft.to}\n"
                            response_text += f"**Subject:** {draft.subject}\n"
                            response_text += f"**Account:** {draft.source_account}\n\n"
                            response_text += f"[Open draft in Gmail]({gmail_url})\n\n"
                            response_text += f"Review and send when ready."

                            # Stream the response
                            for chunk in response_text:
                                yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                                await asyncio.sleep(0.01)

                            # Save assistant response
                            store.add_message(conversation_id, "assistant", response_text)

                            # Send done signal
                            yield f"data: {json.dumps({'type': 'done'})}\n\n"
                            return
                        else:
                            error_msg = "Failed to create draft. Please try again."
                            yield f"data: {json.dumps({'type': 'content', 'content': error_msg})}\n\n"
                            store.add_message(conversation_id, "assistant", error_msg)
                            yield f"data: {json.dumps({'type': 'done'})}\n\n"
                            return
                    except Exception as e:
                        error_msg = f"Error creating draft: {str(e)}"
                        logger.error(error_msg)
                        yield f"data: {json.dumps({'type': 'content', 'content': error_msg})}\n\n"
                        store.add_message(conversation_id, "assistant", error_msg)
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return
                else:
                    # Couldn't extract params, fall through to normal flow
                    # which will use Claude to ask for clarification
                    print("Could not extract draft params, falling through to normal flow")

            # Expand follow-up queries with conversation context
            query_for_routing = request.question
            if conversation_history:
                query_for_routing = expand_followup_query(request.question, conversation_history)
                if query_for_routing != request.question:
                    print(f"Expanded query: '{request.question}' -> '{query_for_routing}'")

            # Route query to determine sources
            query_router = QueryRouter()
            routing_result = await query_router.route(query_for_routing)

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
                from api.services.entity_resolver import get_entity_resolver

                # Extract keywords for search
                keywords = extract_search_keywords(request.question)
                search_term = " ".join(keywords) if keywords else None
                print(f"  Search keywords: {keywords}")

                # Resolve person name to email for targeted search
                person_email = None
                is_sent_to = False  # Whether query is about emails sent TO the person
                person_name = query_router._extract_person_name(request.question)
                if person_name:
                    print(f"  Detected person name: {person_name}")
                    try:
                        resolver = get_entity_resolver()
                        result = resolver.resolve(name=person_name)
                        if result and result.entity:
                            # Get primary email from entity
                            entity = result.entity
                            if entity.emails:
                                person_email = entity.emails[0]
                                print(f"  Resolved to email: {person_email}")
                            elif entity.email:
                                person_email = entity.email
                                print(f"  Resolved to email: {person_email}")
                    except Exception as e:
                        print(f"  Entity resolution error: {e}")

                    # Check if query is about emails sent TO the person
                    query_lower = request.question.lower()
                    if any(phrase in query_lower for phrase in [
                        "i sent", "sent to", "emailed to", "wrote to",
                        "email to", "message to", "i emailed", "i wrote"
                    ]):
                        is_sent_to = True
                        print(f"  Query is about emails SENT TO {person_name}")

                all_messages = []
                for account_type in [GoogleAccount.PERSONAL, GoogleAccount.WORK]:
                    try:
                        gmail = GmailService(account_type)
                        # Use person email for targeted search
                        # When we have a resolved email, fetch full body (fewer results since bodies are large)
                        if person_email:
                            if is_sent_to:
                                messages = gmail.search(
                                    to_email=person_email,
                                    max_results=5,
                                    include_body=True
                                )
                            else:
                                messages = gmail.search(
                                    from_email=person_email,
                                    max_results=5,
                                    include_body=True
                                )
                            print(f"  Searching {'to' if is_sent_to else 'from'}: {person_email} (with body)")
                        elif search_term:
                            messages = gmail.search(keywords=search_term, max_results=5)
                        else:
                            messages = gmail.search(max_results=5)  # Recent emails
                        all_messages.extend(messages)
                        print(f"  Found {len(messages)} emails from {account_type.value} gmail")
                    except Exception as e:
                        print(f"  {account_type.value} gmail error: {e}")

                if all_messages:
                    from zoneinfo import ZoneInfo
                    eastern = ZoneInfo("America/New_York")

                    email_text = "Recent Emails:\n"
                    for m in all_messages:
                        sender = m.sender if hasattr(m, 'sender') else m.get('from', 'Unknown')
                        recipient = m.to if hasattr(m, 'to') else m.get('to', '')
                        subject = m.subject if hasattr(m, 'subject') else m.get('subject', 'No subject')
                        snippet = m.snippet if hasattr(m, 'snippet') else m.get('snippet', '')
                        body = m.body if hasattr(m, 'body') else m.get('body', '')
                        account = m.source_account if hasattr(m, 'source_account') else ''

                        # Convert to Eastern time
                        date_str = ''
                        if hasattr(m, 'date') and m.date:
                            try:
                                eastern_time = m.date.astimezone(eastern)
                                date_str = eastern_time.strftime('%Y-%m-%d %I:%M %p ET')
                            except Exception:
                                date_str = m.date.strftime('%Y-%m-%d %H:%M')

                        email_text += f"- From: {sender} [{account}]\n"
                        if recipient:
                            email_text += f"  To: {recipient}\n"
                        email_text += f"  Subject: {subject}\n"
                        if date_str:
                            email_text += f"  Date: {date_str}\n"
                        # Show full body if available, otherwise snippet
                        if body:
                            # Limit body to prevent context overflow
                            body_preview = body[:2000] + "..." if len(body) > 2000 else body
                            email_text += f"  Body:\n{body_preview}\n"
                        elif snippet:
                            email_text += f"  Preview: {snippet[:200]}...\n"
                    extra_context.append({"source": "gmail", "content": email_text})
                    print(f"  Total: {len(all_messages)} emails from both accounts")

            # Handle slack queries - search Slack DMs and channels
            if "slack" in routing_result.sources:
                print("SEARCHING SLACK...")
                try:
                    from api.services.slack_indexer import get_slack_indexer
                    from api.services.slack_integration import is_slack_enabled

                    if is_slack_enabled():
                        slack_indexer = get_slack_indexer()
                        slack_results = slack_indexer.search(
                            query=request.question,
                            top_k=10,
                        )

                        if slack_results:
                            slack_text = "\n\n### Slack Messages\n\n"
                            for msg in slack_results:
                                channel_name = msg.get("channel_name", "Unknown")
                                user_name = msg.get("user_name", "Unknown")
                                timestamp = msg.get("timestamp", "")
                                content = msg.get("content", "")

                                # Parse timestamp for display
                                try:
                                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                                except:
                                    date_str = timestamp[:10] if timestamp else ""

                                slack_text += f"**{channel_name}** - {user_name} ({date_str}):\n"
                                slack_text += f"  {content[:500]}{'...' if len(content) > 500 else ''}\n\n"

                            extra_context.append({"source": "slack", "content": slack_text})
                            print(f"  Found {len(slack_results)} Slack messages")
                        else:
                            print("  No Slack messages found")
                    else:
                        print("  Slack not enabled")
                except Exception as e:
                    print(f"  Slack search error: {e}")
                    logger.error(f"Slack search failed: {e}")

            # Handle vault queries (always include as fallback)
            if "vault" in routing_result.sources or not routing_result.sources or not extra_context:
                # Use hybrid search (vector + BM25 keyword) for better keyword matching
                hybrid_search = HybridSearch()

                # Check for date context in query
                date_filter = extract_date_context(request.question)
                if date_filter:
                    print(f"DATE CONTEXT DETECTED: {date_filter}")
                    # For date-filtered queries, use vector store directly
                    vector_store = VectorStore()
                    chunks = vector_store.search(
                        query=request.question,
                        top_k=10,
                        filters={"modified_date": date_filter}
                    )
                    # If no results with date filter, fall back to hybrid search
                    if not chunks:
                        print("  No results with date filter, falling back to hybrid search")
                        chunks = hybrid_search.search(query=request.question, top_k=10)
                else:
                    chunks = hybrid_search.search(query=request.question, top_k=10)

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

            # Handle people queries - generate stakeholder briefings + message history
            if "people" in routing_result.sources:
                print("PROCESSING PEOPLE QUERY...")

                # Extract person name from query
                person_name = query_router._extract_person_name(request.question)
                person_email = None
                entity_id = None

                if person_name:
                    print(f"  Extracted person name: {person_name}")

                    # Search calendar for person's email (7 days back and forward)
                    from api.services.google_auth import GoogleAccount

                    for account_type in [GoogleAccount.PERSONAL, GoogleAccount.WORK]:
                        try:
                            calendar = CalendarService(account_type)
                            events = calendar.search_events(
                                attendee=person_name,
                                days_forward=7,
                                days_back=7
                            )
                            for event in events:
                                for attendee in event.attendees:
                                    if '@' in attendee:
                                        # Check if name appears in email or we have a name match
                                        if person_name.lower() in attendee.lower():
                                            person_email = attendee
                                            break
                                if person_email:
                                    break
                            if person_email:
                                break
                        except Exception as e:
                            print(f"  Calendar search error ({account_type.value}): {e}")

                    if person_email:
                        print(f"  Found email from calendar: {person_email}")

                    # Resolve entity to get entity_id for message queries
                    try:
                        from api.services.entity_resolver import get_entity_resolver
                        resolver = get_entity_resolver()
                        result = resolver.resolve(name=person_name, email=person_email)
                        if result:
                            entity_id = result.entity.id
                            print(f"  Resolved entity: {result.entity.canonical_name} ({entity_id})")
                    except Exception as e:
                        print(f"  Entity resolution error: {e}")

                    # Check if query asks for specific message context
                    start_date, end_date = extract_message_date_range(request.question)
                    search_term = extract_message_search_terms(request.question, person_name)

                    # If date range or search term specified, query messages directly
                    if entity_id and (start_date or end_date or search_term):
                        try:
                            from api.services.imessage import query_person_messages
                            print(f"  Querying messages: dates={start_date} to {end_date}, search={search_term}")

                            msg_result = query_person_messages(
                                entity_id=entity_id,
                                search_term=search_term,
                                start_date=start_date,
                                end_date=end_date,
                                limit=150,  # More messages for context
                            )

                            if msg_result["count"] > 0:
                                date_info = ""
                                if msg_result["date_range"]:
                                    dr = msg_result["date_range"]
                                    date_info = f" ({dr['start'][:10]} to {dr['end'][:10]})"

                                extra_context.append({
                                    "source": "imessage",
                                    "content": f"## Text Message History with {person_name}{date_info}\n\n{msg_result['formatted']}",
                                    "count": msg_result["count"],
                                })
                                print(f"  Found {msg_result['count']} messages in range")
                            else:
                                print(f"  No messages found for query")
                        except Exception as e:
                            print(f"  Message query error: {e}")
                            logger.error(f"Failed to query messages for {person_name}: {e}")

                    # Generate briefing (always include for context)
                    try:
                        briefing_service = get_briefings_service()
                        briefing_result = await briefing_service.generate_briefing(
                            person_name,
                            email=person_email
                        )

                        if briefing_result.get("status") == "success":
                            briefing_text = briefing_result.get("briefing", "")
                            extra_context.append({
                                "source": "people_briefing",
                                "content": f"## Stakeholder Briefing: {person_name}\n\n{briefing_text}",
                                "metadata": briefing_result.get("metadata", {})
                            })
                            print(f"  Generated briefing with {briefing_result.get('notes_count', 0)} notes")
                        else:
                            print(f"  Briefing failed: {briefing_result.get('message')}")
                    except Exception as e:
                        print(f"  Briefing generation error: {e}")
                        logger.error(f"Failed to generate briefing for {person_name}: {e}")

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
                # Add iMessage source
                elif ctx.get("source") == "imessage":
                    msg_count = ctx.get("count", 0)
                    sources.insert(0, {  # Put at beginning since it's most relevant
                        'file_name': f"💬 Text Messages ({msg_count} messages)",
                        'source_type': 'imessage',
                    })
                # Add Slack source
                elif ctx.get("source") == "slack":
                    sources.insert(0, {
                        'file_name': "💬 Slack Messages",
                        'source_type': 'slack',
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

            # Use conversation_history we already retrieved earlier for follow-up expansion
            if conversation_history:
                print(f"Including {len(conversation_history)} messages of conversation history for synthesis")

            prompt = construct_prompt(request.question, chunks, conversation_history=conversation_history)

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


def _format_messages_for_synthesis(messages: list, include_sources: bool) -> str:
    """Format conversation messages for synthesis prompt."""
    parts = []
    for msg in messages:
        prefix = "User" if msg.role == "user" else "Assistant"
        parts.append(f"{prefix}: {msg.content}")
        if include_sources and msg.sources:
            sources_str = ", ".join(s.get("file_name", "unknown") for s in msg.sources)
            parts.append(f"[Sources: {sources_str}]")
    return "\n\n".join(parts)


def _format_raw_qa_section(messages: list) -> str:
    """Format raw Q&A section to append to note."""
    parts = ["", "---", "", "## Original Conversation", ""]
    for msg in messages:
        prefix = "**User:**" if msg.role == "user" else "**Assistant:**"
        parts.append(prefix)
        parts.append(msg.content)
        parts.append("")
    return "\n".join(parts)


@router.post("/save-to-vault")
async def save_to_vault(request: SaveToVaultRequest):
    """
    Save conversation to vault as a note.

    Supports two modes:
    1. Full conversation mode: provide conversation_id to save entire thread
    2. Single Q&A mode: provide question and answer (backward compatible)

    Additional options:
    - title: Override auto-generated title
    - folder: Override auto-detected folder
    - tags: Include specific tags in frontmatter
    - guidance: Custom instructions for synthesis
    - include_sources: Include source references in prompt
    - include_raw_qa: Append raw conversation to note
    """
    # Determine content source: conversation or single Q&A
    conversation_text = None
    raw_messages = []

    if request.full_conversation and request.conversation_id:
        # Full conversation mode
        store = get_store()
        messages = store.get_messages(request.conversation_id)
        if not messages:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conversation_text = _format_messages_for_synthesis(messages, request.include_sources)
        raw_messages = messages
    elif request.question and request.answer and request.question.strip() and request.answer.strip():
        # Single Q&A mode (backward compatible)
        conversation_text = f"Question: {request.question}\n\nAnswer: {request.answer}"
        # Create fake message objects for raw Q&A if needed
        from api.services.conversation_store import Message
        raw_messages = [
            Message(id="", conversation_id="", role="user", content=request.question,
                    created_at=datetime.now(), sources=None, routing=None),
            Message(id="", conversation_id="", role="assistant", content=request.answer,
                    created_at=datetime.now(), sources=None, routing=None),
        ]
    else:
        raise HTTPException(
            status_code=400,
            detail="Either conversation_id or both question and answer are required"
        )

    try:
        synthesizer = get_synthesizer()

        # Build synthesis prompt
        prompt_parts = [
            "Based on this conversation, create a well-structured note for my Obsidian vault.",
            "",
            "Conversation:",
            conversation_text,
            "",
        ]

        # Add custom guidance if provided
        if request.guidance:
            prompt_parts.extend([
                "Additional guidance:",
                request.guidance,
                "",
            ])

        # Add tags hint if provided
        if request.tags:
            prompt_parts.extend([
                f"Include these tags in the frontmatter: {', '.join(request.tags)}",
                "",
            ])

        prompt_parts.extend([
            "Create a note with:",
            "1. A clear, concise title (not 'Q&A' or 'Conversation')",
            "2. YAML frontmatter with: created date, source: lifeos, relevant tags",
            "3. A TL;DR section at the top",
            "4. Well-organized content (not just the raw Q&A)",
            "5. Any relevant insights or key takeaways",
            "",
            "Output ONLY the markdown content for the note, starting with the frontmatter.",
        ])

        save_prompt = "\n".join(prompt_parts)

        # Get synthesized note content
        note_content = await synthesizer.get_response(save_prompt)

        # Append raw Q&A if requested
        if request.include_raw_qa and raw_messages:
            note_content += _format_raw_qa_section(raw_messages)

        # Determine title: user override or extract from content
        if request.title:
            title = request.title
        else:
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

        # Determine folder: user override or auto-detect
        if request.folder:
            folder = request.folder
        else:
            folder = "LifeOS/Research"  # Default
            lower_content = note_content.lower()
            if any(word in lower_content for word in ['meeting', 'calendar', 'schedule']):
                folder = "LifeOS/Meetings"
            elif any(word in lower_content for word in ['todo', 'action', 'task']):
                folder = "LifeOS/Actions"
            elif any(word in lower_content for word in ['person', 'about', 'briefing']):
                folder = "LifeOS/People"

        # Write to vault
        vault_path = settings.vault_path
        note_path = vault_path / folder / filename

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(note_content)

        # Return obsidian link
        from urllib.parse import quote
        vault_name = quote(vault_path.name)
        obsidian_url = f"obsidian://open?vault={vault_name}&file={folder}/{filename}"

        return {
            "status": "saved",
            "path": str(note_path),
            "obsidian_url": obsidian_url,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save: {e}")
