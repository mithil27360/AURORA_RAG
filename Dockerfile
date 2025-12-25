FROM python:3.11-slim

# Hugging Face Spaces runs as non-root user
RUN useradd -m -u 1000 user
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  curl \
  && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ML model (critical for fast startup)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Application code
COPY --chown=user app/ ./app/

# Create required directories with proper permissions
RUN mkdir -p chroma_data backups logs && chown -R user:user /app

# Switch to non-root user (required by HF Spaces)
USER user

# Hugging Face uses port 7860
ENV PORT=7860
EXPOSE 7860

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:7860/health || exit 1

# Start server
CMD uvicorn app.main:app --host 0.0.0.0 --port 7860 --workers 1
