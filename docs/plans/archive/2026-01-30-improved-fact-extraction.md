# Improved Fact Extraction Pipeline

**Date**: 2026-01-30
**Status**: Implementation Complete (Testing Pending)
**PRD Reference**: CRM-UI.md Phase 14

## Executive Summary

Redesign the fact extraction system to be a **recall assistant** rather than a biography builder. Use a multi-stage pipeline with local Ollama for filtering/validation and Claude for deep extraction. Key improvements: message context windows, calibrated confidence scoring, and focus on memorable details.

---

## Current State

**File**: `api/services/person_facts.py`

**Current Flow**:
1. Sample interactions (recent 100 + random 100 + priority sources)
2. Single Claude call with all interactions
3. LLM self-reports confidence in JSON response
4. Save facts with upsert logic

**Problems**:
- Single-pass extraction misses nuance
- Self-reported confidence is unreliable (overconfident)
- Messages taken out of context
- Extracts obvious facts (job title) over memorable ones (dog's name)
- Uses expensive Claude for everything

---

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    STAGE 1: FILTERING (Ollama)                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  For each interaction (with context for messages):                   │
│  "Does this contain memorable personal facts about {person}?"        │
│                                                                      │
│  Input: All interactions (with 5-message context window)             │
│  Output: ~20-50 high-signal interactions                             │
│  Model: llama3.2:3b (local, fast)                                    │
│  Time: ~10-20s                                                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  STAGE 2: DEEP EXTRACTION (Claude)                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Extract memorable personal details from filtered interactions.      │
│  Focus: pet names, hobbies, family, preferences, anecdotes           │
│  Exclude: job titles, company names, obvious professional info       │
│                                                                      │
│  Input: High-signal interactions from Stage 1                        │
│  Output: Candidate facts with source quotes (NO confidence yet)      │
│  Model: claude-sonnet-4                                              │
│  Time: ~5-10s                                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│              STAGE 3: VALIDATION + CONFIDENCE (Ollama)               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  For each candidate fact:                                            │
│  1. Does quote support this fact? (yes/no/partial)                   │
│  2. Who is this about? ({person}/Nathan/third party/unclear)         │
│  3. Evidence strength:                                               │
│     - single_mention (0.3-0.5)                                       │
│     - multiple_mentions (0.5-0.7)                                    │
│     - self_identification (0.7-0.85)                                 │
│     - defining_trait (0.85-0.95)                                     │
│                                                                      │
│  Input: Candidate facts from Stage 2                                 │
│  Output: Validated facts with calibrated confidence                  │
│  Model: llama3.2:3b (local)                                          │
│  Time: ~5-10s                                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Task 1: Message Context Window

**Goal**: Fetch surrounding messages for iMessage/WhatsApp/Slack interactions.

**Changes to `interaction_store.py`**:
```python
def get_conversation_context(
    self,
    interaction_id: str,
    window: int = 5
) -> list[Interaction]:
    """
    Get messages surrounding an interaction in the same conversation.

    For iMessage: same phone number, within time window
    For WhatsApp: same chat_id
    For Slack: same channel_id

    Returns: [5 before] + [target] + [5 after]
    """
```

**Acceptance Criteria**:
- [ ] Query by conversation identifier (phone/chat_id/channel_id)
- [ ] Return messages within reasonable time window (e.g., 24 hours)
- [ ] Handle edge cases (first/last messages in conversation)
- [ ] Add `conversation_id` field to interactions if not present

---

### Task 2: Ollama Client Enhancement

**Goal**: Reliable Ollama client for Stage 1 and Stage 3.

**File**: `api/services/ollama_client.py` (exists, may need updates)

**Required Methods**:
```python
class OllamaClient:
    def is_available(self) -> bool:
        """Check if Ollama is running and model is loaded."""

    def generate(
        self,
        prompt: str,
        model: str = "llama3.2:3b",
        temperature: float = 0.3,
        max_tokens: int = 2048
    ) -> str:
        """Generate completion. Returns raw text."""

    def generate_json(
        self,
        prompt: str,
        model: str = "llama3.2:3b"
    ) -> dict:
        """Generate and parse JSON response."""
```

**Acceptance Criteria**:
- [ ] Health check endpoint `/api/tags` to verify availability
- [ ] Timeout handling (30s default)
- [ ] Retry logic with exponential backoff
- [ ] JSON extraction from response (handle markdown code blocks)

---

### Task 3: Stage 1 - Filtering

**Goal**: Use Ollama to filter interactions to high-signal subset.

**New Function in `person_facts.py`**:
```python
def _stage1_filter_interactions(
    self,
    person_name: str,
    interactions: list[dict]
) -> list[dict]:
    """
    Stage 1: Filter to high-signal interactions using local Ollama.

    For each interaction (batched), ask:
    "Does this contain memorable personal facts about {person}?"

    Returns interactions flagged as containing facts.
    """
```

**Prompt Template**:
```
Review these interactions with {person_name} and identify which ones
contain MEMORABLE personal details worth extracting.

Look for: pet names, hobbies, family members, preferences, anecdotes,
health info, travel, personal stories.

Ignore: job titles, company names, meeting logistics, routine scheduling.

For each interaction, respond with just the ID if it contains memorable facts.

Interactions:
{formatted_interactions}

IDs with memorable facts (one per line):
```

**Acceptance Criteria**:
- [ ] Batch interactions (20-30 per Ollama call)
- [ ] Include message context for iMessage/WhatsApp/Slack
- [ ] Return ~10-30% of interactions (high-signal filter)
- [ ] Fall back to sampling if Ollama unavailable
- [ ] Log filtering stats

---

### Task 4: Stage 2 - Deep Extraction

**Goal**: Claude extracts candidate facts from filtered interactions.

**Update extraction prompt**:
```python
def _build_stage2_extraction_prompt(self, person_name: str, interactions: str) -> str:
    return f"""Extract MEMORABLE personal details about {person_name}.

PRIORITIZE (high value for recall):
- Pet names ("my dog Max", "our cat Luna")
- Hobby specifics ("I've been learning pottery", "training for a triathlon")
- Family member names ("my sister Emma", "my son Jake")
- Preferences ("I can't stand cilantro", "I'm a morning person")
- Personal anecdotes ("We went to Costa Rica last year")
- Health/medical mentions ("I have my infusion next week", "my allergies")
- Interests and passions ("I'm obsessed with Formula 1")

SKIP (low value, findable elsewhere):
- Current job title (LinkedIn has this)
- Company name (LinkedIn has this)
- Generic professional info
- Meeting logistics
- Routine scheduling details

The user can find "{person_name} works at {company}" on LinkedIn.
They CANNOT find "{person_name}'s dog is named Max" anywhere else.

Return JSON (no markdown):
{{
  "facts": [
    {{
      "category": "family",
      "key": "dog_name",
      "value": "Max",
      "quote": "I need to take Max to the vet tomorrow",
      "source_id": "abc123"
    }}
  ]
}}

DO NOT include confidence - that will be assessed separately.

Interactions:
{interactions}"""
```

**Acceptance Criteria**:
- [ ] Prompt emphasizes memorable over obvious
- [ ] Examples show what to include/exclude
- [ ] No confidence in Stage 2 output
- [ ] Source quotes required for all facts

---

### Task 5: Stage 3 - Validation + Confidence

**Goal**: Ollama validates facts and assigns calibrated confidence.

**New Function**:
```python
def _stage3_validate_facts(
    self,
    person_name: str,
    candidate_facts: list[dict],
    interactions: list[dict]
) -> list[PersonFact]:
    """
    Stage 3: Validate facts and assign calibrated confidence.

    For each fact:
    1. Does quote support fact?
    2. Is this about {person} (not Nathan, not third party)?
    3. Evidence strength → confidence score
    """
```

**Prompt Template**:
```
Validate these candidate facts about {person_name}.

For each fact, assess:

1. QUOTE_SUPPORTS: Does the quote directly support this fact?
   - yes: Quote clearly states this fact
   - partial: Quote implies but doesn't directly state
   - no: Quote doesn't support this fact

2. ATTRIBUTION: Who does this fact apply to?
   - target: This is about {person_name}
   - nathan: This is about Nathan (the user), not {person_name}
   - third_party: This is about someone else mentioned in conversation
   - unclear: Can't determine who this applies to

3. EVIDENCE_STRENGTH:
   - single_mention: One casual reference → confidence 0.3-0.5
   - multiple_mentions: Referenced several times → confidence 0.5-0.7
   - self_identification: They explicitly stated this about themselves → confidence 0.7-0.85
   - defining_trait: Central to their identity, repeated → confidence 0.85-0.95

CRITICAL: If ATTRIBUTION is not "target", REJECT the fact.

Return JSON:
{{
  "validations": [
    {{
      "fact_index": 0,
      "quote_supports": "yes",
      "attribution": "target",
      "evidence_strength": "self_identification",
      "confidence": 0.8,
      "reject": false,
      "reject_reason": null
    }}
  ]
}}

Candidate facts:
{facts_json}

Original context:
{context}
```

**Confidence Mapping**:
```python
CONFIDENCE_MAP = {
    "single_mention": (0.3, 0.5),
    "multiple_mentions": (0.5, 0.7),
    "self_identification": (0.7, 0.85),
    "defining_trait": (0.85, 0.95)
}
```

**Acceptance Criteria**:
- [ ] Facts about Nathan rejected
- [ ] Facts about third parties rejected
- [ ] Single mentions capped at 0.5
- [ ] Explicit self-identification required for >0.7
- [ ] Rejected facts logged with reason

---

### Task 6: Pipeline Integration

**Goal**: Wire stages together in `PersonFactExtractor.extract_facts()`.

**Updated Flow**:
```python
def extract_facts(self, person_id: str, person_name: str, interactions: list) -> list[PersonFact]:
    # 1. Add context to message-based interactions
    enriched = self._enrich_with_context(interactions)

    # 2. Stage 1: Filter (Ollama)
    filtered = self._stage1_filter_interactions(person_name, enriched)
    logger.info(f"Stage 1: {len(filtered)}/{len(interactions)} interactions flagged")

    # 3. Stage 2: Extract (Claude)
    candidates = self._stage2_extract_facts(person_name, filtered)
    logger.info(f"Stage 2: {len(candidates)} candidate facts extracted")

    # 4. Stage 3: Validate (Ollama)
    validated = self._stage3_validate_facts(person_name, candidates, filtered)
    logger.info(f"Stage 3: {len(validated)} facts validated")

    # 5. Save validated facts
    saved = []
    for fact in validated:
        saved.append(self.fact_store.upsert(fact))

    return saved
```

**Acceptance Criteria**:
- [ ] Pipeline completes in <60s for typical contact
- [ ] Ollama failures fall back to Claude
- [ ] Progress logged at each stage
- [ ] Stats returned (interactions → filtered → candidates → validated)

---

### Task 7: Relationship Summaries Update

**Goal**: Update summary generation to use new pipeline.

Keep relationship summaries (trajectory, themes, events, style) but:
- Run after fact extraction
- Use validated facts as input
- Lower confidence (0.6-0.7) since synthesized

---

## Testing Plan

### Unit Tests

```python
# tests/test_person_facts_v2.py

def test_stage1_filters_low_signal():
    """Stage 1 should filter out logistics/scheduling messages."""

def test_stage1_keeps_personal_details():
    """Stage 1 should keep messages with pet names, hobbies, etc."""

def test_stage2_extracts_memorable():
    """Stage 2 should extract dog names, not job titles."""

def test_stage3_rejects_nathan_facts():
    """Stage 3 should reject facts about Nathan (the user)."""

def test_stage3_rejects_third_party():
    """Stage 3 should reject facts about third parties."""

def test_stage3_caps_single_mention():
    """Single mentions should not exceed 0.5 confidence."""

def test_context_window_fetched():
    """Message-based interactions should include context."""
```

### Integration Tests

```python
def test_full_pipeline_real_person():
    """Run pipeline on real contact data, verify output quality."""

def test_ollama_fallback():
    """Pipeline completes even if Ollama unavailable."""
```

---

## Migration

No database changes required. New facts will have better calibration. Existing facts remain (user-confirmed facts are preserved).

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Precision | >80% | Manual review of 50 extracted facts |
| Usefulness | >70% | % of facts that are "memorable" not "obvious" |
| Confidence calibration | Single mentions <0.5 | Automated check |
| Entity attribution | <5% wrong person | Manual review |
| Claude cost reduction | 70% | API call count before/after |
| Pipeline time | <60s | Timing logs |

---

## Implementation Order

1. ✅ **Task 2**: Ollama client (foundation) - Enhanced with retry logic, JSON parsing, better health check
2. ✅ **Task 1**: Message context window - Added `get_conversation_context()` and `enrich_interactions_with_context()`
3. ✅ **Task 3**: Stage 1 filtering - `_stage1_filter_interactions()` using Ollama
4. ✅ **Task 4**: Stage 2 extraction prompt - `_build_stage2_extraction_prompt()` focused on memorable facts
5. ✅ **Task 5**: Stage 3 validation - `_stage3_validate_facts()` with calibrated confidence
6. ✅ **Task 6**: Pipeline integration - Updated `extract_facts()` to use 3-stage pipeline
7. ✅ **Task 7**: Summary updates - Lowered confidence to 0.6-0.7 for synthesized summaries
8. **Testing**: Unit + integration tests (pending)

---

## Open Questions

1. **Context window size**: 5 messages enough? Or time-based (15 minutes)?
2. **Ollama model**: llama3.2:3b fast enough? Need larger model?
3. **Batch sizes**: How many interactions per Ollama call?
4. **Existing facts**: Re-extract for everyone, or just new extractions?
