# FAANG-Style Code Review
> **Candidate**: Aurora RAG Chatbot
> **Reviewer**: Staff Software Engineer (L6)
> **Verdict**: **HIRE** (Strong Junior/Mid-level) / **NO HIRE** (Senior/Staff)

## 1. The "Monolith" Anti-Pattern (Architecture)
**Mistake**: `aurora_v2.py` is a 2,400-line "God File".
-   **Why it fails**: You mix **Data Access** (SQLite/Chroma), **Business Logic** (Intent, RAG), **Presentation** (FastAPI HTML routes), and **Configuration** in one file.
-   **Impact**: Impossible to test components in isolation. Two developers cannot work on this without merge conflicts.
-   **Fix**: Split into `app/api/`, `app/core/`, `app/db/`, `app/services/`.

## 2. Global State & Concurrency (Scalability)
**Mistake**: Extensive use of Global Variables (`analytics_log`, `conversation_history`, `response_cache`, `llm`, `searcher`).
-   **Why it fails**:
    -   **Testing**: Tests are not isolated; one test dirtying `conversation_history` breaks the next.
    -   **Race Conditions**: Python dictionaries are thread-safe *for single operations*, but RMW (Read-Modify-Write) patterns on globals are not safe under concurrency without strict locking (which you rely on GIL for, which is risky).
    -   **Scale**: You cannot run this on multiple workers (`gunicorn -w 4`) because memory is not shared. Each worker has its own empty cache/history.
-   **Fix**: Use **Dependency Injection** (`Depends(get_db)`). Move state to external stores (Redis for cache/session) or database.

## 3. Blocking I/O in Async Routes (Performance)
**Mistake**: You declare `async def chat(...)` but make **Synchronous Blocking Calls** inside it.
-   `sqlite3` (`conn.execute`) is blocking.
-   `chromadb` (local client) is blocking.
-   **Why it fails**: One user doing a heavy search freezes the *entire event loop*. Other users' heartbeats/ping requests will hang.
-   **Fix**: Use `run_in_executor` for blocking calls or use true async drivers (`aiosqlite`, `asyncpg`).

## 4. Input Validation & Security
**Mistake**: Content Moderation via Regex (`blocked_patterns`).
-   **Why it fails**: "Don't roll your own crypto/security". Regexes are easily bypassed (`f u c k`, `sh1t`).
-   **Fix**: Use a dedicated abuse classification model (e.g., Llama-Guard) or an external moderation API. Your regex list is "cute" but not enterprise-grade.

## 5. Memory Management
**Mistake**: `conversation_history` / `response_cache` are in-memory dicts.
-   **Why it fails**: Server restart = Data loss.
-   **Fix**: Persist this data (Redis/Postgres). The "Memory Cap" (10k items) prevents OOM but introduces unpredictable data loss.

## 6. Testing Strategy
**Mistake**: Tests (`test_core_logic.py`) rely on **Mocking Everything**.
-   **Why it fails**: You tested your *logic*, but not your *integration*. If ChromaDB API changes, your tests pass but prod crashes.
-   **Fix**: Add **Integration Tests** that spin up a real (ephemeral) ChromaDB/SQLite.

## Summary for Candidate
You built a **working product** (which puts you ahead of 90% of candidates). It has observability, resilience, and safety.
However, for a **Senior** role, we expect you to:
1.  Decouple state from the application instance (Redis).
2.  Handle blocking I/O correctly in async contexts.
3.  Structure code for team scalability (Modules vs Monolith).
