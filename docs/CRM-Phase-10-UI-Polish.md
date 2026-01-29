# CRM Phase 10: UI Polish and Quality Improvements

## Overview
Address usability issues, fix broken features, and improve data quality based on user feedback.

---

## Task 1: Timeline Aggregation Fix
**Priority: High**

### Problem
Timeline grouping by day+type is not working properly. Should work in:
1. Main timeline view
2. Expandable sources list on Overview tab

### Requirements
- Multiple iMessages on same day = ONE expandable row showing "27 iMessages"
- Clicking expands to show individual messages
- Same pattern for emails, meetings, calls
- Works in both Timeline tab AND Overview sources section

### Verification
- View person with 50+ messages in a day
- See single grouped row, not 50 individual rows
- Click to expand and see all 50

---

## Task 2: Graph View - Second-Degree Connections
**Priority: High**

### Current Behavior
Graph only shows first-degree connections (direct contacts)

### Required Behavior
1. Show second-degree connections (connections of connections)
2. Clicking a node:
   - Switches to that person's detail view
   - Stays on graph tab
   - Re-centers graph on clicked person
   - Shows THEIR second-degree connections
3. Visual distinction between:
   - Central person (largest node)
   - First-degree connections (medium nodes)
   - Second-degree connections (smaller nodes)

### API Changes
- Modify `/api/crm/network` to support `depth=2` properly
- Return relationship distance in node data

---

## Task 3: Remove Unused UI Elements
**Priority: Medium**

### Elements to Remove
1. **Edit button** - Remove entirely
2. **Refresh button** - Remove if non-functional, or make functional
3. **"Pending" indicator** at top - Remove or explain purpose

### Verification
- UI is cleaner with fewer confusing elements

---

## Task 4: Connections Tab Clarification
**Priority: Medium**

### Problem
Purpose of Connections tab is unclear

### Options
1. **Remove it** if redundant with Graph view
2. **Clarify it** with better labeling and purpose
3. **Merge with Graph** if they serve similar purposes

### Decision Required
What should Connections tab do that Graph doesn't?

---

## Task 5: Low-Confidence Match Review UI
**Priority: High**

### Problem
No visible way to access the review queue from UI

### Requirements
1. Add visible "Review Queue" button/badge in CRM header
2. Badge shows count of pending reviews
3. Clicking opens modal/panel with:
   - Source entity details
   - Proposed match with confidence %
   - Confirm/Reject buttons
   - Auto-advance to next item

### API
Already exists: `GET /api/crm/review-queue`

---

## Task 6: Quick Facts Quality Overhaul
**Priority: Critical**

### Current Problems
1. Only analyzes last 50 interactions (misses most history)
2. ~50% accuracy rate
3. Makes assumptions without evidence
4. Cannot navigate to source context
5. Superficial observations

### Required Improvements

#### 6a. Full History Analysis
- Analyze ALL interactions, not just 50
- Process in batches if needed for context limits
- Aggregate findings across batches

#### 6b. Source Attribution with Navigation
- Each fact links to source interaction
- Clicking fact opens source (email, message, note)
- Show snippet of source text on hover

#### 6c. Quality Standards
- Only include facts with high confidence
- Require explicit evidence in source material
- No assumptions or inferences without quotes
- Include verbatim quotes when possible

#### 6d. Interaction Summaries
Add new fact category: "Relationship Summary"
- Key themes in conversations
- Major events/milestones
- Recurring topics
- Relationship trajectory

#### 6e. Extraction Prompt Improvements
- Be more conservative
- Require citation
- Flag uncertainty
- Multi-pass extraction for validation

---

## Task 7: Interaction History Grid Improvements
**Priority: Medium**

### Current Problems
1. Squares too large
2. No hover information
3. Not clickable
4. Only 90 days shown

### Required Changes
1. **365 days** instead of 90
2. **Smaller squares** (~8px, GitHub-style contribution graph)
3. **Hover tooltip** showing:
   - Date (Jan 26, 2026)
   - Breakdown by type (27 iMessages, 3 emails, 1 meeting)
   - Total count
4. **Click to navigate** to timeline filtered to that day

### Layout
- 52 weeks x 7 days grid
- Month labels along top
- Color intensity = interaction count

---

## Task 8: Visual UI Review with Browser Automation
**Priority: Medium**

### Approach
Use Playwright/Chrome to:
1. Take screenshots of all CRM pages
2. Identify visual issues
3. Test user flows
4. Verify interactions work

### Areas to Review
- Person list layout
- Person detail panel
- Timeline rendering
- Graph interactivity
- Facts display
- Mobile responsiveness

---

## Implementation Order

1. **Task 1**: Timeline aggregation fix (blocking usability)
2. **Task 5**: Review queue UI (important feature)
3. **Task 6**: Quick Facts overhaul (data quality)
4. **Task 2**: Graph second-degree connections
5. **Task 3**: Remove unused elements
6. **Task 4**: Connections tab decision
7. **Task 7**: Visual review

---

## Success Criteria

- [ ] Timeline shows grouped interactions that expand
- [ ] Graph shows 2-degree connections, node click navigates
- [ ] No confusing unused buttons
- [ ] Review queue accessible from UI
- [ ] Quick Facts are accurate with source links
- [ ] Full history analyzed for facts
- [ ] Clean, intuitive UI confirmed by visual review
