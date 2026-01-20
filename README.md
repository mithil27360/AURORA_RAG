# Aurora RAG Chatbot


## Overview
This project is an event assistant chatbot that answers queries about schedules, workshops, and hackathons. It is engineered to handle traffic spikes during festival events without crashing or timing out.

**Current Status**: Stable v4.0.1



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




```bash
# 1. Setup Environment
cp .env.example .env
# Ensure your .env is populated

# 2. Launch Stack
docker compose -f docker-compose.prod.yml up -d --build
```

Access the application at `http://localhost:8000`.
