# Aurora RAG Chatbot

A production-grade Retrieval-Augmented Generation (RAG) system designed to handle real-time, high-concurrency event queries with low latency and strong reliability guarantees.

Served 400+ users and processed 3690+ queries over 15 days with 100% uptime, 1.2s average latency, and a 36.5% cache hit rate. Dual-layer caching reduced query latency from 4.2s to 18ms (99.6% improvement).

**Impact:** Reduced manual coordination effort for event organizers by automating FAQ handling and enabling real-time participant support at scale.

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

### System Efficiency Insights

Reduced LLM calls by 36.5% via multi-tier caching. Dual-layer caching cut query latency from 4.2s to 18ms (99.6% improvement) at a 31% hit rate. Maintained sub-2s latency under peak load of 413 queries/day. Achieved consistent performance with only 2 Gunicorn workers through async-first design.

---

## Tech Stack

| Layer | Technology |
|:------|:-----------|
| Backend | Python 3.11, FastAPI (async-first) |
| Vector DB | ChromaDB (persistent, SQLite-based) |
| LLM | Groq-hosted LLaMA 3 70B |
| Cache | In-Memory LRU (L1) + Redis (L2) + Semantic Cache |
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
    → Intent Classification (8 categories)
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

## Scalability Approach

Async FastAPI pipeline maximizes throughput under limited worker count. Multi-layer caching (L1 memory + L2 Redis + semantic cache) reduces compute-heavy retrieval. API key rotation bypasses LLM provider rate limits without downtime. Query normalization increases cache reuse across semantically similar inputs.

| Strategy | Detail |
|:---------|:-------|
| Hard Timeouts | 10s vector search, 30s LLM, 90s total |
| Rate Limiting | 60 req/min per IP with burst protection |
| Query Normalization | Improves cache hit rates across similar inputs |
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
Used for caching, sessions, and semantic lookup.

**SQLite** (WAL mode, 64MB cache)
Used for persistent logs, analytics, and backups.

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

**Current Bottleneck:** ChromaDB latency increases beyond 10K chunks due to linear scan overhead. Current scale is 500-1000 chunks with latency under 400ms, mitigated by a 36.5% cache hit rate.

**Planned Improvements:**

Replace ChromaDB with FAISS or a hybrid ANN index for scale beyond 10K chunks. Introduce query batching and streaming responses for further latency reduction. Migrate from SQLite to Postgres for horizontal scalability at higher user volumes.

---

## Key Learnings

Multi-tier caching is the single biggest lever for scaling LLM systems. Latency bottlenecks shift from retrieval to generation as scale increases. Simple architectures (SQLite + Redis) can outperform complex stacks at small scale when workload characteristics are understood upfront.

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



## License

MIT
