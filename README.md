# Aurora RAG Chatbot

Event assistant chatbot serving **115 users** with **852 real queries** over 15 days at **100% uptime**. Engineered for high-traffic festival environments with multi-tier caching, intelligent query routing, and comprehensive security.

---

## Key Metrics

| Metric | Value |
|:-------|:------|
| Real User Queries | 852 |
| Stress Test Queries | 520 |
| Latency (Cached) | ~18 ms |
| Latency (Uncached) | ~4.2 s |
| Latency Reduction | ~99.5% |
| Cache Hit Rate | ~36.5% |
| Peak Load | 413 queries/day |
| Uptime | 100% |


---

## Tech Stack

- **Backend**: Python 3.11, FastAPI (async-first)
- **Vector DB**: ChromaDB (SQLite-based, persistent)
- **LLM**: Groq Llama 3.3 70B
- **Cache**: In-Memory LRU (L1) + Redis (L2) + Semantic
- **Database**: SQLite (WAL mode)
- **Infrastructure**: Docker Compose, Nginx, Gunicorn (2 workers)
- **Monitoring**: Prometheus, Grafana
- **CMS**: Google Sheets (auto-sync every 5 min)

---

## Architecture

### Request Flow

```
Security Gate (IP hashing, abuse check, content moderation)
  → Intent Classification (8 categories)
  → Multi-Tier Cache Lookup (L1 → L2 → Semantic)
  → Vector Retrieval (ChromaDB, top-k=50)
  → Cross-Encoder Reranking (optional)
  → LLM Generation (Groq Llama 3.3 70B)
  → Background Tasks (analytics, geolocation, logging)
```

### Key Engineering Decisions

**API Key Rotation**
- Round-robin across multiple Groq API keys (comma-separated in env)
- Per-key usage tracking; mitigates free-tier rate limits

**Google Sheets as CMS**
- Non-technical organizers update event content without code changes
- Auto-sync every 5 minutes with blue-green swap on update

**Encryption Key Management**
- HKDF derivation for purpose-specific keys (encryption, signing, hashing)
- Key versioning supports rotation without data loss

### Scaling Strategies

- Async I/O with `asyncio.to_thread()` for blocking operations
- Hard timeouts: 10s vector search, 30s LLM, 90s total
- Background task offload for analytics and logging
- Query normalization to improve cache hit rates
- Rate limiting: 60 req/min per IP with burst protection

### Data Chunking Strategy

- Master event list (single chunk for broad queries)
- Events by type: workshops, hackathons, competitions, talks
- Per-event details: name, date, venue, description, topics
- Per-day schedule: time, duration, prerequisites
- FAQ pairs for direct question-answer matching
- Chunk size: 200–400 tokens for retrieval precision

---

## Core Features

**RAG Pipeline**
- Vector search with ChromaDB + FastEmbed (all-MiniLM-L6-v2, 384 dimensions)
- Top-k=50 retrieval with optional cross-encoder reranking
- Query expansion with synonym and technical term handling
- Fuzzy matching for event names, abbreviations, and typos

**Conversation Management**
- Multi-turn context via UUID sessions (last 10 turns, 1-hour TTL)
- Entity extraction: events, dates, times, venues
- Context-aware query rewriting for follow-up questions

**Security & Privacy**
- AES-256-CBC encryption for PII, SHA-256 IP hashing
- Raw IPs deleted after 48 hours (GDPR-compliant)
- Right-to-deletion endpoints, HKDF key derivation

**Analytics**
- Real-time dashboard: confidence scores, cache tier breakdown, top queries
- Prometheus metrics: request durations, cache hits/misses, intent distribution, abuse violations
- Grafana dashboards: Realtime (5-min window) + Cumulative (all-time)
- Geolocation enrichment, device/OS/browser telemetry

---

## Performance Reference

| Component | Latency |
|:----------|:--------|
| L1 Cache (In-Memory) | <1ms |
| L2 Cache (Redis) | 5–10ms |
| Semantic Cache | 20–50ms |
| Vector Search (ChromaDB) | 50–150ms |
| LLM Generation (Groq) | 1–3s |

---

## Database Architecture

**Dual-Database Approach**
- **Redis** (256MB, LRU eviction, AOF persistence): Cache, sessions, semantic search
- **SQLite** (WAL mode, 64MB cache): Persistent logging, analytics, backups


---

## Deployment

### Container Stack

| Service | Config |
|:--------|:-------|
| aurora-chatbot | 2 workers, 2GB RAM limit |
| redis | 256MB, AOF persistence |
| prometheus | 30-day retention, HTTPS |
| grafana | 2 dashboards, auto-provisioned |
| nginx | Optional reverse proxy |

### Quick Start

```bash
# 1. Setup environment
cp .env.example .env
# Fill in credentials (see Configuration below)

# 2. Launch stack
docker compose -f docker-compose.prod.yml up -d --build

# 3. Verify
curl -f http://localhost:8000/health
```

### Access Points

| Service | URL |
|:--------|:----|
| Chat UI | `http://localhost:8000` |
| Admin Dashboard | `http://localhost:8000/dashboard` |
| Grafana | `https://localhost:3000` |
| Prometheus | `https://localhost:9090` |

> Grafana and Prometheus use HTTPS with self-signed certificates. Bypass the browser warning in local development.

### Updates & Rollbacks

```bash
# Backup before update
curl -X POST http://localhost:8000/backup-logs

# Update
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build

# Rollback
git checkout <previous-tag>
docker compose -f docker-compose.prod.yml up -d --build
```

---

## Bottlenecks & Limitations

**Identified Bottlenecks**
- Groq API rate limits on free tier — mitigated by ~36.5% cache hit rate and key rotation
- ChromaDB query time degrades beyond ~10K document chunks (currently <400ms at 500–1000 chunks)
- SQLite writes are serialized — background async logging prevents user-facing impact
- In-memory semantic cache is not shared across workers — Redis required for horizontal scaling

**Known Limitations**
- Single-tenant (event-scoped, no multi-tenancy)
- Rule-based intent classification (keyword matching, not ML)
- No streaming responses in turbo mode
- Abuse detection state is in-memory (not shared across instances)
- Cross-encoder reranking disabled in turbo mode (+50–100ms trade-off)



---

## Configuration

```env
# Application
ENVIRONMENT=production
DEBUG=false

# LLM (comma-separated keys for rotation)
GROQ_API_KEY=gsk_key1,gsk_key2,gsk_key3
LLM_MODEL=llama-3.3-70b-versatile
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=1000

# Data Source
GOOGLE_SHEETS_ID=your_sheet_id
GOOGLE_CREDS_JSON={"type":"service_account",...}

# Cache & Database
REDIS_URL=redis://redis:6379/0

# Security
SECRET_KEY=<32+ character secret>
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=<strong password>

# Monitoring
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<strong password>
PROMETHEUS_ADMIN_PASSWORD=<strong password>

# Feature Flags
ENABLE_METRICS=true
ENABLE_RATE_LIMITING=true
ENABLE_SEMANTIC_CACHE=true
ENABLE_ABUSE_DETECTION=true
FEATURE_CONVERSATION_CONTEXT=true
FEATURE_ANALYTICS=true
```

---

## License

MIT
