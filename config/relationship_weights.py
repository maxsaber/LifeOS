"""
Relationship and Entity Resolution Weights Configuration.

Central configuration for all weights used in:
- Relationship strength calculation
- Entity resolution scoring
- Interaction type weighting

Edit this file to tune relationship scoring behavior.
"""

# =============================================================================
# RELATIONSHIP STRENGTH WEIGHTS
# =============================================================================
# Formula: strength = (recency × RECENCY_WEIGHT) + (frequency × FREQUENCY_WEIGHT) + (diversity × DIVERSITY_WEIGHT)

RECENCY_WEIGHT = 0.30     # How much recent contact matters
FREQUENCY_WEIGHT = 0.60   # How much total interaction volume matters
DIVERSITY_WEIGHT = 0.10   # How much multi-channel communication matters

# Parameters for component scores
RECENCY_WINDOW_DAYS = 200     # Days after which recency score drops to 0
FREQUENCY_TARGET = 250        # Weighted interactions for max frequency score (higher = better spread)
FREQUENCY_WINDOW_DAYS = 365   # Window for counting recent interactions

# Weekly digest thresholds
RECENT_INTERACTION_DAYS = 7  # Weekly window for recent interactions
SLIPPING_DAYS = 30           # Days since last interaction to mark as slipping
REACHOUT_DAYS = 45           # Days since last interaction to suggest a reach-out

# Logarithmic frequency scaling - spreads out scores between casual and close contacts
# With log scaling: log(1+count)/log(1+target) instead of count/target
USE_LOG_FREQUENCY_SCALING = True

# Lifetime frequency component - ensures historical relationships don't completely vanish
# Combines: (recent_freq * RECENT_WEIGHT) + (lifetime_freq * LIFETIME_WEIGHT)
LIFETIME_FREQUENCY_ENABLED = True
LIFETIME_FREQUENCY_WEIGHT = 0.3   # 30% of frequency score from lifetime interactions
RECENT_FREQUENCY_WEIGHT = 0.7    # 70% of frequency score from recent (365-day) interactions
LIFETIME_FREQUENCY_TARGET = 750  # Higher target for all-time (harder to max out)

# Recency discount for zero-interaction contacts
# People with no tracked interactions get NO recency credit
# (contacts list and LinkedIn connections shouldn't inflate scores)
MIN_INTERACTIONS_FOR_FULL_RECENCY = 3  # Need at least 3 interactions for full recency credit
ZERO_INTERACTION_RECENCY_MULTIPLIER = 0.0  # Zero interactions = 0% recency (contacts/LinkedIn don't count)

# Peripheral contact threshold
# People with relationship_strength below this are marked as peripheral contacts
# and excluded from expensive aggregation calculations (placed in Dunbar circle 7)
PERIPHERAL_THRESHOLD = 3.0


# =============================================================================
# MANUAL STRENGTH OVERRIDES
# =============================================================================
# Force specific people to have a fixed relationship strength regardless of
# calculated value. These also affect Dunbar circle placement.
# Keys are person IDs (UUIDs), values are strength (0-100).

STRENGTH_OVERRIDES_BY_ID = {
    "cb93e7bd-036c-4ef5-adb9-34a9147c4984": 100.0,  # Taylor Walker
    "23b9aca8-8817-494a-a13e-7d7799f9b282": 100.0,  # Malea Ramia
    "3f41e143-719f-4dc9-a9f1-389b2db5b166": 100.0,  # Nathan Ramia (self)
    "04bf94f8-20b7-4285-abb4-c64131b5542f": 90.0,   # Thy Nguyen
}

# Manual Dunbar circle overrides (person_id -> circle)
# Circle 0 = closest relationships
CIRCLE_OVERRIDES_BY_ID = {
    "cb93e7bd-036c-4ef5-adb9-34a9147c4984": 0,  # Taylor Walker
    "23b9aca8-8817-494a-a13e-7d7799f9b282": 0,  # Malea Ramia
    "3f41e143-719f-4dc9-a9f1-389b2db5b166": 0,  # Nathan Ramia (self)
}


# =============================================================================
# INTERACTION TYPE WEIGHTS
# =============================================================================
# Weight applied to each interaction when calculating frequency score.
# Higher weight = interaction counts more toward relationship strength.
#
# Rationale:
# - Direct 1:1 communication (DM, text, call) weighted highest
# - Synchronous communication (meetings, calls) weighted high
# - Asynchronous communication (email) weighted medium
# - Passive inclusion (being mentioned, CC'd) weighted lower
#
# Note: Currently we only have source_type. Future: add subtype for To/CC, 1:1/group.

INTERACTION_TYPE_WEIGHTS: dict[str, float] = {
    # Direct messaging (high intimacy, intentional contact)
    "imessage": 1.5,          # Personal text message
    "whatsapp": 1.5,          # Personal messaging app
    "signal": 1.5,            # Secure personal messaging
    "slack": 0.6,             # Work DM (less personal, often noisy)

    # Voice/Video (highest effort, synchronous)
    "phone_call": 3.0,        # Voice call - high effort
    "phone": 3.0,             # Phone call (alternate name)
    "facetime": 2.0,          # Video call - high effort

    # Calendar (meetings - synchronous, high signal)
    "calendar": 5.0,          # Meetings - strong relationship signal
    # Future: calendar_1on1: 1.5, calendar_small_group: 1.0, calendar_large_meeting: 0.5

    # Email (async, often broadcast/CC)
    "gmail": 0.8,             # Email - often CC'd or mass
    # Future: gmail_to: 1.0, gmail_cc: 0.3, gmail_sent: 1.2

    # Written content (you wrote about them - shows they're on your mind)
    "vault": 0.7,             # Mentioned in your notes
    "granola": 0.8,           # Meeting notes (AI-generated)

    # Contact sources (static, not interactions)
    "linkedin": 0.3,          # LinkedIn connection (passive)
    "contacts": 0.2,          # In your contacts (very passive)
    "phone_contacts": 0.2,    # Same as contacts
}

# Default weight for unknown interaction types
DEFAULT_INTERACTION_WEIGHT = 1.0


# =============================================================================
# ENTITY RESOLUTION WEIGHTS
# =============================================================================
# Used when matching source entities to canonical person entities

# Fuzzy name matching
NAME_SIMILARITY_WEIGHT = 0.4      # Weight for fuzzy name match score (0-1 scaled to 0-40)

# Context boosting
CONTEXT_BOOST_POINTS = 30         # Points added when email domain matches vault context
RECENCY_BOOST_POINTS = 10         # Points added for recently seen people
RECENCY_BOOST_THRESHOLD_DAYS = 30 # Days to consider someone "recently seen"

# Disambiguation
DISAMBIGUATION_THRESHOLD = 15     # If top two candidates within this score, it's ambiguous
MIN_MATCH_SCORE = 40.0           # Minimum score to consider a valid match

# Relationship strength boost for name-only resolution
# When resolving by name only (no email/phone), prefer people with existing relationship
RELATIONSHIP_STRENGTH_BOOST_MAX = 25    # Max points for relationship strength boost (0-100 strength -> 0-25 points)
RELATIONSHIP_STRENGTH_BOOST_WEIGHT = 0.25  # Multiplier: strength * weight = boost points

# First-name-only boost multiplier
# When matching just "Ben" instead of "Ben Calvin", apply stronger relationship boost
# because first-name-only mentions in notes usually refer to close contacts
FIRST_NAME_ONLY_BOOST_MULTIPLIER = 1.5  # Multiply relationship boost by this for single-word names

# Cache settings
ENTITY_CACHE_TTL_SECONDS = 1800  # 30 minutes


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_interaction_weight(source_type: str) -> float:
    """
    Get the weight for an interaction type.

    Args:
        source_type: The source type (e.g., "gmail", "imessage", "calendar")

    Returns:
        Weight multiplier for this interaction type
    """
    return INTERACTION_TYPE_WEIGHTS.get(source_type, DEFAULT_INTERACTION_WEIGHT)


def compute_weighted_interaction_count(interactions_by_type: dict[str, int]) -> float:
    """
    Compute weighted interaction count from a breakdown by type.

    Args:
        interactions_by_type: Dict mapping source_type to count

    Returns:
        Weighted sum of interactions
    """
    total = 0.0
    for source_type, count in interactions_by_type.items():
        weight = get_interaction_weight(source_type)
        total += count * weight
    return total
