# LifeOS Backlog

Deferred features and enhancements to revisit after v1.

---

## High Priority (likely needed soon)

- [x] **Lightweight orchestrator agent** - ~~Small model (e.g., Haiku) decides which sources/tools to query before retrieval.~~ **DONE: Implemented as P3.5 Local LLM Query Router using Ollama + Llama 3.2 3B (2026-01-07)**
- [x] **Conversation threads** - ~~Persist conversation history, allow multiple threads, resume past conversations.~~ **DONE: Implemented as P5.1 with SQLite storage (2026-01-07)**
- [x] **Hybrid retrieval (dense + BM25)** - ~~Add keyword search alongside embeddings for better exact-match recall.~~ **DONE: Implemented as P5.2 with SQLite FTS5 + RRF fusion (2026-01-07)**
- [x] **Smart model selection** - ~~Router chooses Haiku/Sonnet/Opus based on query complexity. Simple lookups → Haiku (~$0.001), standard queries → Sonnet (~$0.01), complex reasoning → Opus (~$0.10).~~ **DONE: Implemented as P6.1 with keyword-based complexity classification (2026-01-07)**
- [x] **API cost tracking** - ~~Track token usage per query, display cost in UI, show running totals per conversation and session.~~ **DONE: Implemented as P6.2 with SQLite storage and SSE events (2026-01-07)**
- [x] **Persistent memories** - ~~Special conversation type to store things to remember. Memories surface in all future conversations. UI: "Remember this..." button or /remember command.~~ **DONE: Implemented as P6.3 with human-readable JSON storage at ~/.lifeos/memories.json, pre-populated with personal context (2026-01-07)**

---

## Medium Priority

- [ ] **Entity resolution manual review UI** - Flag ambiguous person matches (e.g., "Sarah" in vault could be sarah@murmuration.org or sarah@movementlabs.xyz) for manual confirmation. Surface in UI: "Did you mean Sarah Smith (Movement) or Sarah Jones (Murmuration)?" Store confirmed matches to improve future resolution.
- [ ] **Multi-step reasoning** - Allow Claude to fetch additional context if initial retrieval is insufficient.
- [ ] **Query expansion / HyDE** - Generate hypothetical answers to improve retrieval for vague queries.
- [ ] **Conversation history in context** - Include recent exchanges when synthesizing answers.
- [ ] **Proactive notifications** - Surface relevant info without being asked (e.g., meeting prep, relationship reminders).
- [ ] **Cross-meeting threading** - Generate views showing how a topic evolved across multiple meetings over time. "Show me the progression of budget discussions."
- [ ] **Decision logging** - Auto-extract decisions from meetings, tag with `type: decision`, enable "What did we decide about X?" queries with reasoning context.
- [ ] **Project archaeology** - For dormant/stalled projects, generate "where did we leave off?" summaries including last state, blockers, and restart requirements.

---

## Lower Priority / Future Phases

- [ ] **Slack/Telegram interface** - Alternative to web UI for quick queries.
- [ ] **Voice input** - Speech-to-text for queries.
- [ ] **Contacts integration** - Google Contacts for relationship tracking and name resolution.
- [ ] **Browser history integration** - What you've been reading/researching.
- [ ] **Scheduled briefings** - Daily/weekly summaries pushed via email or notification.
- [ ] **Spaced repetition** - Surface important concepts/facts marked as high-importance periodically for review.
- [ ] **Relationship tracking** - Track last-contact date per person, proactively prompt for contacts past threshold (family: 7 days, close friends: 14 days, work: 30 days).
- [ ] **Time audit analysis** - Analyze Google Calendar to show where time actually goes vs stated priorities.
- [ ] **Connection discovery** - Find non-obvious relationships between notes, ideas, projects, and people using graph analysis.
- [ ] **Devil's advocate mode** - Given a position, construct strongest counterarguments informed by domain knowledge and user's specific context.
- [ ] **Scenario modeling** - Think through second and third-order effects of strategic decisions given known constraints and stakeholders.

---

## Technical Debt / Improvements

- [x] **Test optimization** - ~~Fix slow test suite (30+ min unacceptable). Add pytest markers (`@slow`, `@integration`), lazy imports for ChromaDB, parallel execution with pytest-xdist. Target: <60s for unit tests, <5min for full suite.~~ **DONE: Implemented as P6.4 with pytest markers (@unit, @slow, @integration), pytest-xdist. Unit tests run in ~7s (2026-01-07)**
- [ ] **Retrieval evaluation framework** - Build test set of 50-100 queries with expected source files. Measure MRR (Mean Reciprocal Rank) and recall@k. Required to objectively measure whether retrieval changes actually improve accuracy.
- [ ] **Reranking model** - Add a cross-encoder reranker for better result ordering.
- [ ] **Caching layer** - Cache frequent queries and embeddings.
- [ ] **Metrics/observability** - Track query latency, retrieval quality, usage patterns.
- [ ] **Query logging** - Log all queries and results to identify retrieval failures and improve over time.
- [ ] **Incremental re-indexing** - More efficient updates when single files change vs full reindex.

---

*Last updated: 2026-01-07*
