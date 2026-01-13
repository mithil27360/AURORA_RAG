#!/bin/bash
# =============================================================================
# Aurora RAG Chatbot - Monitoring Stack Startup
# =============================================================================
# Run this script to start Redis, Prometheus, and Grafana
# Requires Docker to be running
# =============================================================================

set -e

echo "🚀 Starting Aurora Monitoring Stack..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    echo ""
    echo "On macOS: Open Docker Desktop app"
    echo "On Linux: sudo systemctl start docker"
    exit 1
fi

# Create directories
mkdir -p data logs

# Start the monitoring stack
echo "📦 Starting Redis, Prometheus, and Grafana..."
docker-compose -f docker-compose.prod.yml up -d redis prometheus grafana

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 5

# Check status
echo ""
echo "📊 Service Status:"
docker-compose -f docker-compose.prod.yml ps

echo ""
echo "✅ Monitoring Stack Started!"
echo ""
echo "🔗 Access URLs:"
echo "   - Prometheus: http://localhost:9090"
echo "   - Grafana:    http://localhost:3000 (admin / aurora2025)"
echo "   - Redis:      localhost:6379"
echo ""
echo "💡 To start the chatbot with Redis:"
echo "   REDIS_URL=redis://localhost:6379/0 ./scripts/start.sh"
echo ""
echo "📈 To view metrics: http://localhost:8000/metrics"
