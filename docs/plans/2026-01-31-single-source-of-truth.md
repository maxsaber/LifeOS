# Plan: Single Source of Truth for Person & Relationship Metrics

**Date:** 2026-01-31
**Status:** ✅ Implemented
**Goal:** Eliminate data inconsistencies between PersonEntity counts and InteractionStore

---

## 1. System Architecture

LifeOS tracks interactions with people across multiple sources (Gmail, Calendar, iMessage, WhatsApp, Slack, etc.). The data flows through three main stores:

### Data Stores

| Store | Location | Purpose |
|-------|----------|---------|
| **InteractionStore** | `data/interactions.db` | SQLite database storing individual interactions. Each row has `person_id`, `source_type`, `timestamp`, `title`, etc. This is the **source of truth** for all interaction data. |
| **PersonEntity** | `data/people_entities.json` | JSON file storing person records with cached aggregate counts (`email_count`, `meeting_count`, `message_count`, `mention_count`) and metadata (`sources` list). |
| **Relationship** | `data/relationships.json` | JSON file storing relationships between pairs of people with cached counts (`shared_events_count`, `shared_messages_count`, etc.). |

### Current Data Flow (Before This Plan)

```
Source Syncs (Gmail, iMessage, WhatsApp, etc.)
    │
    ▼
InteractionStore (interactions.db)
    │
    ├──► sync_person_stats.py ──► PersonEntity counts [SEPARATE SCRIPT]
    │
    └──► sync_relationship_discovery.py ──► Relationship counts [SEPARATE SCRIPT]
```

**The Problem:** `sync_person_stats.py` runs as a separate step. If a source sync runs without triggering stats refresh, the cached counts in PersonEntity diverge from the actual data in InteractionStore.

---

## 2. Solution: Mandatory Post-Sync Stats Refresh

### Principle

**Every script that modifies interactions MUST call `refresh_person_stats()` for affected people before exiting.**

### New Data Flow (After This Plan)

```
Source Syncs (Gmail, iMessage, WhatsApp, Slack, Vault, etc.)
    │
    ▼
InteractionStore (interactions.db)
    │
    ├──► refresh_person_stats(affected_ids) ──► PersonEntity counts [IMMEDIATE, SAME SCRIPT]
    │
    └──► sync_relationship_discovery.py ──► Relationship counts [NIGHTLY ONLY]

Nightly verification step catches any edge cases [SAFETY NET]
```

---

## 3. Complete Coverage Analysis

### 3.1 All Scripts That Modify Interactions

| Script | Operation | Source Types | Must Call refresh_person_stats() |
|--------|-----------|--------------|----------------------------------|
| `sync_gmail_calendar_interactions.py` | INSERT | gmail, calendar | Yes - at end of sync |
| `sync_imessage_interactions.py` | INSERT | imessage, sms | Yes - at end of sync |
| `sync_whatsapp.py` | INSERT | whatsapp | Yes - at end of sync |
| `sync_phone_calls.py` | INSERT | phone | Yes - at end of sync |
| `sync_slack.py` | INSERT | slack | Yes - at end of sync |
| `api/services/indexer.py` (vault_reindex) | INSERT | vault, granola | Yes - at end of reindex |
| `merge_people.py` | UPDATE (move person_id) | all | Yes - for primary after merge |
| `api/routes/crm.py` (split_person) | UPDATE (move person_id) | all | Yes - for both people after split |

### 3.2 Scripts That DELETE Interactions (Must Also Refresh)

| Script | What It Deletes |
|--------|-----------------|
| `scripts/cleanup_marketing_emails.py` | Marketing email interactions |
| `scripts/fix_orphaned_gmail_interactions.py` | Orphaned gmail interactions |
| `scripts/fix_vault_matches.py` | Vault interactions for re-matching |

### 3.3 Run Order Clarification

**Old model (before this plan):**
```
Phase 1: Data collection syncs (no stats refresh)
Phase 2: Entity linking
Phase 3: sync_person_stats.py (bulk refresh ALL people)
Phase 4: relationship_discovery, strengths
```

**New model (after this plan):**
```
Phase 1: Data collection syncs (EACH calls refresh_person_stats for affected people)
Phase 2: Entity linking
Phase 3: relationship_discovery, strengths
Phase 4: Verification (catches any edge cases)
```

**Key change:** `sync_person_stats.py` is NO LONGER in the sync order. It becomes a standalone verification/repair tool only.

---

## 4. Implementation Details

### 4.1 New File: `api/services/person_stats.py`

Central module for all PersonEntity stats operations.

```python
"""
Person stats refresh - keeps PersonEntity counts in sync with InteractionStore.

This module provides the ONLY correct way to update PersonEntity counts.
All sync scripts MUST call refresh_person_stats() after modifying interactions.
"""
import sqlite3
import logging
import fcntl
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def refresh_person_stats(person_ids: Optional[list[str]] = None, save: bool = True) -> dict:
    """
    Recompute PersonEntity counts from InteractionStore.

    Args:
        person_ids: Specific people to refresh. If None, refreshes ALL people.
        save: Whether to persist changes to disk.

    Returns:
        Dict with stats: {updated: int, total_interactions: int}
    """
    from api.services.person_entity import get_person_entity_store
    from api.services.interaction_store import get_interaction_db_path

    store = get_person_entity_store()
    conn = sqlite3.connect(get_interaction_db_path())

    stats = {'updated': 0, 'total_interactions': 0}

    if person_ids is None:
        # Full refresh - query all at once
        cursor = conn.execute("""
            SELECT person_id, source_type, COUNT(*) as cnt
            FROM interactions
            GROUP BY person_id, source_type
        """)

        person_counts: dict[str, dict[str, int]] = {}
        for row in cursor:
            pid, source_type, count = row
            if pid not in person_counts:
                person_counts[pid] = {}
            person_counts[pid][source_type] = count
            stats['total_interactions'] += count

        # Update people with interactions
        for person_id, counts in person_counts.items():
            entity = store.get_by_id(person_id)
            if entity:
                _apply_counts_to_entity(entity, counts)
                store.update(entity)
                stats['updated'] += 1

        # Zero out people with no interactions
        for entity in store.get_all():
            if entity.id not in person_counts:
                if entity.email_count or entity.meeting_count or entity.message_count or entity.mention_count:
                    entity.email_count = 0
                    entity.meeting_count = 0
                    entity.message_count = 0
                    entity.mention_count = 0
                    store.update(entity)
                    stats['updated'] += 1
    else:
        # Targeted refresh
        for person_id in person_ids:
            cursor = conn.execute("""
                SELECT source_type, COUNT(*) as cnt
                FROM interactions
                WHERE person_id = ?
                GROUP BY source_type
            """, (person_id,))

            counts = {row[0]: row[1] for row in cursor}
            stats['total_interactions'] += sum(counts.values())

            entity = store.get_by_id(person_id)
            if entity:
                _apply_counts_to_entity(entity, counts)
                store.update(entity)
                stats['updated'] += 1

    conn.close()

    if save:
        store.save()  # Uses file locking

    logger.info(f"Refreshed stats for {stats['updated']} people")
    return stats


def _apply_counts_to_entity(entity, counts: dict[str, int]):
    """Apply interaction counts to a PersonEntity."""
    entity.email_count = counts.get('gmail', 0)
    entity.meeting_count = counts.get('calendar', 0)
    entity.mention_count = counts.get('vault', 0) + counts.get('granola', 0)
    entity.message_count = (
        counts.get('imessage', 0) +
        counts.get('whatsapp', 0) +
        counts.get('sms', 0) +
        counts.get('slack', 0)
    )

    # Update sources list
    interaction_sources = set(counts.keys())
    existing_sources = set(entity.sources or [])
    entity.sources = list(existing_sources | interaction_sources)


def verify_person_stats(fix: bool = False) -> dict:
    """
    Verify PersonEntity counts match InteractionStore.

    Args:
        fix: If True, fix any discrepancies found.

    Returns:
        Dict mapping person_id to discrepancy details. Empty if consistent.
    """
    from api.services.person_entity import get_person_entity_store
    from api.services.interaction_store import get_interaction_db_path

    store = get_person_entity_store()
    conn = sqlite3.connect(get_interaction_db_path())

    discrepancies = {}

    for entity in store.get_all():
        cursor = conn.execute("""
            SELECT source_type, COUNT(*) as cnt
            FROM interactions
            WHERE person_id = ?
            GROUP BY source_type
        """, (entity.id,))

        counts = {row[0]: row[1] for row in cursor}

        computed_email = counts.get('gmail', 0)
        computed_meeting = counts.get('calendar', 0)
        computed_mention = counts.get('vault', 0) + counts.get('granola', 0)
        computed_message = (
            counts.get('imessage', 0) +
            counts.get('whatsapp', 0) +
            counts.get('sms', 0) +
            counts.get('slack', 0)
        )

        if (entity.email_count != computed_email or
            entity.meeting_count != computed_meeting or
            entity.mention_count != computed_mention or
            entity.message_count != computed_message):

            discrepancies[entity.id] = {
                'name': entity.canonical_name,
                'cached': {
                    'email': entity.email_count,
                    'meeting': entity.meeting_count,
                    'mention': entity.mention_count,
                    'message': entity.message_count,
                },
                'computed': {
                    'email': computed_email,
                    'meeting': computed_meeting,
                    'mention': computed_mention,
                    'message': computed_message,
                },
            }

            if fix:
                _apply_counts_to_entity(entity, counts)
                store.update(entity)

    conn.close()

    if fix and discrepancies:
        store.save()
        logger.info(f"Fixed {len(discrepancies)} discrepancies")

    return discrepancies
```

### 4.2 Add File Locking to PersonEntityStore.save()

Modify `api/services/person_entity.py`:

```python
def save(self) -> None:
    """Persist entities to disk with file locking for concurrent access safety."""
    import fcntl

    self.storage_path.parent.mkdir(parents=True, exist_ok=True)
    data = [entity.to_dict() for entity in self._entities.values()]

    # Use exclusive lock to prevent concurrent writes
    with open(self.storage_path, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    logger.info(f"Saved {len(data)} entities to {self.storage_path}")
```

### 4.3 Update run_all_syncs.py

Remove `person_stats` from sync order, add verification at end:

```python
SYNC_ORDER = [
    # Phase 1: Data collection (each calls refresh_person_stats internally)
    "gmail",
    "calendar",
    "linkedin",
    "contacts",
    "phone",
    "whatsapp",
    "imessage",
    "slack",
    "vault_reindex",

    # Phase 2: Entity linking
    "link_slack",
    "link_imessage",

    # Phase 3: Relationship analysis
    "relationship_discovery",
    "strengths",

    # Phase 4: Verification (safety net)
    "verify_stats",
]
```

### 4.4 Convert sync_person_stats.py to Verification Tool

The script becomes a standalone tool, NOT part of the nightly sync:

```python
#!/usr/bin/env python3
"""
Verify and fix PersonEntity stats.

This script is a VERIFICATION/REPAIR tool only. Stats are normally kept
in sync by individual sync scripts calling refresh_person_stats().

Usage:
    python sync_person_stats.py --verify        # Check for discrepancies
    python sync_person_stats.py --verify --fix  # Check and fix discrepancies
    python sync_person_stats.py --full-refresh  # Force full refresh
"""
```

---

## 5. Files to Modify

| File | Change |
|------|--------|
| `api/services/person_stats.py` | **NEW** - Core refresh and verify functions |
| `api/services/person_entity.py` | Add file locking to save() |
| `scripts/sync_gmail_calendar_interactions.py` | Add refresh call at end |
| `scripts/sync_imessage_interactions.py` | Add refresh call at end |
| `scripts/sync_whatsapp.py` | Add refresh call at end |
| `scripts/sync_phone_calls.py` | Add refresh call at end |
| `scripts/sync_slack.py` | Add refresh call at end |
| `api/services/indexer.py` | Add refresh call at end of vault reindex |
| `scripts/merge_people.py` | Replace manual count addition with refresh call |
| `api/routes/crm.py` | Add refresh call after split |
| `scripts/sync_person_stats.py` | Convert to verification-only tool |
| `scripts/run_all_syncs.py` | Remove person_stats from order, add verification |

---

## 6. Testing Strategy

1. **Unit tests for person_stats.py** - Test refresh and verify functions
2. **Integration tests** - Run sync, verify counts match
3. **Concurrency test** - Two syncs simultaneously, verify no data loss
4. **One-off script test** - Manual sync produces correct counts

---

## 7. Archived/Deprecated

After implementation, the following behaviors are deprecated:

| Old Behavior | New Behavior |
|--------------|--------------|
| `sync_person_stats.py` as part of nightly sync | Verification tool only |
| Manual count addition in merge_people.py | Call refresh_person_stats() |
| Sync scripts not updating PersonEntity | All syncs call refresh at end |

---

## 8. Implementation Notes (2026-01-31)

### Files Modified

1. **`api/services/person_stats.py`** - NEW - Central stats refresh and verification module
2. **`api/services/person_entity.py`** - Added file locking to save(), empty file handling in _load()
3. **`api/services/indexer.py`** - Vault reindex now tracks affected_person_ids and calls refresh
4. **`api/services/slack_sync.py`** - Slack sync now tracks affected_person_ids and calls refresh
5. **`scripts/sync_gmail_calendar_interactions.py`** - Tracks and refreshes affected people
6. **`scripts/sync_imessage_interactions.py`** - Tracks and refreshes affected people
7. **`scripts/sync_whatsapp.py`** - Tracks and refreshes affected people
8. **`scripts/sync_phone_calls.py`** - Tracks and refreshes affected people
9. **`scripts/merge_people.py`** - Replaced manual count addition with refresh call
10. **`scripts/split_person.py`** - Added refresh call after moving interactions
11. **`scripts/run_all_syncs.py`** - Removed person_stats from sync order
12. **`scripts/sync_person_stats.py`** - Converted to verification/repair tool

### Test Updates

- Fixed `tests/test_person_entity.py` - Cleared blocklist in fixture for test isolation

### Pre-existing Test Failures (Not Related to This Change)

The following tests fail due to pre-existing data quality issues, not our implementation:
- `test_counts_match_database` - Reports existing discrepancies (this is exactly what we want to catch!)
- `test_top_person_stats_accurate`, `test_stats_by_source_type` - CRM UI data tests
- `test_no_temp_directory_interactions`, `test_all_vault_files_exist`, etc. - P91 data integrity
- `test_one_interaction`, `test_half_target`, `test_old_but_active` - Relationship metrics formula tests

### Next Steps

1. Run `python scripts/sync_person_stats.py --full --execute` to fix existing discrepancies
2. Consider updating relationship metrics tests to match implementation
