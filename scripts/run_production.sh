#!/bin/bash
# Production server startup script for 200+ concurrent users
# Usage: ./run_production.sh

echo "🚀 Starting Aurora Fest RAG Chatbot (Production Mode)"
echo "📊 Optimized for 200+ concurrent users"

# Set production environment
export LOG_LEVEL=WARNING  # Reduce logging overhead

# Check if Redis is available (recommended for production)
if redis-cli ping > /dev/null 2>&1; then
    echo "✓ Redis: Connected"
else
    echo "⚠ Redis: Not available (using in-memory fallback)"
    echo "  For best performance, start Redis: brew services start redis"
fi

# Start with multiple workers (4 workers = ~50 users per worker)
# Gunicorn with Uvicorn workers for production-grade ASGI
echo ""
echo "Starting server with 4 workers..."
echo "Access: http://localhost:8000"
echo "Dashboard: http://localhost:8000/dashboard"
echo ""

# Use Gunicorn with Uvicorn workers for production
if command -v gunicorn &> /dev/null; then
    gunicorn app.main:app \
        --workers 4 \
        --worker-class uvicorn.workers.UvicornWorker \
        --bind 0.0.0.0:8000 \
        --timeout 60 \
        --keep-alive 5 \
        --max-requests 1000 \
        --max-requests-jitter 100 \
        --access-logfile - \
        --error-logfile -
else
    echo "⚠ Gunicorn not installed. Using uvicorn (install with: pip install gunicorn)"
    echo "  For 200+ users, install gunicorn for better performance"
    echo ""
    # Fallback to single uvicorn with optimized settings
    uvicorn app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --workers 4 \
        --limit-concurrency 200 \
        --limit-max-requests 1000 \
        --timeout-keep-alive 5
fi
