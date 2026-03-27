# Aurora RAG Chatbot

A production-ready Retrieval-Augmented Generation (RAG) chatbot for ISTE Aurora fest, handling real-time participant queries (schedules, venues, registrations, FAQs) with low latency and high reliability. Reduced manual organizer effort while serving 400+ users.

**400+ users** processed **3690+ total queries** (2960+ real + 730+ stress test) over 15 days at **100% uptime**, with 36.5% cache hit rate and 1.2s average response time.

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

---

## Impact

Delivered instant responses during fest, cutting organizer coordination time and boosting participant satisfaction through real-time analytics and 100% uptime under peak load.

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

---

## Key Decisions

### API Key Rotation

Round-robin across multiple Groq API keys with per-key usage tracking. Mitigated free-tier rate limits effectively.

### Google Sheets CMS

Non-technical organizers update content without code changes. Auto-sync every 5 minutes with blue-green swap for zero-downtime content refreshes.

### Scaling Strategies

| Strategy | Detail |
|:---------|:-------|
| Hard Timeouts | 10s vector search, 30s LLM, 90s total |
| Query Normalization | Improves cache hit rates |
| Rate Limiting | 60 req/min per IP with burst protection |

---

## Core Features

### RAG Pipeline

Top-k=50 retrieval from ChromaDB with cross-encoder reranking (ms-marco-MiniLM-L-6-v2) for improved relevance. Embeddings via FastEmbed (all-MiniLM-L6-v2, 384 dimensions).

### Security and Privacy

AES-256-CBC encryption for PII, SHA-256 hashing for IP addresses, raw logs deleted after 48 hours (GDPR-aligned).

### Analytics and Monitoring

Real-time dashboards for confidence scores, cache tier breakdowns, and top queries. Prometheus metrics for p95 latencies, cache hits/misses, intent distribution, and abuse violations. Grafana dashboards for both real-time (5-min window) and cumulative analytics.

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

### Dual-Database Approach

**Redis** (256MB, LRU eviction, AOF persistence)
Used for caching, sessions, and semantic lookup.

**SQLite** (WAL mode, 64MB cache)
Used for persistent logs, analytics, and backups.

---

## Deployment

### Quick Start

```bash
# 1. Setup environment
cp .env.example .env

# 2. Configure credentials in .env

# 3. Launch production stack
docker compose -f docker-compose.prod.yml up -d --build

# 4. Health check
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

## Bottlenecks and Mitigations

ChromaDB latency increases beyond 10K chunks due to linear scan overhead. Current scale is 500-1000 chunks with latency under 400ms. Addressed via multi-tier caching achieving a 36.5% hit rate.

Groq API free-tier rate limits mitigated through round-robin key rotation and cache-first request handling.

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
