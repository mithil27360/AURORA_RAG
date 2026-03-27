# Aurora RAG Chatbot

A production-grade Retrieval-Augmented Generation (RAG) system designed to handle real-time, high-concurrency event queries with low latency and strong reliability guarantees.

Served 400+ users and processed 3690+ queries over 15 days with 100% uptime, 1.2s average latency, and a 36.5% cache hit rate — reducing query latency from 4.2s to 18ms (99.6% improvement) via multi-tier caching. Designed to support dynamic content updates from 80+ event coordinators (MCs) through a Google Sheets-based CMS. Designed and implemented the system end-to-end, including architecture, retrieval pipeline, caching, deployment, and monitoring.

**Impact:** Reduced manual coordination effort for event organizers by automating FAQ handling and enabling real-time participant support at scale.

**Role:** Technical Lead (Point of Contact) — led a team of 6 developers. Proposed and implemented the core system architecture (RAG pipeline, caching, deployment). Team contributions included data preparation (Google Sheets), embedding model experimentation, backup chatbot prototyping (Zapier/n8n), and testing/feedback to improve system accuracy and robustness.

---

## Key Metrics

| Metric | Value |
|:-------|:------|
| Real User Queries | 2960+ |
| Stress Test Queries | 730+ |
| Total Queries | 3690+ |
| Active Users | 400+ |
| Uptime | 100% |
| Avg Queries per User | 9.2 |
| Cache Hit Rate | 36.5% |
| Avg Response Time | 1.2s |
| Peak Load | 413 queries/day |
| Cache Latency Improvement | 4.2s → 18ms (99.6% reduction) |
| p95 Latency | <2.5s |

### System Efficiency Insights

Reduced LLM calls by 36.5% via multi-tier caching, achieving significant latency reduction (4.2s → 18ms, 99.6% improvement). Maintained sub-2s latency under peak load of 413 queries/day. Designed an async-first FastAPI pipeline enabling high concurrency with only 2 workers, maintaining stable latency under peak load.

---

## Tech Stack

| Layer | Technology |
|:------|:-----------|
| Backend | Python 3.11, FastAPI (async-first) |
| Vector DB | ChromaDB (persistent, SQLite-based) |
| LLM | Groq-hosted LLaMA 3 70B |
| Cache | In-Memory LRU (L1) + Redis (L2) + Semantic Cache (embedding-based similarity lookup to reuse responses for semantically similar queries) |
| Database | SQLite (WAL mode) |
| Infrastructure | Docker Compose, Nginx, Gunicorn (2 workers) |
| Monitoring | Prometheus, Grafana |
| CMS | Google Sheets (auto-sync every 5 min) |
| Embeddings | FastEmbed (all-MiniLM-L6-v2, 384-dim) |

---

## Architecture

### Request Flow

```
Security Gate (IP hashing, abuse detection, content moderation)
    → Intent Classification (8 categories, lightweight keyword classifier)
    → Multi-Tier Cache Lookup (L1 → L2 → Semantic)
    → Vector Retrieval (ChromaDB, top-k=50)
    → Cross-Encoder Reranking (ms-marco-MiniLM-L-6-v2)
    → LLM Generation (Groq LLaMA 3 70B)
    → Background Tasks (analytics, logging, geolocation)
```

### Design Tradeoffs

| Decision | Reasoning |
|:---------|:----------|
| ChromaDB over FAISS | Persistence and operational simplicity at current scale (500-1000 chunks) |
| Cross-encoder reranking despite ~50-100ms overhead | Improved answer precision justified the latency cost |
| Multi-tier caching (L1 + L2 + Semantic) | Offsets linear scan cost in vector search and reduces LLM calls |
| SQLite (WAL) over Postgres | Lower operational complexity for a read-heavy, single-node workload |

---

## System Constraints

Free-tier LLM API rate limits required aggressive caching and key rotation to maintain availability. Single-node deployment (Docker Compose) constrained horizontal scaling, pushing optimization toward async design and cache efficiency. Read-heavy workload with burst traffic patterns during live events demanded low-latency cache layers over raw compute. Cold-start latency of LLM responses required aggressive caching to maintain consistent UX. System was designed to handle dynamic updates from 80+ coordinators, requiring robustness to inconsistent, delayed, and concurrent data changes.

---

## Scalability Approach

Designed an async-first FastAPI pipeline enabling high concurrency with only 2 Gunicorn workers, maintaining stable latency under peak load. Multi-layer caching (L1 memory + L2 Redis + semantic cache) reduces compute-heavy retrieval. API key rotation bypasses LLM provider rate limits without downtime. Query normalization increases cache reuse across semantically similar queries.

| Strategy | Detail |
|:---------|:-------|
| Hard Timeouts | 10s vector search, 30s LLM, 90s total |
| Rate Limiting | 60 req/min per IP with burst protection |
| Query Normalization | Increases cache reuse across semantically similar queries |
| Key Rotation | Round-robin across Groq API keys with per-key tracking |

---

## Failure Handling

Fallback to cached responses on LLM timeout. Graceful degradation when vector search exceeds latency thresholds. Abuse detection and rate limiting prevent system overload. Background task isolation ensures the core request pipeline stays unaffected by logging or analytics failures.

---

## Core Features

### RAG Pipeline

Top-k=50 retrieval from ChromaDB with cross-encoder reranking (ms-marco-MiniLM-L-6-v2) for improved relevance. Embeddings via FastEmbed (all-MiniLM-L6-v2, 384 dimensions).

### Security and Privacy

AES-256-CBC encryption for PII, SHA-256 hashing for IP addresses, raw logs deleted after 48 hours (GDPR-aligned).

### Analytics and Monitoring

Real-time dashboards for confidence scores, cache tier breakdowns, and top queries. Prometheus metrics for p95 latencies, cache hits/misses, intent distribution, and abuse violations. Grafana dashboards for both real-time (5-min window) and cumulative analytics.

### Google Sheets CMS

Non-technical organizers update content without code changes. Auto-sync every 5 minutes with blue-green swap for zero-downtime content refreshes.

---

## Performance Reference

| Component | Latency |
|:----------|:--------|
| L1 Cache (In-Memory) | <1 ms |
| L2 Cache (Redis) | 5-10 ms |
| Semantic Cache | 20-50 ms |
| Vector Search (ChromaDB) | 50-150 ms |
| LLM Generation (Groq) | 1-3 s |

---

## Database Architecture

**Redis** (256MB, LRU eviction, AOF persistence)
Handles caching, sessions, and semantic lookup.

**SQLite** (WAL mode, 64MB cache)
Stores persistent logs, analytics, and backups.

---

## Deployment

### Quick Start

```bash
# Setup environment
cp .env.example .env

# Launch production stack
docker compose -f docker-compose.prod.yml up -d --build

# Health check
curl -f http://localhost:8000/health
```

### Access Points

| Service | URL |
|:--------|:----|
| Chat UI | http://localhost:8000 |
| Admin Dashboard | http://localhost:8000/dashboard |
| Grafana | https://localhost:3000 |
| Prometheus | https://localhost:9090 |

> Grafana and Prometheus use HTTPS with self-signed certificates. Bypass the browser warning in local development.

### Updates and Rollbacks

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

## Bottlenecks and Future Improvements

**Primary Bottleneck:** ChromaDB's linear scan retrieval introduces latency growth beyond ~10K chunks, making it unsuitable for large-scale deployments without ANN indexing. This creates a scaling ceiling, making approximate nearest neighbor (ANN) indexing necessary for production-scale datasets. Current scale is 500-1000 chunks with latency under 400ms, mitigated by a 36.5% cache hit rate.

**Planned Improvements:**

Replace ChromaDB with FAISS or a hybrid ANN index for scale beyond 10K chunks. Introduce query batching and streaming responses for further latency reduction. Migrate from SQLite to Postgres for horizontal scalability at higher user volumes.

---

## Key Learnings

Caching, not model optimization, is the dominant factor in real-world LLM system performance. Retrieval quality (reranking) often matters more than increasing model size. Over-engineering infrastructure early is less effective than optimizing for actual workload characteristics. Real-world performance improvements were driven more by system-level optimizations (caching, retrieval) than model-level changes.

---

## Configuration

```env
# LLM (comma-separated keys for rotation)
GROQ_API_KEY=gsk_key1,gsk_key2,gsk_key3
LLM_MODEL=llama-3.3-70b-versatile
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=1000

# Data Source
GOOGLE_SHEETS_ID=your_sheet_id
GOOGLE_CREDS_JSON={"type":"service_account",...}

# Cache and Database
REDIS_URL=redis://redis:6379/0

# Security
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=<strong password>

# Monitoring
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<strong password>
PROMETHEUS_ADMIN_PASSWORD=<strong password>
```

---

## Team Contributions

| Area | Owner |
|:-----|:------|
| System Architecture | Mithil (Technical Lead) |
| RAG Pipeline | Mithil |
| Caching System | Mithil |
| Deployment and Monitoring | Mithil |
| Data Preparation (Google Sheets) | Team |
| Embedding Model Experimentation | Team |
| Backup Chatbot Prototyping (Zapier/n8n) | Team |
| Testing and Feedback | Team |

---



## License

MIT
