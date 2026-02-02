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


# =============================================================================
# TAG OVERRIDES
# =============================================================================
# Manual tag overrides (person_id -> list of tags)
# Generated from LinkedIn data extraction 2026-02-02
# Tags follow format: industry:X, seniority:X, state:XX, city:X
#
# Location rules:
#   - Max 1 city + 1 state per person
#   - Sourced from person location, fallback to most recent job location
# Industry rules:
#   - Multiple allowed - one per unique industry across all jobs
# Seniority rules:
#   - Max 1 - highest tier achieved across all jobs
#   - Hierarchy: executive > senior > mid-level > entry

TAG_OVERRIDES_BY_ID: dict[str, list[str]] = {
    "7a2a9f18-2056-4f28-bac0-317c38717cba": ["city:chicago", "state:il", "industry:other", "seniority:executive"],  # AJ Kahle
    "74a0ffd1-c240-40e5-8884-7b82cc9558e1": ["city:washington-dc", "state:dc", "industry:other", "seniority:mid-level"],  # Aaron Goldzimer
    "482fd1a8-af46-4bbb-98e2-afea0c3da278": ["city:nashville", "state:tn", "industry:consulting", "industry:other", "industry:tech", "seniority:senior"],  # Abby Chisholm
    "dfb4d0e6-7ee3-45d2-9e97-4d05f5ac9459": ["city:albuquerque", "state:nm", "industry:government", "industry:legal", "industry:military", "industry:tech", "seniority:executive"],  # Adam Hesch
    "e4dcf856-b611-4f58-b756-016cad32c549": ["city:colorado-springs", "state:co", "industry:finance", "industry:other", "industry:tech", "seniority:senior"],  # Adam Pierce Nubern, CPA
    "a56841ed-ee83-4833-91dc-28c49b501f0a": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Alex Barbieri
    "0ffb8dd0-01e7-4dc2-9f69-9dc670b2a146": ["city:washington-dc", "state:dc", "industry:education", "industry:non-profit", "industry:tech", "seniority:executive"],  # Alex Niemczewski
    "b01e81b4-9164-412f-aef4-1cbe558be0c1": ["city:new-york", "state:ny", "industry:government", "industry:healthcare", "industry:politics", "seniority:executive"],  # Ali Bokhari
    "114bdb46-3942-4a91-ae09-33c6777d58fd": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:mid-level"],  # Ali Mortell
    "0b6f3939-fca9-429b-b946-72e440ae218b": ["industry:tech", "seniority:entry"],  # Alice Cornejo
    "826cdf58-81ce-443d-8148-82f3c8b4195d": ["city:washington-dc", "state:dc", "industry:consulting", "industry:education", "industry:government", "industry:non-profit", "seniority:executive"],  # Alix Haber
    "ab229560-94a2-4518-aec8-79c17e473d8d": ["city:seattle", "state:wa", "industry:government", "industry:other", "industry:politics", "seniority:senior"],  # Amee Amin
    "56850f9f-57ec-450f-bc2e-68cf15bcebe3": ["city:richmond", "state:ca", "industry:consulting", "industry:politics", "industry:tech", "seniority:executive"],  # Amir Arman
    "76a82271-8d30-427c-b995-f1deef897141": ["city:bethesda", "state:md", "industry:non-profit", "industry:tech", "seniority:executive"],  # Amir Stepak
    "6a50cb2f-69ca-4c25-ab2a-8684795bf16a": ["city:washington-dc", "state:dc", "industry:government", "industry:legal", "industry:politics", "seniority:executive"],  # Andie Levien
    "05f416d6-cfeb-4f72-908d-d1b87defe99a": ["city:washington-dc", "state:dc", "industry:other", "industry:tech", "seniority:executive"],  # Andrew Blythe
    "988e23b1-7ca7-4199-9836-499e060902a3": ["city:new-orleans", "state:la", "industry:education", "industry:legal", "industry:non-profit", "industry:other", "industry:tech", "seniority:executive"],  # Andrew Perry
    "983841fd-7664-419e-892a-0e8075182f52": ["city:washington-dc", "state:dc", "industry:finance", "industry:other", "industry:politics", "seniority:executive"],  # Andrew Reagan
    "451098ec-ee80-4cd9-8d32-a6950ea087e9": ["city:washington-dc", "state:dc", "industry:other", "seniority:mid-level"],  # Andrew Swick
    "a6388f5f-f98e-486c-baa6-5d1939f4d079": ["city:sacramento", "state:ca", "industry:other", "industry:politics", "industry:tech", "seniority:mid-level"],  # Anna (DeTorres) Homen
    "1aa519d6-db2c-4ae4-acd7-131f83575930": ["city:birmingham", "state:al", "industry:finance", "industry:media", "industry:non-profit", "seniority:mid-level"],  # Anna Ramia
    "6e601bcf-f168-4fe4-8cf8-e51975603c3f": ["city:bensalem", "state:pa", "industry:education", "industry:entertainment", "industry:tech", "seniority:entry"],  # Annabelle Levan
    "8edf37c8-c688-4e85-b976-11dbf14ad743": ["city:new-york", "state:ny", "industry:education", "industry:politics", "industry:tech", "seniority:executive"],  # Antoinette Chukudebelu
    "589e3c2b-26fe-4d97-b873-5c568b201a89": ["city:new-york", "state:ny", "industry:education", "industry:other", "industry:tech", "seniority:executive"],  # Anyi Sun
    "b15bc491-ba1f-46e8-85e9-65096c465181": ["city:arlington", "state:va", "industry:media", "industry:politics", "seniority:mid-level"],  # Ariel Braunstein, MPAP
    "cdface72-1c14-48ef-a8a4-ca84add924c6": ["city:washington-dc", "state:dc", "industry:education", "industry:non-profit", "industry:tech", "seniority:senior"],  # Asaf Reich
    "73aa799d-7393-4bfc-942d-f2ac038fd61a": ["city:midlothian", "state:va", "industry:non-profit", "industry:politics", "industry:tech", "seniority:executive"],  # Audra (Grassia) Archuleta
    "7ac79540-cce1-47d0-b57b-9453d9e798b0": ["city:washington-dc", "state:dc", "industry:government", "industry:politics", "seniority:executive"],  # Ben Calvin
    "3c01337c-9a82-43e2-b0a6-f5d82baef0bb": ["city:washington-dc", "state:dc", "industry:tech", "seniority:executive"],  # Ben Warren
    "5c8e40a9-160a-401b-88e5-ce0939c909f3": ["city:washington-dc", "state:dc", "industry:tech", "seniority:executive"],  # Bernard Asare
    "10b79ed8-8e03-4756-a04d-94b907a3cf11": ["city:atlanta", "state:ga", "industry:other", "industry:tech", "seniority:executive"],  # Bill Jones
    "4f46e9a2-3a19-41ec-922b-8f4f9039bcc1": ["city:new-york", "state:ny", "industry:consulting", "industry:government", "industry:media", "industry:politics", "seniority:senior"],  # Billy Glidden
    "41875537-e159-4cd8-8592-ca6e216d7894": ["city:houston", "industry:other", "seniority:senior"],  # Bon Nguyen
    "dc12e561-2915-469e-8777-2817180fd4a8": ["city:chicago", "state:il", "industry:consulting", "industry:education", "industry:politics", "industry:religious", "seniority:executive"],  # Brandon Salesberry
    "dbe4b8dc-19ec-4e9d-9c33-36b61a432c5f": ["city:edgewater", "state:md", "industry:other", "seniority:mid-level"],  # Brendon Mills
    "a31f0487-962e-4af5-a829-b6925372bff6": ["city:nashville", "state:tn", "industry:politics", "seniority:executive"],  # Brit Bender
    "df9207ff-0ccf-4b20-95bc-8b637159ac1d": ["city:remote", "state:ca", "industry:non-profit", "industry:politics", "industry:tech", "seniority:senior"],  # Brita Mackey
    "23d50fff-d8aa-4280-9c9b-d8b07f596c39": ["city:memphis", "state:tn", "industry:healthcare", "industry:religious", "industry:tech", "seniority:mid-level"],  # Bryce Berry, CSCS, ACSM-EP/ACS, Pn1, EIM
    "ec7dd382-c78a-4a39-97ee-c0b701e624b1": ["city:san-francisco", "state:ca", "industry:other", "industry:politics", "seniority:mid-level"],  # Bryce Peppers
    "c3b06015-9dda-498a-9075-5c3f5d108967": ["city:greater-cleveland", "industry:other", "industry:politics", "seniority:executive"],  # Candace Martin
    "53be4a18-9aaf-431e-8a11-83c2506ca230": ["city:new-york", "state:ny", "industry:other", "seniority:executive"],  # Carol Davidsen
    "b7b32cc7-8789-4885-87e1-29aa3d821779": ["city:boston", "state:ma", "industry:non-profit", "industry:politics", "industry:tech", "seniority:executive"],  # Carolina Zamora
    "d9d1921c-4d18-4088-b766-ff6a15b06cd4": ["city:austin", "state:tx", "industry:finance", "industry:other", "industry:tech", "seniority:executive"],  # Carson Li
    "aa7662f6-e394-490f-84d8-20283500b23c": ["city:washington-dc", "state:dc", "industry:consulting", "industry:politics", "seniority:executive"],  # Carter Kalchik
    "bc35d0d5-6c41-4e7b-8a39-71227ec7d214": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Charlie Turner
    "a6900367-368f-4d5c-a060-c18280659e95": ["city:dallas-fort-worth-metroplex", "industry:other", "industry:tech", "seniority:executive"],  # Chase Cappo
    "9071b62c-b1e0-4bd2-8e96-4d411ab8849d": ["city:new-york", "state:ny", "industry:retail", "industry:tech", "seniority:executive"],  # Christine Miao
    "5a8dec7f-99b3-4129-b0da-8f014ae189c6": ["city:new-york", "state:ny", "industry:education", "industry:government", "industry:non-profit", "industry:politics", "seniority:mid-level"],  # Christopher Magallona
    "b6ce339e-d49a-4cba-afe5-8860d77612ec": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:mid-level"],  # Cindy Sui
    "69a0d01d-9362-4211-8b94-ef6802ae259f": ["city:boston", "state:dc", "industry:consulting", "industry:non-profit", "industry:other", "industry:politics", "seniority:executive"],  # Courtney Finn Clark
    "9a8ddbc9-255f-47d2-b930-2675874f6411": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Cristina Sinclaire
    "40facab7-3506-4de6-b3e9-1341f2a14f1b": ["city:washington-dc", "state:dc", "industry:politics", "industry:tech", "seniority:senior"],  # Curtis Morales
    "87816830-90d0-4ad0-a15c-314a82b37036": ["city:san-francisco", "industry:other", "seniority:executive"],  # Dan Glorsky
    "1e993fb0-d486-4482-a867-70a5af1f6e28": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "industry:tech", "seniority:executive"],  # Dan McSwain
    "2e717d10-0fd6-4aee-adcd-87d7a3d51cbc": ["city:new-york", "state:ny", "industry:other", "seniority:executive"],  # Dan Porter
    "b61ee780-7199-42bc-87c9-bbcc417a69e3": ["city:oakland", "state:ca", "industry:other", "industry:politics", "seniority:mid-level"],  # Daniel Jubelirer
    "01c80172-cd96-4126-93ba-b2c08aeeff67": ["city:denver", "state:co", "industry:other", "seniority:mid-level"],  # Dave Burgio
    "8641589e-e414-4558-ac4d-c1ced2a17d9b": ["city:brooklyn", "state:ny", "industry:other", "industry:tech", "seniority:executive"],  # David Hammer
    "994bbc78-8f2e-43ff-aa6a-692533aa770d": ["city:narberth", "state:pa", "industry:education", "industry:non-profit", "industry:politics", "seniority:executive"],  # David Nickerson
    "d3174ffc-ace5-47a6-ab22-931aea83515a": ["city:austin", "state:tx", "industry:other", "industry:tech", "seniority:executive"],  # Davis Lawyer
    "0b09279f-baf0-4aba-a818-56bb4a281da9": ["city:europe", "industry:consulting", "industry:other", "industry:politics", "industry:tech", "seniority:mid-level"],  # Daye Lee
    "3b81d423-301e-4509-ab77-3427e9481a0e": ["city:seattle", "state:wa", "industry:consulting", "industry:other", "industry:tech", "seniority:senior"],  # Deb Kopp
    "174cd9ac-231e-4967-ba72-fa2a70c7a1f2": ["city:austin", "state:tx", "industry:other", "industry:tech", "seniority:executive"],  # Dheeraj Chand
    "9d6a5498-4aef-4640-a9d1-8c4547e208fd": ["city:los-angeles", "state:ca", "industry:other", "industry:politics", "seniority:mid-level"],  # Drey Cameron
    "f2242da1-a07a-4eea-96e3-ffeac11e1e30": ["city:philadelphia", "state:pa", "industry:other", "industry:politics", "seniority:mid-level"],  # Dylan Clairmont
    "6667972f-80db-4666-8463-7bc44ce44d4d": ["city:madison", "state:wi", "industry:other", "industry:politics", "industry:tech", "seniority:executive"],  # Ed Niles
    "bf56aa7c-9669-4053-8559-22a09e9d6e3a": ["city:washington-dc", "state:dc", "industry:other", "seniority:executive"],  # Elan Kriegel
    "7981f4dd-1826-4fa6-a4a7-eaa30cf16f93": ["city:east-lansing", "state:mi", "industry:consulting", "industry:politics", "seniority:executive"],  # Eleanor Templeton
    "10c8265f-b7eb-4812-af9f-3bd07680fc1a": ["city:new-york", "state:ny", "industry:other", "seniority:mid-level"],  # Elena Gonzalez
    "2a147975-f2f2-4891-8d23-43ab0b530ab1": ["city:washington-dc", "state:dc", "industry:legal", "industry:non-profit", "seniority:executive"],  # Elizabeth Cruikshank
    "1034bf68-e4bb-4ebe-a329-18587eb3ee10": ["city:austin", "state:tx", "industry:other", "industry:tech", "seniority:executive"],  # Elizabeth Weiland
    "ff5e936f-f09f-4934-9643-828621ee71ac": ["city:denver", "state:dc", "industry:consulting", "industry:government", "industry:media", "industry:other", "industry:tech", "seniority:senior"],  # Elyse Ping Medvigy, MA
    "34142cc5-38b1-42fe-8224-3d0765f951b0": ["city:washington-dc", "state:dc", "industry:healthcare", "industry:non-profit", "industry:tech", "seniority:executive"],  # Emily Durfee
    "48c04f1c-5a5c-4bcd-bd07-914246b63d2c": ["city:new-york", "state:ny", "industry:other", "industry:politics", "seniority:mid-level"],  # Emily White
    "47ffe076-1265-4dc8-8d13-ac2bd62dcc9f": ["city:new-york", "state:ny", "industry:government", "industry:other", "industry:politics", "seniority:executive"],  # Emma Bloomberg
    "2d996de3-4f40-438f-b261-d48583c322fb": ["city:washington-dc", "state:dc", "industry:other", "seniority:executive"],  # Erek Dyskant
    "b030409d-d3d5-4d54-839e-7f757cb32955": ["city:washington-dc", "state:dc", "industry:government", "industry:non-profit", "industry:politics", "industry:tech", "seniority:executive"],  # Erica Slates
    "e1d31f0f-2567-4c16-9629-29574cdcfc76": ["city:palo-alto", "state:ca", "industry:other", "seniority:executive"],  # Erika Lovin
    "635613a2-343e-4918-922b-4a09ec0e7112": ["city:medford", "state:ma", "industry:education", "industry:politics", "industry:tech", "seniority:executive"],  # Erika Weisz
    "10fe2867-a9e1-4392-8cc2-3a46912eaa92": ["city:arlington", "state:va", "industry:finance", "industry:media", "industry:tech", "seniority:executive"],  # Evan Burfield
    "efbfa82f-e04e-4904-b1a3-5852343e36cf": ["city:new-york", "state:ny", "industry:finance", "industry:tech", "seniority:senior"],  # Evan Marcantonio
    "bd30aa84-b4cc-496d-9cfb-80ca663c24c1": ["city:washington-dc", "state:dc", "industry:non-profit", "industry:other", "seniority:executive"],  # Evanna Hu
    "4b580ef5-827b-41d1-929c-e743974d0b4e": ["city:west-hollywood", "state:ca", "industry:consulting", "industry:entertainment", "industry:media", "seniority:senior"],  # Evie Lyras
    "ce988679-7693-4f33-8021-71cdb96baea6": ["city:fairfax", "state:va", "industry:tech", "seniority:executive"],  # Faisal Siddiqui
    "efe1f68f-0f47-43cf-9a1e-a88ecfc104b9": ["city:portland", "state:or", "industry:non-profit", "industry:politics", "seniority:executive"],  # Fatmah Worfeley
    "90a4f378-8339-458e-a90b-d2bbbbef1607": ["city:chicago", "state:il", "industry:other", "industry:politics", "industry:tech", "seniority:executive"],  # Gautham Arumilli
    "ef707ec5-9d65-4e32-9fb8-178b7e0ace4b": ["city:new-york", "state:ny", "industry:media", "industry:tech", "seniority:senior"],  # Genevieve Lee
    "2c405a89-53c8-48dc-a07b-4e5d17975cb8": ["city:minneapolis", "state:mn", "industry:other", "industry:politics", "seniority:mid-level"],  # Hannah Burt
    "e39f459d-adb9-4388-9b3d-a11f12a5d45f": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Haris Aqeel
    "4237567b-2ff0-4647-b2ba-f6c995d3c681": ["city:washington-dc", "state:dc", "industry:education", "industry:politics", "industry:tech", "seniority:executive"],  # Harrison Kreisberg
    "8c592fb9-2bc8-4f17-9c9e-4a97d5a7af01": ["city:washington-dc", "state:dc", "industry:media", "industry:non-profit", "industry:retail", "seniority:mid-level"],  # Heather Williams
    "d26b362b-8ce6-49bb-b5b7-6d67d05cc507": ["city:san-francisco", "state:ca", "industry:non-profit", "industry:other", "industry:tech", "seniority:executive"],  # Heidi Williams
    "18c06c3a-99d4-47e5-a8c6-ed6d47bb45e6": ["city:san-francisco", "state:ca", "industry:finance", "industry:politics", "industry:tech", "seniority:executive"],  # Hillary Lehr
    "98930b8d-b6df-477d-8ebf-e15d100c29b0": ["city:umatilla", "state:fl", "industry:other", "seniority:executive"],  # Hunter Lamirande
    "5db8e2ae-6a53-42f4-b14a-4cf9c3fc050d": ["city:los-angeles", "state:ca", "industry:consulting", "industry:education", "industry:media", "industry:retail", "industry:tech", "seniority:senior"],  # Ian Daly
    "bf0a8cee-495e-4b37-932a-cc767b395dfa": ["city:washington-dc", "state:dc", "industry:non-profit", "industry:politics", "seniority:executive"],  # Ilana Kaplan
    "0af4a27e-7750-4123-a16a-cf5fc7ed4de0": ["city:chicago", "state:il", "industry:other", "industry:tech", "seniority:mid-level"],  # Iris Cano
    "bb92fac5-3f4a-4453-8e37-b833e51cf6b6": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "industry:tech", "seniority:mid-level"],  # Isaac Flores-Huerta
    "5ce5124a-723e-44c4-8430-ff66a84cb68c": ["city:washington-dc", "state:dc", "industry:other", "industry:tech", "seniority:executive"],  # Ivana Ng
    "cb1cc927-34e9-45f6-ac53-f3777e88b024": ["city:boston", "state:ma", "industry:other", "seniority:mid-level"],  # Jack Ball
    "55384170-7f87-45d0-943f-f45ae8ce5e3e": ["city:washington-dc", "state:dc", "industry:consulting", "industry:non-profit", "industry:other", "industry:tech", "seniority:executive"],  # Jacky Chang
    "ba5e476d-a436-4945-87ea-adf05e697c4b": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:mid-level"],  # James Booth
    "3c0ec7bc-2c32-4e9f-a9ca-1db5964e0ebd": ["city:austin", "industry:consulting", "industry:other", "industry:politics", "seniority:executive"],  # James Denny
    "7a825c4f-4da2-4cf6-850d-ca491ad918ff": ["city:colorado-springs", "state:co", "industry:logistics", "industry:military", "industry:other", "seniority:mid-level"],  # Jamie Bitner MBA, DSL
    "4ece1ddd-9f49-4d21-80d1-a3d2cd25990b": ["city:kansas", "state:fl", "industry:other", "industry:politics", "seniority:mid-level"],  # Jamie Jarvis
    "067cc5ef-ca0f-42c6-9cfe-2538b5461f62": ["city:austin", "state:tx", "industry:military", "industry:politics", "seniority:executive"],  # Jeremy Smith
    "d5202074-943f-4818-b863-a483ac8afb87": ["city:chicago", "state:il", "industry:consulting", "industry:non-profit", "industry:tech", "seniority:executive"],  # Jiore Craig
    "dec74a96-5cf1-4fb8-b568-23a024e107a4": ["city:new-york", "state:ny", "industry:other", "industry:politics", "seniority:executive"],  # Joe Huston
    "d07597bd-53aa-4be1-9244-c139df59b4ee": ["city:asheville", "state:nc", "industry:consulting", "industry:other", "industry:politics", "industry:tech", "seniority:senior"],  # Joel Shuman
    "630fb878-5c03-44b8-b3dd-3ff3d62cee2b": ["city:philadelphia", "state:pa", "industry:other", "industry:tech", "seniority:mid-level"],  # Johnny Garcia
    "de14e096-d95d-4eaf-a093-f2bfab86dca1": ["city:san-francisco", "state:ca", "industry:other", "industry:tech", "seniority:executive"],  # Jon McCann
    "73f7fbdc-00c7-44c2-8baa-e0aad2cf27e4": ["city:chicago", "state:il", "industry:other", "industry:tech", "seniority:executive"],  # Jordan Birnholtz
    "c9aebe36-49c4-42bb-a29d-3f28389105e9": ["city:montclair", "state:nj", "industry:consulting", "industry:media", "industry:non-profit", "industry:tech", "seniority:executive"],  # Josh Hendler
    "1c0edc74-9a81-4c46-aade-21ed4adadd50": ["city:alexandria", "state:va", "industry:consulting", "industry:other", "industry:politics", "industry:tech", "seniority:executive"],  # Josh Yazman
    "65ad2bae-40cb-4708-8252-942b5c52bb00": ["city:charlotte", "state:dc", "industry:other", "industry:politics", "seniority:mid-level"],  # Josie Koehler
    "09def099-35cd-4ea9-879f-22422dceb2ec": ["city:brooklyn", "state:ny", "industry:consulting", "industry:other", "industry:tech", "seniority:executive"],  # Kaitlyn Venezia
    "ac821ba2-5b30-4522-825d-56ce1a55e21c": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:mid-level"],  # Kareem Jones
    "64b09da3-c5c8-4fce-960b-57f4748b3210": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Kat Atwater
    "63726b96-6f9f-4bc6-b666-64428ebe9e30": ["city:san-francisco", "state:ca", "industry:other", "industry:tech", "seniority:mid-level"],  # Katie Douglass
    "c32931f4-2f04-478b-8fba-69f1b88a3dda": ["city:los-angeles", "state:ca", "industry:other", "industry:politics", "seniority:executive"],  # Katie Whittington
    "48a1f769-bf40-47e3-8f6e-a26197ef6782": ["city:san-diego", "state:ca", "industry:media", "industry:other", "industry:politics", "seniority:executive"],  # Kellen Arno
    "b8d749d5-5916-4796-9a90-07d7fdf487e8": ["city:remote", "state:co", "industry:education", "industry:government", "industry:healthcare", "industry:politics", "seniority:mid-level"],  # Kellie Allen
    "f79fe5a0-74df-433a-a5fb-8a418cee9e95": ["city:washington-dc", "state:dc", "industry:consulting", "industry:other", "industry:tech", "seniority:senior"],  # Kelly Fink
    "9714161e-6118-43d1-a863-b299a201e2f1": ["city:washington-dc", "state:dc", "industry:education", "industry:energy", "industry:entertainment", "seniority:senior"],  # Kerry DeMella, PhD
    "4a9c19aa-92fc-47b2-b559-0a35c364ea6f": ["city:franklin", "state:wi", "industry:other", "industry:politics", "industry:tech", "seniority:executive"],  # Kevin Perez
    "7970350d-0552-46e2-bea3-553252bc66aa": ["city:chicago", "state:il", "industry:consulting", "industry:politics", "industry:tech", "seniority:executive"],  # Kevin Pujanauski
    "3497d157-2680-4838-b7d7-f8752f48fedf": ["city:austin", "state:tx", "industry:consulting", "industry:education", "industry:logistics", "industry:tech", "seniority:executive"],  # Kevin Rustagi
    "2bf7efbb-5667-4f67-84a6-677b3ca4c82a": ["city:washington-dc", "state:dc", "industry:entertainment", "industry:tech", "seniority:executive"],  # Kim Nguyen
    "55df14df-f4aa-4aec-8aef-565007cfef6f": ["city:new-york", "state:ny", "industry:other", "industry:tech", "seniority:executive"],  # Kit Krugman
    "429eb918-ab87-4c64-9004-6e2e62a3e5f9": ["city:chicago", "state:il", "industry:non-profit", "industry:other", "seniority:executive"],  # Lance Dietz
    "48d8318e-7d96-423a-9df0-7b593103c88d": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Laura Brogan
    "649e4f4a-1cf2-4dcd-b73d-b7f6f30608e4": ["city:nashville", "industry:other", "industry:politics", "seniority:executive"],  # Lauren Gepford
    "cfe01042-128f-4bd8-a8a1-25ba1e2665e8": ["city:washington-dc", "state:dc", "industry:other", "industry:tech", "seniority:executive"],  # Lauren Krone
    "eee73dcf-9c7c-4573-9446-00068dbdd600": ["city:new-haven", "state:ct", "industry:education", "industry:legal", "industry:politics", "seniority:executive"],  # Lauren Libby
    "9fa87f3e-e7ba-4f69-b726-9c39c16f60b7": ["city:tampa", "state:fl", "industry:other", "industry:politics", "industry:tech", "seniority:mid-level"],  # Leonardo Dulanto Falcon
    "189ed9e5-e04e-42f7-a027-c7b1ef9f596d": ["city:new-york", "state:ny", "industry:other", "seniority:executive"],  # Leslie Gross
    "bde2eb5e-5c33-4deb-9682-d1dc83f46af6": ["city:washington-dc", "state:dc", "industry:other", "seniority:mid-level"],  # Leslie Sage
    "eb4ef85b-63ce-4319-b6f0-420b30779b77": ["city:new-york", "state:ny", "industry:other", "seniority:executive"],  # Livie Casto
    "440bdae4-111d-4c8b-9d2e-68c7cd3494a5": ["city:washington-dc", "state:dc", "industry:non-profit", "industry:other", "industry:politics", "seniority:executive"],  # Liz Jaff
    "52b0c9a8-b782-4abe-8976-86d90bb2fdc9": ["city:detroit", "state:mi", "industry:other", "industry:tech", "seniority:executive"],  # Louis Gelinas
    "062a9312-3839-4e4b-a7c7-3e8af556eafe": ["city:brooklyn", "state:ny", "industry:other", "industry:politics", "industry:tech", "seniority:executive"],  # Mallory Stewart Robison
    "317d2707-6075-43a3-9f25-841ee1b73843": ["city:washington-dc", "state:dc", "industry:government", "industry:legal", "industry:politics", "seniority:senior"],  # Maria Krol Stosz
    "6f18ea09-1929-42cb-9e73-6d76821d2d9d": ["city:washington-dc", "state:dc", "industry:other", "industry:tech", "seniority:mid-level"],  # Mark Rossetti
    "d1ec3c3b-95f8-47fa-8732-91449d0a1fe7": ["city:washington-dc", "state:dc", "industry:education", "industry:finance", "industry:government", "industry:non-profit", "seniority:mid-level"],  # Martha Gillon
    "1a694f52-e059-44b2-968d-5d5262a7531a": ["industry:other", "seniority:executive"],  # Matt Martin
    "86991f85-f3d6-4226-9b81-4c23b8ed6aab": ["city:washington-dc", "state:dc", "industry:media", "industry:politics", "industry:tech", "seniority:executive"],  # Matt Mawhinney
    "6dc8cf74-665f-4bd5-ab83-4de388dacb94": ["city:washington-dc", "state:dc", "industry:other", "industry:tech", "seniority:mid-level"],  # Matt Southwell
    "98faf69d-7714-40a7-85c5-da9d1df1f78a": ["city:chicago", "state:dc", "industry:other", "seniority:executive"],  # Matthew Saniie
    "c6f0867c-932b-4eb7-832e-b8f1672cd466": ["city:new-york", "state:ny", "industry:other", "industry:tech", "seniority:executive"],  # Matthew Stafford
    "deaba34d-ed3f-4967-b46b-18aa9a9edd96": ["city:brooklyn", "state:ny", "industry:other", "industry:tech", "seniority:executive"],  # Max Borowitz
    "96b721f7-d951-4239-bdbb-b9615c063cc4": ["city:washington-dc", "state:dc", "industry:politics", "industry:tech", "seniority:executive"],  # Max Wood
    "445ff380-74e6-4b8b-8277-ea2d1e62b04c": ["city:fairfax", "state:va", "industry:other", "seniority:executive"],  # Maya Castillo
    "0dbbc972-a1d3-4429-b273-181e7db4984e": ["city:seattle", "state:wa", "industry:other", "industry:politics", "industry:tech", "seniority:executive"],  # Michael Futch
    "8c9dafd8-97a7-455e-be41-585affc97aa4": ["city:washington-dc", "state:dc", "industry:consulting", "industry:finance", "industry:government", "industry:politics", "seniority:executive"],  # Michael Luciani
    "fefe1631-0224-4c7a-80f4-94ed4d2be159": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:mid-level"],  # Michael McCall
    "b6bb87b2-f4e5-4334-8412-0238858c7aea": ["city:new-york", "state:ny", "industry:other", "industry:politics", "seniority:executive"],  # Michael Slaby
    "2c74b017-5780-4379-a73a-a4ba1f5faa80": ["city:philadelphia", "state:dc", "industry:other", "seniority:executive"],  # Michelle Brown
    "1c8f432e-dc3d-406a-a4c6-a8914789b2f3": ["city:belgrade", "state:mt", "industry:education", "industry:other", "industry:politics", "seniority:senior"],  # Michelle Vered
    "ec86ccf4-1edd-420c-9f3f-26653114870f": ["city:mclean", "state:va", "industry:military", "industry:non-profit", "industry:tech", "seniority:executive"],  # Mike Slagh
    "a9c5a3d5-3369-4686-887a-905f4308456f": ["city:new-haven", "state:ct", "industry:education", "industry:finance", "industry:other", "industry:tech", "seniority:executive"],  # Miles Lasater
    "2daceb9c-3c1c-4830-b77c-78a645864770": ["city:houston", "state:tx", "industry:consulting", "industry:government", "industry:politics", "seniority:executive"],  # Mili Gosar
    "37a392b2-3cd1-4d30-a8c6-526a9a6b25e1": ["city:oakland", "state:ca", "industry:legal", "industry:tech", "seniority:senior"],  # Mindy Phillips
    "fb1868ee-45cc-4cbe-9fe7-f462b2b3e242": ["city:austin", "industry:other", "industry:politics", "seniority:mid-level"],  # Mitul Mistry
    "7e34a04d-1731-4e32-b2fa-bd06d7ac5add": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Mohammed Maraqa
    "0f4e03c3-614d-4b30-afe6-0dd506f79b58": ["city:chicago", "state:il", "industry:entertainment", "industry:healthcare", "industry:media", "industry:politics", "seniority:mid-level"],  # Myra Barnett
    "957f7eb2-a8d7-437b-b4f0-4860faa231ca": ["city:cambridge", "state:ma", "industry:education", "industry:other", "industry:tech", "seniority:senior"],  # Nate Webster
    "08d459d9-c60d-4835-a644-aff3b8ad2550": ["city:hudson", "state:ny", "industry:non-profit", "industry:politics", "industry:tech", "seniority:executive"],  # Nathan Woodhull
    "daa8ef23-8aea-4bcc-b751-1dff7d939344": ["city:united-states-\u00b7-remote", "state:ca", "industry:consulting", "industry:non-profit", "industry:other", "industry:tech", "seniority:executive"],  # Newton Campbell Jr., Ph.D.
    "3f9dd552-77f0-4a83-a228-476539397f6a": ["city:charlottesville", "state:va", "industry:media", "industry:non-profit", "industry:politics", "industry:tech", "seniority:executive"],  # Nick (Morrow) Hutchins
    "e3c1ae72-4408-4230-ab99-34720798bc5f": ["city:greenville", "state:sc", "industry:other", "seniority:mid-level"],  # Nick Z. Elliott
    "084d892c-78a4-4d58-8852-3b239a66f182": ["city:washington-dc", "state:dc", "industry:entertainment", "industry:politics", "industry:tech", "seniority:executive"],  # Oscar Boleman
    "3ec51f91-6881-4e21-b979-1ae335c296b1": ["city:chicago", "state:il", "industry:other", "industry:tech", "seniority:executive"],  # Otis Reid
    "8205b758-a86f-456c-8c1c-ae3d3b2aa434": ["city:memphis", "state:tn", "industry:consulting", "seniority:mid-level"],  # Patricia Ramia
    "8460eafa-dad6-4286-9b93-d1e62d5781fa": ["city:portland", "state:me", "industry:other", "industry:tech", "seniority:mid-level"],  # Paul Schaffer
    "19fd78e3-428e-4707-a1a6-4641cb238784": ["city:washington-dc", "state:dc", "industry:other", "seniority:executive"],  # Pedro Suarez
    "013bf487-32ce-4873-90c2-c1cd7d91aff6": ["city:chicago", "state:il", "industry:other", "industry:politics", "industry:tech", "seniority:executive"],  # Peter Stein
    "97c0bbef-2e80-4d1f-96a0-3472fde00fdf": ["city:san-francisco", "state:ca", "industry:other", "seniority:executive"],  # Peterson Conway
    "89f5a939-0d2b-4545-942c-9372569b768a": ["city:washington-dc", "state:dc", "industry:other", "industry:tech", "seniority:mid-level"],  # Rachel Hovde
    "1ffe315f-5854-46a8-b455-4a7fe7a56abc": ["city:new-york", "state:ny", "industry:non-profit", "industry:other", "industry:tech", "seniority:executive"],  # Rachel Kane
    "7de5c217-b9a7-4fb0-8f09-2a68d8bbb307": ["city:washington-dc", "state:dc", "industry:education", "industry:non-profit", "seniority:executive"],  # Rachel Southcott
    "fae0cdfd-fe64-453e-8cad-1ad3728de2ec": ["city:canada", "industry:consulting", "industry:education", "industry:healthcare", "industry:non-profit", "industry:tech", "seniority:executive"],  # Rainer Franz
    "1c64be9c-bbb7-4856-8cbb-d8dbcca22438": ["city:washington-dc", "state:dc", "industry:other", "industry:tech", "seniority:executive"],  # Riki Conrey
    "20be5f44-5b92-4f9e-ae98-22959c00364f": ["city:new-smyrna-beach", "state:fl", "industry:consulting", "industry:education", "industry:non-profit", "industry:other", "seniority:executive"],  # Robert Caslen, DBA
    "0252556d-b50d-4119-b6d1-da34f533ce58": ["city:washington-dc", "state:dc", "industry:politics", "industry:tech", "seniority:executive"],  # Robert Joseph
    "847e73a8-ce5d-4638-aacf-6d1124c70b2c": ["city:campton", "state:nh", "industry:consulting", "industry:education", "industry:tech", "seniority:mid-level"],  # Rose Sebastian
    "9f9c6255-837b-481a-8ae9-37c1b54adaa8": ["city:portland", "state:or", "industry:other", "industry:politics", "seniority:mid-level"],  # Rossy Valdovinos
    "c705c2fd-d148-4c14-ad63-5f5e58b6bd48": ["city:new-orleans", "state:la", "industry:education", "industry:politics", "industry:tech", "seniority:executive"],  # Roxanne Rudov
    "c760a305-19fa-40f0-acc0-6121b07e3f31": ["city:san-francisco", "state:ca", "industry:government", "industry:tech", "seniority:senior"],  # Rucha Tatke
    "2319a4e9-37d5-42b0-92ef-86d528fc9968": ["city:boston", "state:ma", "industry:other", "seniority:mid-level"],  # Russell Pildes
    "adf65d77-8550-4a87-8faa-c16348c58319": ["city:denver", "state:co", "industry:consulting", "industry:education", "industry:energy", "seniority:executive"],  # Ryan A. Jones
    "f662bca6-aba7-4f4e-b4a0-bb21063cd7d2": ["city:washington-dc", "state:dc", "industry:other", "seniority:executive"],  # Sabrina Dorman
    "b15d45ea-c6d6-4a55-bee4-9215e6984cf6": ["city:washington-dc", "state:dc", "industry:other", "seniority:executive"],  # Sabrina Roshan
    "335c0128-bb8e-4dec-95d2-cd8e517a9d22": ["city:chicago", "state:il", "industry:tech", "seniority:executive"],  # Sam Frank
    "fac19fc7-9177-47fa-9757-349af0ef40a1": ["city:washington-dc", "state:dc", "industry:education", "industry:media", "industry:non-profit", "industry:politics", "industry:tech", "seniority:executive"],  # Sam Goodgame
    "d902a3d0-1598-44f9-977d-1729bf30e273": ["city:washington-dc", "state:dc", "industry:consulting", "industry:politics", "industry:tech", "seniority:executive"],  # Samuel Nitz
    "7cefcc6f-fa7c-499c-a58c-c2dc46262bcb": ["city:seattle", "state:wa", "industry:finance", "industry:other", "industry:tech", "seniority:senior"],  # Sana Fathima
    "120b9c11-cc10-4246-b59e-68edf46401f1": ["city:los-altos", "state:ca", "industry:finance", "industry:non-profit", "industry:tech", "seniority:executive"],  # Sangeeth Peruri
    "e0188337-24df-456c-807b-b2a6eee44196": ["city:bellevue", "state:wa", "industry:other", "industry:politics", "industry:tech", "seniority:mid-level"],  # Sara Black
    "a7aa5ef9-2c09-49bf-a67a-9bffe4eb998e": ["city:washington-dc", "state:dc", "industry:consulting", "industry:education", "industry:government", "seniority:executive"],  # Sarah Esty
    "fc95c71f-ddc1-4996-ad56-41b859dbe139": ["city:washington-dc", "state:dc", "industry:government", "industry:other", "industry:politics", "industry:tech", "seniority:senior"],  # Sarah Gwinn
    "8f7ceb88-ba0b-458f-a2db-bbebb2154757": ["city:baltimore", "state:md", "industry:consulting", "industry:education", "industry:politics", "seniority:executive"],  # Sarah Stamper
    "ff150389-3894-430c-a6c5-9557b94e10b4": ["city:asheville", "state:nc", "industry:media", "industry:other", "seniority:executive"],  # Sarah-Marie Hopf
    "419bfdfb-ed80-41a4-8b26-cb7a4bb3756b": ["city:new-york", "state:ny", "industry:politics", "seniority:executive"],  # Saul Cunow
    "24c3eab2-65e9-44aa-b346-ce16681daa20": ["city:new-york", "state:ny", "industry:other", "seniority:executive"],  # Scott Starrett
    "f79abd35-2117-4872-a407-9c14f97e53ea": ["city:campbell", "state:ca", "industry:government", "industry:media", "industry:non-profit", "seniority:executive"],  # Sergio Lopez
    "4e0dabac-224c-42be-8531-84d2c03b5cd7": ["city:washington-dc", "state:dc", "industry:non-profit", "industry:tech", "seniority:executive"],  # Shane Bateman
    "6bcd70a5-71f0-481f-a735-4010864114e4": ["city:washington-dc", "state:dc", "industry:other", "seniority:executive"],  # Shayna Strom
    "24e1bd80-dc43-40ec-93c1-f58b15aa0928": ["city:memphis", "state:tn", "industry:media", "industry:other", "industry:tech", "seniority:executive"],  # Shell D. Berry
    "6d11b1b9-617a-43eb-b36a-2f3d90a4f1bb": ["city:austin", "state:tx", "industry:other", "industry:politics", "seniority:executive"],  # Shion Deysarkar
    "a7f91eea-4863-4667-96a6-402a6af9e867": ["city:remote", "industry:consulting", "industry:finance", "industry:healthcare", "industry:politics", "seniority:executive"],  # Shola Farber
    "44101b6f-7cc9-4912-86e2-88af7b662fad": ["city:durham", "state:nc", "industry:other", "seniority:executive"],  # Shruti Shah
    "6764576f-2dc9-42a6-8067-38413d4f1ff2": ["city:cambridge", "state:ma", "industry:education", "industry:tech", "seniority:executive"],  # Simon Kozlov
    "cb825159-f80e-48cb-8aac-8cdfb56761ae": ["city:los-angeles", "state:ca", "industry:other", "industry:politics", "seniority:mid-level"],  # Simone Kathleen Rossi
    "f090de3d-bf93-4e24-af1d-2d6efd2443e6": ["city:bridgetown", "state:il", "industry:other", "industry:politics", "seniority:executive"],  # Solace Porter
    "3bdc3ba9-3dea-41ec-8c93-395c619dbd3f": ["city:new-york", "state:ny", "industry:consulting", "industry:government", "industry:non-profit", "industry:tech", "seniority:executive"],  # Sonya Reynolds
    "349deb6a-327e-416d-973f-e575534ecdf9": ["city:brooklyn", "state:ny", "industry:education", "industry:military", "industry:non-profit", "seniority:executive"],  # Soren Duggan
    "9b5c4b3b-52ab-4b61-9e03-8e5e7ed76c18": ["city:san-francisco", "state:ca", "industry:healthcare", "industry:other", "industry:tech", "seniority:senior"],  # Susanna Supalla
    "86741686-b3e8-438d-a2f3-00481fac0ae8": ["city:washington-dc", "state:dc", "industry:education", "industry:non-profit", "industry:tech", "seniority:executive"],  # Swetha Ramaswamy
    "cb000ad1-5dcf-44e8-908e-fc42cf873178": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:mid-level"],  # Sydney Dion-Martel
    "dff6b99a-8714-4a8a-a9b5-a337e779ef7d": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Sydney Throop
    "0ffde5ee-ea34-4e03-8a17-6e5600b6eaca": ["city:oakland", "state:ca", "industry:entertainment", "industry:non-profit", "industry:politics", "industry:real-estate", "industry:tech", "seniority:executive"],  # Tamara Miller
    "f5fe7943-eba4-4679-a964-ba928fb241a1": ["city:washington-dc", "state:dc", "industry:media", "seniority:senior"],  # Tara Golshan
    "27dace12-8eab-429f-b74d-cfbc15c2f57a": ["city:washington-dc", "state:dc", "industry:non-profit", "industry:other", "industry:politics", "seniority:executive"],  # Tatenda Musapatike
    "018c9c89-19f3-4ab9-af2d-97e05077257d": ["city:bethlehem", "state:pa", "industry:politics", "industry:tech", "seniority:senior"],  # Taylor Nation
    "06924b0d-115e-4882-9b67-63961d1b4d16": ["city:washington-dc", "state:dc", "industry:other", "industry:politics", "seniority:executive"],  # Thea Sebastian
    "6cfb6792-3f17-47a4-bd46-6a9f49876b9e": ["city:washington-dc", "state:dc", "industry:other", "seniority:mid-level"],  # Thomas Esty
    "04bf94f8-20b7-4285-abb4-c64131b5542f": ["city:washington-dc", "state:dc", "industry:government", "seniority:mid-level"],  # Thy R
    "2441186b-51ab-41dc-90a1-9737b3ef7af1": ["city:wiscasset", "state:me", "industry:logistics", "industry:non-profit", "industry:politics", "industry:retail", "seniority:mid-level"],  # Tonya Slobuszewski
    "1f1023e3-7cf0-4d5a-bd8b-47402ff93cfa": ["city:cambridge", "state:ma", "industry:tech", "seniority:executive"],  # Tuan Ho
    "7347a1d4-fbbe-4c45-b9b3-6cd080212076": ["city:san-francisco", "state:ca", "industry:other", "industry:tech", "seniority:mid-level"],  # Tyler Matthews
    "5eb571ec-1629-4f56-9c6d-05644f7177ac": ["city:washington-dc", "state:dc", "industry:education", "industry:politics", "industry:tech", "seniority:executive"],  # Valerie Bradley
    "0800118c-bda0-4656-9a2b-c64db35be998": ["industry:non-profit", "seniority:entry"],  # Victoria Levchenko
    "e7cce321-fd6c-48a4-8a58-19cf752f303d": ["city:arlington", "state:va", "industry:consulting", "industry:tech", "seniority:executive"],  # Vince Broz
    "96c89bad-d718-4e5d-84fb-1dfb480256c2": ["city:new-york", "state:ny", "industry:other", "industry:tech", "seniority:mid-level"],  # Viraj Doshi
    "1d026fc1-f079-46b9-9015-512f8322e8b7": ["city:washington-dc", "state:dc", "industry:finance", "industry:government", "industry:non-profit", "seniority:executive"],  # Wendy Papakostandini
    "29a732c3-2356-4f60-bf21-956b3652883a": ["city:memphis", "state:tn", "industry:logistics", "seniority:executive"],  # William (Bill) Ramia
    "b76c1ac4-a582-4824-9294-71b14e823da6": ["city:san-francisco", "industry:consulting", "industry:non-profit", "industry:politics", "seniority:executive"],  # Yoni Landau
    "8f71c969-8fe1-494c-a514-715f95c7a637": ["city:washington-dc", "state:dc", "industry:politics", "seniority:executive"],  # Zoë Stein
}