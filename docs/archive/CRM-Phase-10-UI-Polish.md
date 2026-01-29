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

## Task 9: People List Filtering and Sorting
**Priority: Critical**

### Problem
The people list shows everyone, including those with zero interactions. List is not sorted meaningfully.

### Requirements
1. **Filter by default**: Only show people with 1+ interactions
2. **Sort by strength**: Order by relationship strength (descending)
3. **Show all toggle**: Optional checkbox to include zero-interaction people
4. **Performance**: List should load quickly with filtering applied

### API Changes
- Add `min_interactions=1` default parameter to `/api/crm/people`
- Add `sort_by=strength` parameter
- Return only filtered results by default

### Verification
- Load CRM, see only people with interactions
- Top of list = highest strength connections
- Toggle to see all (including zero-interaction)

---

## Task 10: Pre-Extract Facts for Top 50
**Priority: High**

### Problem
Quick Facts are empty until manually extracted. Users shouldn't have to click "Extract" for everyone.

### Requirements
1. Identify top 50 people by relationship strength
2. Run fact extraction for each (in background)
3. Store results so they're immediately available when viewing person
4. Skip people who already have facts extracted

### Implementation
- Create `scripts/batch_extract_facts.py`
- Query top 50 people by strength with 1+ interactions
- For each, call the fact extraction service
- Log progress and any errors
- Can be run manually or via cron

### Verification
- Run script
- Open CRM, view top people
- Quick Facts are already populated (no "Extract" needed)

---

## Task 11: Remove Connections Tab
**Priority: High**

### Problem
Connections tab is confusing and redundant with Graph view. User doesn't understand its purpose.

### Decision
**Remove the Connections tab entirely.**

### Rationale
- Graph view already shows connections visually
- Having both creates confusion
- Simpler UI = better UX

### Implementation
1. Remove "Connections" tab from tab bar
2. Remove connections tab content/rendering code
3. Keep Graph as the sole network visualization
4. Update any references in documentation

### Verification
- Only 3 tabs remain: Overview, Timeline, Graph
- Graph works correctly for network visualization

---

## Task 12: Fix Graph Tab - Second-Degree Connections
**Priority: Critical**

### Problem
Graph tab was working before but is now broken. Does not show proper 2-degree network.

### Required Behavior
1. **Center node**: Selected person is ALWAYS the center of the graph
2. **Two-degree network**: Show all people within 2 degrees of connection
   - Degree 0: Central person (selected)
   - Degree 1: Direct connections to central person
   - Degree 2: Connections of those direct connections
3. **Click behavior**: Clicking ANY node:
   - Switches to that person's detail page
   - That person becomes the NEW center
   - Graph re-renders with THEIR 2-degree network
   - Stays on Graph tab
4. **Visual hierarchy**:
   - Degree 0: Largest node, accent color
   - Degree 1: Medium nodes
   - Degree 2: Smaller nodes, reduced opacity

### API Requirements
- `/api/crm/network?center_on={person_id}&depth=2`
- Returns nodes with `degree` field (0, 1, or 2)
- Returns edges connecting the network

### Debugging Steps
1. Check if API returns correct data with depth=2
2. Check if D3.js force simulation is running
3. Check if SVG is being rendered in container
4. Check for JavaScript errors in console

### Verification
- Select any person → they're centered in graph
- See their direct connections (degree 1)
- See connections-of-connections (degree 2)
- Click another node → graph re-centers on them

---

## Task 13: Performance Optimization
**Priority: Critical**

### Problem
Loading a person's page takes many seconds. Unacceptable UX.

### Root Causes to Investigate
1. **API calls**: How many calls on person load? Can they be parallelized/batched?
2. **Timeline query**: Loading full timeline on initial load?
3. **Network query**: Complex graph queries blocking UI?
4. **Facts extraction**: Running synchronously on load?
5. **Frontend**: Re-rendering unnecessarily?

### Performance Targets
- Person page initial load: < 500ms
- Tab switch: < 200ms
- Graph render: < 1s for networks up to 200 nodes

### Optimization Strategies
1. **Lazy loading**: Only load visible tab's data
2. **Pagination**: Don't load full timeline upfront
3. **Caching**: Cache person data, timeline, network
4. **Background loading**: Load secondary data after initial render
5. **API batching**: Single call for person + stats + recent activity
6. **Indexes**: Ensure database indexes on frequently queried columns

### Implementation
1. Profile current load to identify bottleneck
2. Add timing logs to API endpoints
3. Implement lazy tab loading
4. Add response caching
5. Optimize slow queries

### Verification
- Open Network tab in browser DevTools
- Click person → all data loads in < 500ms
- Switch tabs → instant response

---

## Implementation Order (Updated)

### Round 1 (Critical - Do Now)
1. **Task 9**: Filter people list (blocking usability)
2. **Task 12**: Fix Graph tab (broken feature)
3. **Task 13**: Performance optimization (UX blocker)

### Round 2 (High Priority)
4. **Task 11**: Remove Connections tab (cleanup)
5. **Task 10**: Pre-extract facts for top 50

### Already Completed
- ~~Task 1~~: Timeline aggregation ✅
- ~~Task 5~~: Review queue UI ✅
- ~~Task 6~~: Quick Facts overhaul ✅
- ~~Task 7~~: History grid ✅

---

## Success Criteria

- [x] Timeline shows grouped interactions that expand
- [ ] Graph shows 2-degree connections, node click navigates
- [x] No confusing unused buttons
- [x] Review queue accessible from UI
- [x] Quick Facts are accurate with source links
- [x] Full history analyzed for facts
- [ ] People list filtered to those with interactions
- [ ] People list sorted by strength
- [ ] Top 50 have pre-extracted facts
- [ ] Connections tab removed
- [ ] Page load < 500ms
- [ ] Graph tab works correctly with 2-degree network
