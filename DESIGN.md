# System Design Document

> **Project**: Aurora Fest RAG Chatbot
> **Version**: 2.0.0
> **Status**: Production Ready

## 1. System Overview
The Aurora Fest RAG Chatbot is a specialized retrieval-augmented generation system designed to answer student queries about college fest events with high accuracy and zero hallucinations. It prioritizes availability and correctness over broad conversational ability.

### Core Components
- **Frontend**: Lightweight HTML/JS UI (embedded or independent).
- **Backend API**: FastAPI (Python 3.11) handling request routing, rate limiting, and orchestration.
- **Vector Store**: ChromaDB (local persistent) for semantic search.
- **LLM Provider**: Groq (Llama-3-70b) for high-speed valid answer generation.
- **Data Source**: Google Sheets (Admin Panel) -> Auto-synced to Vector Store.

## 2. Data Flow Architecture

### Ingestion Pipeline (Background)
1.  **Fetch**: Pulls raw event data from Google Sheets (every 5 mins).
2.  **Normalize**: Flattens nested sheet structures into standardized "Event" objects.
3.  **Chunk**: Splits events into optimized text chunks (Schedule, Prerequisites, General).
4.  **Vectorize**: Generates embeddings (all-MiniLM-L6-v2).
5.  **Update**: "Blue/Green" deployment loads new chunks into a fresh collection, then atomic swap.

### Retrieval Pipeline (Real-time)
1.  **User Query**: `POST /chat`
2.  **Intent Classification**: Regex-based analysis (Zero-latency classification: "Schedule", "Contact", etc.).
3.  **Hybrid Search**:
    -   *Filter*: Apply intent-based filters (e.g., `type="schedule_time"`).
    -   *Search*: Vector similarity search + Keyword boosting for event names.
4.  **Generation**:
    -   `STRICT_MODE`: LLM (Temp=0.0) answers ONLY from retrieved context.
    -   *Fallback*: If confidence < threshold, return "I don't have that info".

## 3. Failure Handling & Resilience

| Failure Mode | Mitigation Strategy |
| :--- | :--- |
| **API Limit (Groq)** | Auto-rotation of API keys (Round-robin failover). |
| **LLM Downtime** | Fallback to "System Maintenance" friendly message. |
| **Bad Data Update** | `VectorSearch` aborts swap if new data < 80% of old data. |
| **Server Crash** | Stateless design allows instant restart (managed by Docker/PM2). |
| **Memory Leak** | `conversation_history` capped at 10k users (auto-clear). |

## 4. Key Design Trade-offs

### Regex vs LLM Intent Classification
-   **Decision**: We use **Regex** for the first pass.
-   **Why**:
    -   *Determinism*: We verify that "When is..." ALWAYS hits the schedule filter.
    -   *Latency*: <1ms vs 500ms+ for an LLM call.
    -   *Cost*: Zero cost per classification.

### Confidence Scores
-   **Decision**: Confidence is a **Ranking Signal**, not a probability.
-   **Why**: Calibrated probabilities are hard in RAG. We use `score = similarity + metadata_boost` to rank "best effort" results, which is sufficient for simple retrieval.
