"""
Briefings service for LifeOS.

Generates stakeholder briefings by aggregating:
- People metadata from PeopleAggregator (v1) or EntityResolver (v2)
- Vault notes mentioning the person
- Action items involving the person
- Calendar meetings with the person
- Interaction history (v2)
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field

from api.services.people import resolve_person_name, PEOPLE_DICTIONARY
from api.services.people_aggregator import PeopleAggregator, get_people_aggregator
from api.services.vectorstore import VectorStore
from api.services.actions import ActionRegistry, get_action_registry
from api.services.synthesizer import get_synthesizer

# v2 imports - these may not be populated yet
try:
    from api.services.entity_resolver import EntityResolver, get_entity_resolver
    from api.services.interaction_store import InteractionStore, get_interaction_store
    HAS_V2_PEOPLE = True
except ImportError:
    HAS_V2_PEOPLE = False

logger = logging.getLogger(__name__)


@dataclass
class BriefingContext:
    """Context gathered for a stakeholder briefing."""
    person_name: str
    resolved_name: str
    email: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    category: str = "unknown"  # work, personal, family
    linkedin_url: Optional[str] = None  # v2: LinkedIn profile

    # Interaction metrics
    meeting_count: int = 0
    email_count: int = 0
    mention_count: int = 0
    last_interaction: Optional[datetime] = None

    # Content
    related_notes: list[dict] = field(default_factory=list)
    action_items: list[dict] = field(default_factory=list)
    recent_context: list[str] = field(default_factory=list)

    # v2: Interaction history (formatted markdown)
    interaction_history: str = ""

    # Sources
    sources: list[str] = field(default_factory=list)

    # v2: Entity ID for linking
    entity_id: Optional[str] = None


BRIEFING_PROMPT = """You are LifeOS, preparing a stakeholder briefing for Nathan.

Generate a concise, actionable briefing about {person_name} based on the context below.

## Person Metadata
- Name: {resolved_name}
- Email: {email}
- Company: {company}
- Position: {position}
- Category: {category}
- LinkedIn: {linkedin_url}
- Meetings (90 days): {meeting_count}
- Emails (90 days): {email_count}
- Note mentions: {mention_count}
- Last interaction: {last_interaction}

## Interaction History
{interaction_history}

## Related Notes
{related_notes_text}

## Action Items
{action_items_text}

---

Generate a briefing in this exact format:

## {resolved_name} — Briefing

**Role/Relationship:** [Infer from notes and metadata - be specific]
**Last Interaction:** [Date and brief context if available]
**Interaction Frequency:** {meeting_count} meetings in past 90 days
{linkedin_line}

### Interaction Timeline
[If interaction history is available, summarize recent touchpoints: emails, meetings, note mentions]
[If not available, omit this section]

### Recent Context
- [2-4 bullet points of key recent information from notes]

### Open Items
- [Any action items involving this person]
- [Decisions pending with them]
- [If none, say "No open items found"]

### Relationship Notes
- [Any personal context from notes: preferences, communication style, shared history]
- [If none found, omit this section]

### Suggested Topics
- [2-3 topics to discuss based on open items and recent context]

---
Sources: [list source files]

Keep it concise and actionable. Focus on what Nathan needs to know for his next interaction."""


class BriefingsService:
    """Service for generating stakeholder briefings."""

    def __init__(
        self,
        people_aggregator: Optional[PeopleAggregator] = None,
        vector_store: Optional[VectorStore] = None,
        action_registry: Optional[ActionRegistry] = None,
        entity_resolver: Optional["EntityResolver"] = None,
        interaction_store: Optional["InteractionStore"] = None,
    ):
        """Initialize briefings service."""
        self._people_aggregator = people_aggregator
        self._vector_store = vector_store
        self._action_registry = action_registry
        self._entity_resolver = entity_resolver
        self._interaction_store = interaction_store

    @property
    def people_aggregator(self) -> PeopleAggregator:
        """Lazy-load people aggregator."""
        if self._people_aggregator is None:
            self._people_aggregator = get_people_aggregator()
        return self._people_aggregator

    @property
    def vector_store(self) -> VectorStore:
        """Lazy-load vector store."""
        if self._vector_store is None:
            self._vector_store = VectorStore()
        return self._vector_store

    @property
    def action_registry(self) -> ActionRegistry:
        """Lazy-load action registry."""
        if self._action_registry is None:
            self._action_registry = get_action_registry()
        return self._action_registry

    @property
    def entity_resolver(self) -> Optional["EntityResolver"]:
        """Lazy-load entity resolver (v2)."""
        if self._entity_resolver is None and HAS_V2_PEOPLE:
            try:
                self._entity_resolver = get_entity_resolver()
            except Exception as e:
                logger.debug(f"EntityResolver not available: {e}")
        return self._entity_resolver

    @property
    def interaction_store(self) -> Optional["InteractionStore"]:
        """Lazy-load interaction store (v2)."""
        if self._interaction_store is None and HAS_V2_PEOPLE:
            try:
                self._interaction_store = get_interaction_store()
            except Exception as e:
                logger.debug(f"InteractionStore not available: {e}")
        return self._interaction_store

    def gather_context(self, person_name: str, email: Optional[str] = None) -> Optional[BriefingContext]:
        """
        Gather all context about a person.

        Args:
            person_name: Name to look up (will be resolved)
            email: Optional email for better resolution (v2)

        Returns:
            BriefingContext with all gathered data, or None if person unknown
        """
        # Resolve the person name using v1 system
        resolved = resolve_person_name(person_name)
        if not resolved:
            resolved = person_name.title()

        # Initialize context
        context = BriefingContext(
            person_name=person_name,
            resolved_name=resolved,
        )

        # Try v2 EntityResolver first (if available)
        entity = None
        if self.entity_resolver:
            try:
                result = self.entity_resolver.resolve(name=resolved, email=email)
                if result:
                    entity = result.entity
                    context.entity_id = entity.id
                    context.resolved_name = entity.display_name or entity.canonical_name
                    context.email = entity.emails[0] if entity.emails else None
                    context.company = entity.company
                    context.position = entity.position
                    context.category = entity.category
                    context.linkedin_url = entity.linkedin_url
                    context.meeting_count = entity.meeting_count
                    context.email_count = entity.email_count
                    context.mention_count = entity.mention_count
                    context.last_interaction = entity.last_seen
                    context.sources.extend(entity.sources)
                    logger.debug(f"Resolved {person_name} via EntityResolver: {entity.canonical_name}")
            except Exception as e:
                logger.warning(f"Could not use EntityResolver: {e}")

        # Fall back to v1 PeopleAggregator if no entity found
        if not entity:
            try:
                results = self.people_aggregator.search(resolved)
                if results:
                    person_record = results[0]
                    context.email = person_record.email
                    context.company = person_record.company
                    context.position = person_record.position
                    context.category = person_record.category
                    context.meeting_count = person_record.meeting_count
                    context.email_count = person_record.email_count
                    context.mention_count = person_record.mention_count
                    context.last_interaction = person_record.last_seen
                    context.sources.extend(person_record.sources)
                    logger.debug(f"Resolved {person_name} via PeopleAggregator")
            except Exception as e:
                logger.warning(f"Could not search people aggregator: {e}")

        # Get interaction history from v2 InteractionStore (if available and entity found)
        if self.interaction_store and context.entity_id:
            try:
                context.interaction_history = self.interaction_store.format_interaction_history(
                    context.entity_id, days_back=90, limit=20
                )
            except Exception as e:
                logger.warning(f"Could not get interaction history: {e}")

        # Search vault for mentions
        # v2: Always search, removing the PEOPLE_DICTIONARY restriction
        try:
            # Try with people filter first if name is known
            filters = None
            if resolved in PEOPLE_DICTIONARY:
                filters = {"people": [resolved]}

            chunks = self.vector_store.search(
                query=resolved,
                top_k=15,
                filters=filters
            )

            # If no results with filter, try without filter
            if not chunks and filters:
                chunks = self.vector_store.search(
                    query=resolved,
                    top_k=15,
                    filters=None
                )

            for chunk in chunks:
                context.related_notes.append({
                    "file_name": chunk.get("metadata", {}).get("file_name", "Unknown"),
                    "file_path": chunk.get("metadata", {}).get("file_path", ""),
                    "content": chunk.get("content", "")[:500],  # Truncate for prompt
                    "score": chunk.get("score", 0),
                })
                file_name = chunk.get("metadata", {}).get("file_name", "")
                if file_name and file_name not in context.sources:
                    context.sources.append(file_name)
        except Exception as e:
            logger.warning(f"Could not search vault: {e}")

        # Get action items involving person
        try:
            actions = self.action_registry.get_actions_involving_person(resolved)
            for action in actions[:10]:  # Limit to 10
                context.action_items.append({
                    "task": action.task,
                    "owner": action.owner,
                    "completed": action.completed,
                    "due_date": action.due_date.isoformat() if action.due_date else None,
                    "source_file": action.source_file,
                })
        except Exception as e:
            logger.warning(f"Could not get action items: {e}")

        return context

    async def generate_briefing(self, person_name: str, email: Optional[str] = None) -> dict:
        """
        Generate a stakeholder briefing.

        Args:
            person_name: Name of person to brief on
            email: Optional email for better resolution (v2)

        Returns:
            Dict with briefing content and metadata
        """
        # Gather context
        context = self.gather_context(person_name, email=email)

        if not context:
            return {
                "status": "not_found",
                "message": f"I don't have any notes about {person_name}.",
                "person_name": person_name,
            }

        # Check if we have any data
        if not context.related_notes and not context.action_items and not context.email:
            return {
                "status": "limited",
                "message": f"I have limited information about {context.resolved_name}. They appear in my records but I don't have detailed notes.",
                "person_name": context.resolved_name,
                "sources": context.sources,
            }

        # Format related notes for prompt
        related_notes_text = "\n\n".join([
            f"**{note['file_name']}:**\n{note['content']}"
            for note in context.related_notes[:10]  # Limit for prompt size
        ]) or "No related notes found."

        # Format action items for prompt
        action_items_text = "\n".join([
            f"- [{('x' if item['completed'] else ' ')}] {item['task']} (Owner: {item['owner'] or 'Unassigned'})"
            for item in context.action_items
        ]) or "No action items found."

        # Format interaction history
        interaction_history = context.interaction_history or "_No interaction history available._"

        # Format LinkedIn line for output
        linkedin_line = ""
        if context.linkedin_url:
            linkedin_line = f"**LinkedIn:** [{context.resolved_name}]({context.linkedin_url})"

        # Build prompt
        prompt = BRIEFING_PROMPT.format(
            person_name=context.person_name,
            resolved_name=context.resolved_name,
            email=context.email or "Unknown",
            company=context.company or "Unknown",
            position=context.position or "Unknown",
            category=context.category,
            linkedin_url=context.linkedin_url or "N/A",
            meeting_count=context.meeting_count,
            email_count=context.email_count,
            mention_count=context.mention_count,
            last_interaction=context.last_interaction.strftime("%Y-%m-%d") if context.last_interaction else "Unknown",
            interaction_history=interaction_history,
            related_notes_text=related_notes_text,
            action_items_text=action_items_text,
            linkedin_line=linkedin_line,
        )

        # Generate briefing with Claude
        try:
            synthesizer = get_synthesizer()
            briefing_content = await synthesizer.get_response(prompt, max_tokens=2048)

            return {
                "status": "success",
                "briefing": briefing_content,
                "person_name": context.resolved_name,
                "metadata": {
                    "email": context.email,
                    "company": context.company,
                    "position": context.position,
                    "linkedin_url": context.linkedin_url,
                    "meeting_count": context.meeting_count,
                    "email_count": context.email_count,
                    "mention_count": context.mention_count,
                    "last_interaction": context.last_interaction.isoformat() if context.last_interaction else None,
                    "entity_id": context.entity_id,
                },
                "sources": context.sources,
                "action_items_count": len(context.action_items),
                "notes_count": len(context.related_notes),
            }
        except Exception as e:
            logger.error(f"Failed to generate briefing: {e}")
            return {
                "status": "error",
                "message": f"Failed to generate briefing: {str(e)}",
                "person_name": context.resolved_name,
            }


# Singleton
_briefings_service: Optional[BriefingsService] = None


def get_briefings_service() -> BriefingsService:
    """Get or create briefings service singleton."""
    global _briefings_service
    if _briefings_service is None:
        _briefings_service = BriefingsService()
    return _briefings_service
