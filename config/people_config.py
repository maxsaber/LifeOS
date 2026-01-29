"""
People System Configuration for LifeOS.

Maps email domains to vault contexts and normalizes company names for entity resolution.
"""
from typing import Optional


# Domain → Vault Context Map
# Maps email domains to vault folder paths where people from that organization appear
DOMAIN_CONTEXT_MAP: dict[str, list[str]] = {
    # Current job - Movement Labs
    "movementlabs.xyz": ["Work/ML/"],
    "movementlabs.com": ["Work/ML/"],

    # Previous jobs (archived)
    "murmuration.org": ["Personal/zArchive/Murm/"],
    "bluelabs.com": ["Personal/zArchive/BlueLabs/"],
    "bluelabs.io": ["Personal/zArchive/BlueLabs/"],
    "decktech.com": ["Personal/zArchive/Deck/"],
    "rise.com": ["Personal/zArchive/Rise/"],

    # Personal domains
    "gmail.com": ["Personal/"],
    "icloud.com": ["Personal/"],
}


# Company Normalization Map
# Maps LinkedIn company names to email domains and vault contexts
# Used to link LinkedIn records (which have company names) to email-based records
COMPANY_NORMALIZATION: dict[str, dict] = {
    "Movement Labs": {
        "domains": ["movementlabs.xyz", "movementlabs.com"],
        "vault_contexts": ["Work/ML/"],
    },
    "Murmuration": {
        "domains": ["murmuration.org"],
        "vault_contexts": ["Personal/zArchive/Murm/"],
    },
    "BlueLabs": {
        "domains": ["bluelabs.com", "bluelabs.io"],
        "vault_contexts": ["Personal/zArchive/BlueLabs/"],
    },
    "BlueLabs Analytics": {
        "domains": ["bluelabs.com", "bluelabs.io"],
        "vault_contexts": ["Personal/zArchive/BlueLabs/"],
    },
    "Deck": {
        "domains": ["decktech.com"],
        "vault_contexts": ["Personal/zArchive/Deck/"],
    },
    "Rise": {
        "domains": ["rise.com"],
        "vault_contexts": ["Personal/zArchive/Rise/"],
    },
}


# Entity Resolution Configuration
class EntityResolutionConfig:
    """Configuration for entity resolution algorithm."""

    # Fuzzy matching thresholds
    NAME_SIMILARITY_WEIGHT: float = 0.4  # Weight for name similarity score (0-1)
    CONTEXT_BOOST_POINTS: int = 30       # Points added when domain matches vault context
    RECENCY_BOOST_POINTS: int = 10       # Points added for recently seen people
    RECENCY_THRESHOLD_DAYS: int = 30     # Days to consider "recent"

    # Disambiguation threshold
    # If top two candidates score within this many points, create separate entities
    DISAMBIGUATION_THRESHOLD: int = 15

    # Minimum score to consider a match
    MIN_MATCH_SCORE: float = 40.0

    # Cache settings
    QUERY_CACHE_TTL_SECONDS: int = 1800  # 30 minutes


# Interaction Log Configuration
class InteractionConfig:
    """Configuration for interaction tracking."""

    # Default time window for interaction queries
    DEFAULT_WINDOW_DAYS: int = 365

    # Maximum time window allowed for timeline queries (10 years)
    MAX_WINDOW_DAYS: int = 3650

    # Maximum interactions to return in a single query
    MAX_INTERACTIONS_PER_QUERY: int = 100

    # Snippet length for interaction preview
    SNIPPET_LENGTH: int = 100


def get_vault_contexts_for_domain(domain: str) -> list[str]:
    """
    Get vault contexts associated with an email domain.

    Args:
        domain: Email domain (e.g., "movementlabs.xyz")

    Returns:
        List of vault context paths, or empty list if domain unknown
    """
    return DOMAIN_CONTEXT_MAP.get(domain.lower(), [])


def get_domains_for_company(company_name: str) -> list[str]:
    """
    Get email domains associated with a company name.

    Args:
        company_name: Company name from LinkedIn (e.g., "Movement Labs")

    Returns:
        List of email domains, or empty list if company unknown
    """
    company_info = COMPANY_NORMALIZATION.get(company_name, {})
    return company_info.get("domains", [])


def get_vault_contexts_for_company(company_name: str) -> list[str]:
    """
    Get vault contexts associated with a company name.

    Args:
        company_name: Company name from LinkedIn (e.g., "Movement Labs")

    Returns:
        List of vault context paths, or empty list if company unknown
    """
    company_info = COMPANY_NORMALIZATION.get(company_name, {})
    return company_info.get("vault_contexts", [])


def normalize_domain(email: str) -> Optional[str]:
    """
    Extract and normalize domain from email address.

    Args:
        email: Full email address

    Returns:
        Lowercase domain, or None if invalid email
    """
    if not email or "@" not in email:
        return None
    return email.split("@")[1].lower()
