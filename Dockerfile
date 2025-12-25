FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  curl \
  && rm -rf /var/lib/apt/lists/*

# Python dependencies (layer cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ML model during build (critical for fast startup)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Application code
COPY app/ ./app/
COPY credentials.json .

# Create required directories
RUN mkdir -p chroma_data backups logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Single worker to prevent ChromaDB race conditions (scale horizontally with replicas)
CMD ["gunicorn", "app.main:app", \
  "--workers", "1", \
  "--worker-class", "uvicorn.workers.UvicornWorker", \
  "--bind", "0.0.0.0:8000", \
  "--timeout", "120", \
  "--keep-alive", "5", \
  "--access-logfile", "-", \
  "--error-logfile", "-"]
