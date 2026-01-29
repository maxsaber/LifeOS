# CRM P9.1: Data Integrity Requirements

## Overview

This document defines strict requirements for CRM data integrity. Each requirement has associated automated tests that MUST pass before the requirement is considered complete.

**Verification Method**: All requirements verified by:
1. Automated pytest tests
2. Browser-based UI verification using Playwright

---

## R1: Clean Interaction Database

**Requirement**: The interaction database must contain only real data, no test pollution.

**Acceptance Criteria**:
- [ ] No interactions with source_id pointing to /tmp or /var/folders paths
- [ ] All vault interactions point to files that actually exist
- [ ] All interactions have valid person_id that exists in PersonEntity store

**Test**: `tests/test_p91_data_integrity.py::TestR1CleanDatabase`

---

## R2: Correct Entity Resolution

**Requirement**: When a person is linked to a vault note, that person MUST actually be mentioned in the note content.

**Acceptance Criteria**:
- [ ] For any vault interaction, the linked person's name/alias appears in the note
- [ ] No false positive links (person linked but not mentioned)
- [ ] Sample verification: Check 20 random vault interactions

**Test**: `tests/test_p91_data_integrity.py::TestR2EntityResolution`

---

## R3: Working Vault Links

**Requirement**: Vault links in the timeline must open the correct note.

**Acceptance Criteria**:
- [ ] source_id contains valid file path
- [ ] File exists at that path
- [ ] obsidian:// URL can be constructed from path
- [ ] Browser test: Click vault link, verify it attempts to open Obsidian

**Test**: `tests/test_p91_data_integrity.py::TestR3VaultLinks`

---

## R4: Working Gmail Links

**Requirement**: Gmail links in timeline must open the specific email, not just inbox.

**Acceptance Criteria**:
- [ ] Gmail interactions have message_id in source_id
- [ ] Link format: `https://mail.google.com/mail/u/0/#inbox/{message_id}`
- [ ] Browser test: Click gmail link, verify URL contains message_id

**Test**: `tests/test_p91_data_integrity.py::TestR4GmailLinks`

---

## R5: Working Calendar Links

**Requirement**: Calendar links must open the specific event.

**Acceptance Criteria**:
- [ ] Calendar interactions have event_id in source_id
- [ ] Link format: `https://calendar.google.com/calendar/event?eid={base64_event_id}`
- [ ] Browser test: Click calendar link, verify URL format

**Test**: `tests/test_p91_data_integrity.py::TestR5CalendarLinks`

---

## R6: Accurate Interaction Counts

**Requirement**: PersonEntity counts must match actual interactions in database.

**Acceptance Criteria**:
- [ ] email_count = COUNT of gmail interactions for that person
- [ ] meeting_count = COUNT of calendar interactions for that person
- [ ] mention_count = COUNT of vault+granola interactions for that person
- [ ] Verified for top 10 people by interaction count

**Test**: `tests/test_p91_data_integrity.py::TestR6InteractionCounts`

---

## R7: Taylor Test Case (Canonical)

**Requirement**: Taylor Walker must have correct, verifiable data.

**Acceptance Criteria**:
- [ ] Found by email: annetaylorwalker@gmail.com
- [ ] Found by phone: +19012295017
- [ ] Has interactions from at least 2 different sources
- [ ] Every vault interaction linked to Taylor actually mentions "Taylor" or "Tay"
- [ ] relationship_strength > 0 (calculated from real data)
- [ ] Browser: Taylor visible in CRM list with non-zero interaction count
- [ ] Browser: Taylor's timeline shows real interactions with working links

**Test**: `tests/test_p91_data_integrity.py::TestR7TaylorCanonical`

---

## R8: Top 10 Verification

**Requirement**: Top 10 contacts must all have valid, verifiable data.

**Acceptance Criteria**:
- [ ] All have interaction_count > 0
- [ ] All have at least one interaction with valid source link
- [ ] No one in top 10 should have only test/garbage data
- [ ] Browser: All 10 visible with correct counts

**Test**: `tests/test_p91_data_integrity.py::TestR8Top10Verification`

---

## R9: Browser UI Verification

**Requirement**: The CRM UI must display correct data from the user's perspective.

**Acceptance Criteria**:
- [ ] /crm page loads without errors
- [ ] People list shows people sorted by relationship strength
- [ ] Clicking a person shows their details with non-zero stats
- [ ] Timeline tab shows interactions with dates and sources
- [ ] Clicking a vault link attempts to open obsidian://
- [ ] Clicking a gmail link goes to mail.google.com with message ID

**Test**: `tests/test_p91_browser.py::TestR9BrowserUI`

---

## Execution Order

1. **R1**: Clean database (removes test pollution)
2. **R2**: Fix entity resolution (ensures correct links)
3. **R3-R5**: Fix link formats (ensures clickable links)
4. **R6**: Sync counts (ensures accurate stats)
5. **R7**: Verify Taylor (canonical test case)
6. **R8**: Verify top 10 (ensures not overfitting to Taylor)
7. **R9**: Browser verification (user perspective)

---

## Test Command

```bash
# Run all P9.1 requirements tests
PYTHONPATH=. pytest tests/test_p91_data_integrity.py tests/test_p91_browser.py -v

# Run specific requirement
PYTHONPATH=. pytest tests/test_p91_data_integrity.py::TestR1CleanDatabase -v
```

---

## Completion Criteria

P9.1 is complete when:
1. All 9 requirement test classes pass
2. Browser tests verify UI displays correct data
3. No test data pollution remains
4. Links are clickable and work
