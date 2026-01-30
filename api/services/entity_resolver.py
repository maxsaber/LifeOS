"""
Entity Resolver for LifeOS People System v2.

Implements three-pass entity resolution:
1. Email anchoring - exact email match across sources
2. Fuzzy name matching with context boost - for names without email
3. Disambiguation - create separate entities when ambiguous
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

from api.services.person_entity import PersonEntity, PersonEntityStore, get_person_entity_store
from api.services.people import resolve_person_name, PEOPLE_DICTIONARY
from api.services.link_override import get_link_override_store
from config.people_config import (
    DOMAIN_CONTEXT_MAP,
    COMPANY_NORMALIZATION,
    EntityResolutionConfig,
    get_vault_contexts_for_domain,
    get_domains_for_company,
    get_vault_contexts_for_company,
    normalize_domain,
)
from config.relationship_weights import (
    RELATIONSHIP_STRENGTH_BOOST_MAX,
    RELATIONSHIP_STRENGTH_BOOST_WEIGHT,
    FIRST_NAME_ONLY_BOOST_MULTIPLIER,
)
from config.settings import settings

logger = logging.getLogger(__name__)


def _make_aware(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class ResolutionCandidate:
    """A potential match for entity resolution."""

    entity: PersonEntity
    score: float
    match_type: str  # "email_exact", "name_fuzzy", "alias_exact"
    confidence: float  # 0.0-1.0


@dataclass
class ResolutionResult:
    """Result of entity resolution."""

    entity: PersonEntity
    is_new: bool  # True if a new entity was created
    confidence: float
    match_type: str
    disambiguation_applied: bool = False


class EntityResolver:
    """
    Resolves names/emails to PersonEntity instances.

    Uses a three-pass algorithm:
    1. Email anchoring (exact match)
    2. Fuzzy name matching with context boost
    3. Disambiguation for ambiguous cases
    """

    def __init__(self, entity_store: Optional[PersonEntityStore] = None):
        """
        Initialize the resolver.

        Args:
            entity_store: PersonEntityStore to use (default singleton)
        """
        self._store = entity_store or get_person_entity_store()

    @property
    def store(self) -> PersonEntityStore:
        """Get the entity store."""
        return self._store

    def resolve_by_email(self, email: str) -> Optional[PersonEntity]:
        """
        Pass 1: Exact email match.

        Args:
            email: Email address to look up

        Returns:
            PersonEntity if found, None otherwise
        """
        if not email:
            return None
        return self._store.get_by_email(email.lower())

    def resolve_by_phone(self, phone: str) -> Optional[PersonEntity]:
        """
        Phone anchor: Exact phone match (E.164 format).

        Args:
            phone: Phone number in E.164 format (+1XXXXXXXXXX)

        Returns:
            PersonEntity if found, None otherwise
        """
        if not phone:
            return None
        return self._store.get_by_phone(phone)

    def resolve_by_name(
        self,
        name: str,
        context_path: Optional[str] = None,
        create_if_missing: bool = False,
    ) -> Optional[ResolutionResult]:
        """
        Pass 2 & 3: Fuzzy name matching with context boost and disambiguation.

        Args:
            name: Name to resolve (will be canonicalized)
            context_path: Vault path for context boost (e.g., "Work/ML/meeting.md")
            create_if_missing: Create new entity if no match found

        Returns:
            ResolutionResult with matched/created entity, or None
        """
        if not name or not name.strip():
            return None

        # First, try to canonicalize using existing PEOPLE_DICTIONARY
        canonical = resolve_person_name(name)

        # Check for exact name/alias match in store
        exact_match = self._store.get_by_name(canonical)
        if exact_match:
            return ResolutionResult(
                entity=exact_match,
                is_new=False,
                confidence=1.0,
                match_type="name_exact",
            )

        # Check for link override (disambiguation rules from previous splits)
        override_store = get_link_override_store()
        override = override_store.find_matching(
            name=canonical,
            source_type=None,  # Will be passed in enhanced version
            context_path=context_path,
        )
        if override:
            preferred = self._store.get_by_id(override.preferred_person_id)
            if preferred:
                logger.debug(f"Link override matched: '{canonical}' -> {preferred.canonical_name}")
                return ResolutionResult(
                    entity=preferred,
                    is_new=False,
                    confidence=1.0,
                    match_type="link_override",
                )

        # Score all candidates using fuzzy matching
        candidates = self._score_candidates(canonical, context_path)

        if not candidates:
            if create_if_missing:
                return self._create_new_entity(canonical, context_path)
            return None

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)

        top = candidates[0]

        # Check if score meets minimum threshold
        if top.score < EntityResolutionConfig.MIN_MATCH_SCORE:
            if create_if_missing:
                return self._create_new_entity(canonical, context_path)
            return None

        # Check for disambiguation (Pass 3)
        if len(candidates) >= 2:
            second = candidates[1]
            score_diff = top.score - second.score

            if score_diff < EntityResolutionConfig.DISAMBIGUATION_THRESHOLD:
                # Ambiguous - check if we should create a new entity
                if create_if_missing:
                    return self._create_disambiguated_entity(
                        canonical, context_path, top.entity
                    )
                # Otherwise return top match with lower confidence
                return ResolutionResult(
                    entity=top.entity,
                    is_new=False,
                    confidence=top.confidence * 0.7,  # Reduce confidence for ambiguous
                    match_type="fuzzy_ambiguous",
                    disambiguation_applied=True,
                )

        return ResolutionResult(
            entity=top.entity,
            is_new=False,
            confidence=top.confidence,
            match_type=top.match_type,
        )

    def _score_candidates(
        self, name: str, context_path: Optional[str]
    ) -> list[ResolutionCandidate]:
        """
        Score all entities against a name.

        Args:
            name: Name to match against
            context_path: Path for context boost

        Returns:
            List of candidates with scores
        """
        candidates = []
        name_lower = name.lower()

        # Check if this is a first-name-only match (single word, no spaces)
        # First-name mentions in notes usually refer to close contacts
        is_first_name_only = ' ' not in name.strip()

        for entity in self._store.get_all():
            score = 0.0
            match_type = "fuzzy"

            # Name similarity (using token_set_ratio for best partial matching)
            name_sim = fuzz.token_set_ratio(name_lower, entity.canonical_name.lower())
            score += name_sim * EntityResolutionConfig.NAME_SIMILARITY_WEIGHT

            # Also check aliases
            for alias in entity.aliases:
                alias_sim = fuzz.token_set_ratio(name_lower, alias.lower())
                if alias_sim > name_sim:
                    name_sim = alias_sim
                    score = alias_sim * EntityResolutionConfig.NAME_SIMILARITY_WEIGHT

            # Context boost
            if context_path and entity.vault_contexts:
                if self._path_matches_context(context_path, entity.vault_contexts):
                    score += EntityResolutionConfig.CONTEXT_BOOST_POINTS
                    match_type = "fuzzy_context"

            # Recency boost
            if entity.last_seen:
                days_since = (datetime.now(timezone.utc) - _make_aware(entity.last_seen)).days
                if days_since < EntityResolutionConfig.RECENCY_THRESHOLD_DAYS:
                    score += EntityResolutionConfig.RECENCY_BOOST_POINTS

            # Relationship strength boost
            # People you have strong relationships with are more likely to be
            # mentioned by first name in your notes
            rel_strength = entity.relationship_strength  # 0-100 scale
            if rel_strength > 0:
                # Calculate boost: strength (0-100) * weight -> points (0-25 default)
                rel_boost = min(
                    rel_strength * RELATIONSHIP_STRENGTH_BOOST_WEIGHT,
                    RELATIONSHIP_STRENGTH_BOOST_MAX
                )
                # Apply stronger boost for first-name-only matches
                if is_first_name_only:
                    rel_boost *= FIRST_NAME_ONLY_BOOST_MULTIPLIER
                score += rel_boost
                if rel_boost > 5:  # Significant boost
                    match_type = "fuzzy_relationship" if match_type == "fuzzy" else f"{match_type}_relationship"

            # Only add if there's meaningful similarity
            if name_sim > 50:  # At least 50% name match
                confidence = min(score / 100.0, 1.0)
                candidates.append(
                    ResolutionCandidate(
                        entity=entity,
                        score=score,
                        match_type=match_type,
                        confidence=confidence,
                    )
                )

        return candidates

    def _path_matches_context(
        self, file_path: str, vault_contexts: list[str]
    ) -> bool:
        """
        Check if a file path matches any of the vault contexts.

        Args:
            file_path: Path to check (e.g., "/Users/x/Notes 2025/Work/ML/meeting.md")
            vault_contexts: List of context prefixes (e.g., ["Work/ML/"])

        Returns:
            True if path is within any context
        """
        # Normalize path
        path_str = str(file_path).replace("\\", "/")

        for context in vault_contexts:
            context_normalized = context.replace("\\", "/")
            if context_normalized in path_str:
                return True

        return False

    def _create_new_entity(
        self, name: str, context_path: Optional[str]
    ) -> ResolutionResult:
        """
        Create a new PersonEntity for an unknown name.

        Args:
            name: Canonical name
            context_path: Path for inferring vault context

        Returns:
            ResolutionResult with new entity
        """
        vault_contexts = []
        category = "unknown"

        if context_path:
            # Try to infer vault context from path
            vault_contexts = self._infer_vault_contexts(context_path)
            category = self._infer_category(context_path)

        entity = PersonEntity(
            canonical_name=name,
            display_name=name,
            vault_contexts=vault_contexts,
            category=category,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )

        stored = self._store.add(entity)

        return ResolutionResult(
            entity=stored,
            is_new=True,
            confidence=0.5,  # Lower confidence for new entities
            match_type="new_entity",
        )

    def _create_disambiguated_entity(
        self, name: str, context_path: Optional[str], similar_entity: PersonEntity
    ) -> ResolutionResult:
        """
        Create a disambiguated entity when name is ambiguous.

        Args:
            name: Canonical name
            context_path: Path for inferring context
            similar_entity: The entity this would be confused with

        Returns:
            ResolutionResult with disambiguated entity
        """
        vault_contexts = []
        category = "unknown"
        suffix = ""

        if context_path:
            vault_contexts = self._infer_vault_contexts(context_path)
            category = self._infer_category(context_path)
            suffix = self._infer_context_suffix(context_path)

        # Create display name with disambiguation
        display_name = f"{name} ({suffix})" if suffix else name

        entity = PersonEntity(
            canonical_name=name,
            display_name=display_name,
            vault_contexts=vault_contexts,
            category=category,
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            confidence_score=0.7,  # Slightly lower for disambiguated
        )

        stored = self._store.add(entity)

        return ResolutionResult(
            entity=stored,
            is_new=True,
            confidence=0.7,
            match_type="disambiguated",
            disambiguation_applied=True,
        )

    def _infer_vault_contexts(self, file_path: str) -> list[str]:
        """Infer vault context from file path."""
        path_str = str(file_path).replace("\\", "/")

        # Check known context patterns
        if "Work/ML" in path_str:
            return ["Work/ML/"]
        elif "Personal/zArchive/Murm" in path_str:
            return ["Personal/zArchive/Murm/"]
        elif "Personal/zArchive/BlueLabs" in path_str:
            return ["Personal/zArchive/BlueLabs/"]
        elif "Personal/" in path_str:
            return ["Personal/"]
        elif "Work/" in path_str:
            return ["Work/"]

        return []

    def _infer_category(self, file_path: str) -> str:
        """Infer category from file path."""
        path_str = str(file_path).replace("\\", "/")

        if "Work/" in path_str:
            return "work"
        elif "Personal/Relationship" in path_str or "Personal/Malea" in path_str:
            return "family"
        elif "Personal/" in path_str:
            return "personal"

        return "unknown"

    def _infer_context_suffix(self, file_path: str) -> str:
        """Infer disambiguation suffix from file path."""
        path_str = str(file_path).replace("\\", "/")

        if "Work/ML" in path_str:
            return "Movement"
        elif "Personal/zArchive/Murm" in path_str:
            return "Murmuration"
        elif "Personal/zArchive/BlueLabs" in path_str:
            return "BlueLabs"
        elif "Personal/zArchive/Deck" in path_str:
            return "Deck"
        elif "Work/" in path_str:
            return "Work"
        elif "Personal/" in path_str:
            return "Personal"

        return ""

    def resolve(
        self,
        name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        context_path: Optional[str] = None,
        create_if_missing: bool = False,
    ) -> Optional[ResolutionResult]:
        """
        Main entry point: resolve a person by name, email, and/or phone.

        Priority:
        1. Email exact match (if email provided)
        2. Phone exact match (if phone provided, E.164 format)
        3. Name exact match
        4. Fuzzy name match with context boost
        5. Create new entity (if create_if_missing)

        Args:
            name: Person's name
            email: Person's email
            phone: Person's phone (E.164 format, e.g., +1XXXXXXXXXX)
            context_path: Vault path for context boost
            create_if_missing: Create new entity if not found

        Returns:
            ResolutionResult or None
        """
        # Pass 1: Email exact match
        if email:
            entity = self.resolve_by_email(email)
            if entity:
                return ResolutionResult(
                    entity=entity,
                    is_new=False,
                    confidence=1.0,
                    match_type="email_exact",
                )

        # Pass 1b: Phone exact match
        if phone:
            entity = self.resolve_by_phone(phone)
            if entity:
                return ResolutionResult(
                    entity=entity,
                    is_new=False,
                    confidence=1.0,
                    match_type="phone_exact",
                )

        # Pass 2 & 3: Name matching
        if name:
            result = self.resolve_by_name(
                name, context_path, create_if_missing=create_if_missing
            )
            if result:
                # If we also have email/phone, add them to the entity
                updated = False
                if email and result.is_new:
                    result.entity.add_email(email)
                    updated = True
                if phone and result.is_new:
                    result.entity.add_phone(phone)
                    updated = True
                if updated:
                    self._store.update(result.entity)
                return result

        # If we have email but no name match, create entity from email
        if email and create_if_missing:
            name_from_email = self._extract_name_from_email(email)
            domain = normalize_domain(email)
            vault_contexts = get_vault_contexts_for_domain(domain) if domain else []
            category = "work" if vault_contexts else "unknown"

            entity = PersonEntity(
                canonical_name=name_from_email,
                display_name=name_from_email,
                emails=[email.lower()],
                phone_numbers=[phone] if phone else [],
                phone_primary=phone,
                vault_contexts=vault_contexts,
                category=category,
                first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
            )

            stored = self._store.add(entity)

            return ResolutionResult(
                entity=stored,
                is_new=True,
                confidence=0.6,
                match_type="email_new",
            )

        return None

    def _extract_name_from_email(self, email: str) -> str:
        """
        Extract a display name from an email address.

        Args:
            email: Email address

        Returns:
            Best-guess name from email prefix
        """
        if not email or "@" not in email:
            return email or "Unknown"

        prefix = email.split("@")[0]

        # Handle common patterns
        # john.doe@... -> John Doe
        # johndoe@... -> Johndoe
        # john_doe@... -> John Doe
        # jdoe@... -> Jdoe

        # Replace separators with spaces
        name = re.sub(r"[._-]", " ", prefix)

        # Title case
        name = name.title()

        return name

    def resolve_from_linkedin(
        self,
        first_name: str,
        last_name: str,
        email: Optional[str],
        company: Optional[str],
        position: Optional[str],
        linkedin_url: Optional[str],
    ) -> ResolutionResult:
        """
        Resolve a person from LinkedIn data.

        Uses company normalization to infer email domains and vault contexts.

        Args:
            first_name: First name from LinkedIn
            last_name: Last name from LinkedIn
            email: Email if available
            company: Company name from LinkedIn
            position: Position/title
            linkedin_url: LinkedIn profile URL

        Returns:
            ResolutionResult with matched/created entity
        """
        full_name = f"{first_name} {last_name}".strip()

        # Try email first
        if email:
            entity = self.resolve_by_email(email)
            if entity:
                # Update with LinkedIn data
                entity.linkedin_url = linkedin_url or entity.linkedin_url
                entity.company = company or entity.company
                entity.position = position or entity.position
                if "linkedin" not in entity.sources:
                    entity.sources.append("linkedin")
                self._store.update(entity)

                return ResolutionResult(
                    entity=entity,
                    is_new=False,
                    confidence=1.0,
                    match_type="email_exact",
                )

        # Try to infer email domain from company
        vault_contexts = []
        if company:
            domains = get_domains_for_company(company)
            vault_contexts = get_vault_contexts_for_company(company)

            # Try to find existing entity by domain match
            for domain in domains:
                for entity in self._store.get_all():
                    for ent_email in entity.emails:
                        if ent_email.endswith(f"@{domain}"):
                            # Check if name matches
                            name_sim = fuzz.token_set_ratio(
                                full_name.lower(), entity.canonical_name.lower()
                            )
                            if name_sim > 80:
                                # Update with LinkedIn data
                                entity.linkedin_url = linkedin_url or entity.linkedin_url
                                entity.company = company or entity.company
                                entity.position = position or entity.position
                                if "linkedin" not in entity.sources:
                                    entity.sources.append("linkedin")
                                self._store.update(entity)

                                return ResolutionResult(
                                    entity=entity,
                                    is_new=False,
                                    confidence=0.85,
                                    match_type="linkedin_domain_match",
                                )

        # Try name matching
        result = self.resolve_by_name(full_name, create_if_missing=False)
        if result:
            entity = result.entity
            entity.linkedin_url = linkedin_url or entity.linkedin_url
            entity.company = company or entity.company
            entity.position = position or entity.position
            if "linkedin" not in entity.sources:
                entity.sources.append("linkedin")
            self._store.update(entity)
            return result

        # Create new entity
        category = "work" if vault_contexts else "unknown"

        entity = PersonEntity(
            canonical_name=full_name,
            display_name=full_name,
            emails=[email.lower()] if email else [],
            company=company,
            position=position,
            linkedin_url=linkedin_url,
            vault_contexts=vault_contexts,
            category=category,
            sources=["linkedin"],
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
        )

        stored = self._store.add(entity)

        return ResolutionResult(
            entity=stored,
            is_new=True,
            confidence=0.8,
            match_type="linkedin_new",
        )


# Singleton instance
_entity_resolver: Optional[EntityResolver] = None


def get_entity_resolver(
    entity_store: Optional[PersonEntityStore] = None,
) -> EntityResolver:
    """
    Get or create the singleton EntityResolver.

    Args:
        entity_store: PersonEntityStore to use

    Returns:
        EntityResolver instance
    """
    global _entity_resolver
    if _entity_resolver is None:
        _entity_resolver = EntityResolver(entity_store)
    return _entity_resolver
