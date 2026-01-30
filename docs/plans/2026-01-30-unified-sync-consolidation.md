# Unified Sync Consolidation Plan

**Date:** 2026-01-30
**Status:** Complete

## Problem Statement

Currently there are two separate sync processes:
- **3AM Nightly Sync** (`api/main.py`): Vault reindex, People v2 sync, Google Docs/Sheets, iMessage, Slack
- **6AM CRM Sync** (`scripts/run_all_syncs.py`): Gmail, Calendar, Contacts, Phone, WhatsApp, iMessage, Slack, relationship discovery, stats

Issues:
1. **Wrong order**: Vault reindex at 3AM uses stale data from previous 6AM sync
2. **Duplication**: Gmail, Calendar, iMessage, Slack are synced in both
3. **Data lag**: Vector store is always a day behind CRM data
4. **Confusion**: Two separate systems doing overlapping things

## Solution: Single Unified Sync

Consolidate into one daily sync with proper dependency ordering:

```
Phase 1: Data Collection (no dependencies)
Phase 2: Entity Processing (depends on Phase 1)
Phase 3: Relationship Building (depends on Phase 2)
Phase 4: Vector Store Indexing (depends on Phases 1-3)
Phase 5: Content Sync (can run in parallel with Phase 4)
```

## Detailed Phase Design

### Phase 1: Data Collection
Collect fresh data from all external sources into local stores.

| Step | Script | Writes To | Dependencies |
|------|--------|-----------|--------------|
| 1.1 | sync_gmail_calendar_interactions.py --source gmail | interactions.db | None |
| 1.2 | sync_gmail_calendar_interactions.py --source calendar | interactions.db | None |
| 1.3 | sync_contacts_csv.py | crm.db (source_entities) | None |
| 1.4 | sync_phone_calls.py | interactions.db | None |
| 1.5 | sync_whatsapp.py | interactions.db, crm.db | None |
| 1.6 | sync_imessage_interactions.py | interactions.db | None |
| 1.7 | sync_slack.py | crm.db, ChromaDB (lifeos_slack) | None |
| 1.8 | sync_linkedin.py (NEW) | people_entities.json | None |

### Phase 2: Entity Processing
Link source entities to canonical people.

| Step | Script | Writes To | Dependencies |
|------|--------|-----------|--------------|
| 2.1 | link_slack_entities.py | crm.db (source_entities) | 1.7 |

### Phase 3: Relationship Building
Build relationships and compute metrics.

| Step | Script | Writes To | Dependencies |
|------|--------|-----------|--------------|
| 3.1 | sync_relationship_discovery.py | crm.db (relationships) | Phase 2 |
| 3.2 | sync_person_stats.py | people_entities.json | 3.1 |
| 3.3 | sync_strengths.py | crm.db (relationships) | 3.2 |

### Phase 4: Vector Store Indexing
Index content with fresh people data available.

| Step | Script/Function | Writes To | Dependencies |
|------|-----------------|-----------|--------------|
| 4.1 | Vault reindex | ChromaDB (lifeos), BM25 | Phase 3 |
| 4.2 | Calendar index | ChromaDB (lifeos_calendar) | Phase 1 |

### Phase 5: Content Sync
Pull external content into vault (can run parallel with Phase 4).

| Step | Script/Function | Writes To | Dependencies |
|------|-----------------|-----------|--------------|
| 5.1 | Google Docs sync | Vault (markdown) | None |
| 5.2 | Google Sheets sync | Vault (markdown) | None |

## Implementation Tasks

### Task 1: Create LinkedIn Sync Script ✅
- [x] Create `scripts/sync_linkedin.py` to sync LinkedIn CSV to PersonEntity
- [x] Extract logic from `people_aggregator.py::sync_linkedin_to_v2()`
- [x] Add to SYNC_SOURCES in sync_health.py

### Task 2: Create Vault Reindex Script ✅
- [x] Create `scripts/sync_vault_reindex.py` to trigger vault reindexing
- [x] Use existing `IndexerService.index_all()`
- [x] Add to SYNC_SOURCES in sync_health.py

### Task 3: Create Content Sync Scripts ✅
- [x] Create `scripts/sync_google_docs.py` wrapper
- [x] Create `scripts/sync_google_sheets.py` wrapper
- [x] Add to SYNC_SOURCES in sync_health.py

### Task 4: Update run_all_syncs.py ✅
- [x] Reorganize SYNC_ORDER into phases
- [x] Add new scripts (linkedin, vault_reindex, google_docs, google_sheets)
- [x] Add phase comments for clarity

### Task 5: Simplify 3AM Nightly Sync ✅
- [x] Remove redundant syncs from `api/main.py::_nightly_sync_loop`
- [x] Keep only: notification collection, health checks
- [x] Removed all duplicate sync operations, now only does health monitoring

### Task 6: Update Documentation ✅
- [x] Update docs/architecture/DATA-AND-SYNC.md with new unified sync
- [x] Update plan document with completion status

### Task 7: Update launchd Configuration
- [ ] launchd already configured for 6AM via com.lifeos.crm-sync
- [ ] No changes needed - existing configuration works with unified sync

## File Changes Summary

### New Files
- `scripts/sync_linkedin.py`
- `scripts/sync_vault_reindex.py`
- `scripts/sync_google_docs.py`
- `scripts/sync_google_sheets.py`

### Modified Files
- `scripts/run_all_syncs.py` - Add phases and new scripts
- `api/services/sync_health.py` - Add new SYNC_SOURCES
- `api/main.py` - Simplify or remove 3AM sync
- `docs/architecture/DATA-AND-SYNC.md` - Update documentation

## Rollback Plan

If issues arise:
1. Restore original `run_all_syncs.py` from git
2. Restore original `api/main.py` from git
3. Both syncs can run independently

## Success Criteria

1. Single daily sync completes successfully
2. Vector store has fresh data (not day-old)
3. No duplicate processing
4. All existing functionality preserved
5. Documentation is accurate and up-to-date

## Progress Log

- [x] Task 1: Create LinkedIn Sync Script
- [x] Task 2: Create Vault Reindex Script
- [x] Task 3: Create Content Sync Scripts
- [x] Task 4: Update run_all_syncs.py
- [x] Task 5: Simplify 3AM Nightly Sync
- [x] Task 6: Update Documentation
- [x] Task 7: Update launchd Configuration (no changes needed)

## Additional Changes Made

- **Relationship Discovery Window**: Changed from 180 days to 3650 days (~10 years) to process all historical data
- **Successfully ran relationship_discovery**: 2214 relationships updated with edge weights
- **Gmail sync already supports sent + received + CC**: No changes needed, existing code handles all email types
