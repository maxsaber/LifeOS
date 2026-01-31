# Entity Resolution Refactor

**Date:** 2026-01-30
**Status:** Complete

## Problem Statement
The original `token_set_ratio` algorithm was too permissive, causing false matches like "Mary Katherine Palmer" → "Taylor Walker" (56% character similarity).

## Solution: Structured Name Matching

### Phase 1: Generate Candidates

For each entity in the store:

1. **Parse names** into `{first, middles[], last}` structure
   - Strip prefixes: Dr., Mr., Mrs., Ms., Prof., Rev.
   - Strip suffixes: MD, PhD, Jr, Sr, II, III, MBA, etc.

2. **Hard disqualifiers** (skip candidate entirely):
   - Different last names when both names have last names
   - Full name query with no first name similarity (prevents "John Walker" → "Taylor Walker")
   - First-name-only query with no first name match (prevents "Sarah" matching "Taylor" via context-only)
   - Note: Initials count as matches ("J Walker" → "John Walker" works)

3. **Score calculation**:
   | Signal | Points |
   |--------|--------|
   | Exact last name | 50 |
   | Last name initial prefix | 35 |
   | Fuzzy last name (85%+) | 25 |
   | Exact first name | 25 |
   | Fuzzy first name (85%+) | 20 |
   | First/last name initial | 10 |
   | First=middle cross-match | 15 |
   | Context boost | 30 |
   | Recency boost (< 30 days) | 10 |
   | Relationship strength | 0-25 |

4. Add to candidates if score ≥ 20

### Phase 2: Evaluate Candidates

1. Sort candidates by score (descending)
2. Check if top score ≥ MIN_MATCH_SCORE (40)
3. **First-name-only special handling**:
   - Only 1 candidate total → match (unique) +15 bonus
   - Only 1 passes threshold → match (context disambiguates) +10 bonus
   - Multiple pass, one has 20+ point lead → match to leader +10 bonus
   - Multiple pass, one has relationship_strength ≥ 30 uniquely → match +15 bonus
   - Multiple close candidates (similar scores, similar relationship) → **REFUSE** (ambiguous)
4. Check disambiguation threshold between top 2 candidates
5. Return best match or None

## Test Cases (All Passing)

| Query | Entities | Expected | Result |
|-------|----------|----------|--------|
| "Ben" | Ben Calvin (60), Ben Warren (55) | No match (ambiguous) | ✅ |
| "Ben" | Ben Calvin (60), Ben Smith (10) | Ben Calvin (dominant) | ✅ |
| "Yoni" | Yoni Landau (70) | Yoni Landau (unique close) | ✅ |
| "Taylor" | Taylor Walker (15) | Taylor Walker (unique) | ✅ |
| "Taylor" | Taylor Walker (15), Taylor Smith (12) | No match (ambiguous) | ✅ |
| "Sarah" + murm_context | Sarah Chen (ML), Sarah Miller (Murm) | Sarah Miller (context) | ✅ |
| "Ben Calvin" | Ben Calvin, Ben Warren | Ben Calvin (full name) | ✅ |
| "Mary Katherine Palmer" | Taylor Walker | No match (different last name) | ✅ |

## Key Design Decisions

1. **Last name is most important** (50 pts vs 25 pts for first) - last names are more distinctive
2. **First-name-only requires actual first name match** - prevents context-only matches
3. **Multiple close candidates = refuse** - better to not match than match wrong person
4. **Context can disambiguate** when only one candidate passes threshold
5. **Relationship strength breaks ties** between otherwise equal candidates

## Files Modified

- `api/services/entity_resolver.py` - Complete rewrite of `_score_candidates()`
- `tests/test_entity_resolver.py` - Added 14 new tests for parse_name and structured matching

## Algorithm Improvements

### Comma-Separated Suffix Handling
Added support for stripping credentials after commas (e.g., "Sarah Long, CLC, CSC" → first="Sarah", last="Long").

## Data Cleanup (Post-Refactor)

After implementing the new algorithm, audited existing data for bad matches caused by the old permissive algorithm.

### LinkedIn Matches Fixed (38 total)

User reviewed all 75 suspicious LinkedIn matches and classified them. Fixed 38 incorrect matches by clearing linkedin_url, company, and position:

**Initial fixes (5):**
- Taylor Walker (mary-katherine-palmer)
- Madeline Eden (denismikush)
- Samuel Miller (amitpatel2008)
- Sarah Long (val-sanin)

**CSV-based fixes (34):**
- Emilia Pierce, Santiago Martinez, Brandon Larson, "." entity, Sarah (first-name only)
- Anne Barkett, T H, Mark Mullen, Eric Larson, Jen Nicole, Ami Patel
- Matt Wilhelm, David Hudson, M P, Larry Stein, Kate Edwards, Charles Stewart
- M L, Christina Lah, Jack Wallace, Caitlin Chicu, Gregory Gause, Adam Young
- Christina Brugger, Cort Mukina, Sheryn Lee, Jennifer, Jewell, Kay Klunder
- Michael Pak, PFC Rodriguez, Richard, Sean, Bo

**Restored (1):**
- Tamara Miller (liliomere) - confirmed correct by user

### Vault Matches Fixed

User reviewed 60 ambiguous vault matches (first-name-only entities with shared names).

**Reassignments (422):**
- Ben → Ben Calvin (45)
- Malea → Malea Ramia (41)
- Dan → context-based (Dan Porter if BlueLabs, Dan McSwain if Murm) (34)
- Kat → Kat Atwater (26)
- Valerie → Valerie Bradley (22)
- Sarah → context-based (Sarah Long if ML, Sarah Esty if Personal) (19)
- Ed → Ed Niles (21)
- Hayley → Hayley Currier (20)
- Evan → Evan Burfield (16)
- Erek → Erek Dyskant (16)
- Kate → Kate Dahl (BlueLabs only) (14)
- Harrison → Harrison Kreisberg (14)
- Isaac → Isaac Flores-Huerta (12)
- Elly → Elly Teitsworth (12)
- Joel → Joel Shuman (11)
- Amir → Amir Stepak (10)
- Max → context-based (8)
- And 20+ more simple reassignments

**Deleted (132):**
Removed incorrectly linked vault interactions where no valid match exists:
- Rep (16), Speaker 0 (16), Colin (9), Chris (8), Andrew (8), Tait (8)
- Emily (7), Josh (7), Alex (5), Amanda (5), Tanya (5), Grace (5), Wendy (5)
- Mark (4), Aaron (4), Matt (4), Scott (4), Jackie (4), Beth (4), Tom (4)

### Scripts Created

- `scripts/fix_taylor_walker.py` - Single fix for Taylor Walker
- `scripts/fix_linkedin_mismatches.py` - Batch fix for confirmed bad matches
- `scripts/fix_linkedin_from_csv.py` - CSV-driven LinkedIn cleanup
- `scripts/fix_vault_matches.py` - CSV-driven vault match corrections
