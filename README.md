# Aurora RAG Chatbot

A high-concurrency Retrieval Augmented Generation (RAG) system built for the ISTE Aurora 2025 festival. Designed to run on limited hardware (2 vCPU) while supporting 100+ concurrent users with sub-second latency.

## Overview
This project is an event assistant chatbot that answers queries about schedules, workshops, and hackathons. It is engineered to handle "thundering herd" traffic spikes during festival events without crashing or timing out.

**Current Status**: Stable v4.0.1

Unlike standard RAG implementations, this system is designed for **speed** and **stability** using:
- **FastEmbed (ONNX)**: Efficient embedding generation.
- **Request Queuing**: Smart handling of traffic spikes.
- **Smart Rate Limiting**: Advanced key rotation and throttling.

## Performance
- **Latency**: ~300ms for cached/streaming responses.
- **Capacity**: Tested up to 100 concurrent users.
- **Throughput**: ~500 requests/minute on standard droplets.

## Tech Stack
- **Backend**: Python 3.11, FastAPI
- **Vector Store**: ChromaDB
- **LLM Engine**: Groq (Llama 3.1)
- **Infrastructure**: Docker, Nginx, Redis

## Observability & Monitoring

The system includes built-in monitoring tools (Prometheus + Grafana) enabled in deployed environments.

| Component | URL (Local) | Credentials | Description |
| :--- | :--- | :--- | :--- |
| **Chat UI** | `http://localhost:8000` | N/A | Main user interface |
| **Admin Dashboard** | `http://localhost:8000/dashboard` | `admin` / *(See .env)* | Internal analytics & logs |
| **Grafana** | `https://localhost:3000` | `admin` / *(See .env)* | Visual metrics & system health |
| **Prometheus** | `https://localhost:9090` | `admin` / *(See .env)* | Time-series data collection |

> **Note**: Grafana and Prometheus run over HTTPS with self-signed certificates. You may need to bypass the browser warning in local development.

---

## Setup & Deployment

### Option A: Local Development (Manual)
Best for coding and testing changes quickly.

1.  **Clone & Prepare**
    ```bash
    git clone https://github.com/iste-manipal/aurora-rag.git
    cd aurora-rag
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

2.  **Configuration**
    ```bash
    cp .env.example .env
    # Add your keys: GROQ_API_KEY, GOOGLE_SHEETS_ID, GOOGLE_CREDENTIALS_FILE
    ```

3.  **Run Services**
    You need a local Redis instance for caching.
    ```bash
    docker run -d -p 6379:6379 redis:alpine
    uvicorn app.main:app --reload --port 8000
    ```

### Option B: Local Production (Docker)
Replicates the exact production environment with all monitoring tools.

```bash
# 1. Setup Environment
cp .env.example .env
# Ensure your .env is populated

# 2. Launch Stack
docker compose -f docker-compose.prod.yml up -d --build
```

Access the application at `http://localhost:8000`.
