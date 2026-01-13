#!/bin/bash
# Secure Start Script for Aurora Monitoring Stack
# Performs security checks before starting services

set -e

echo "🔐 Aurora Monitoring Stack - Secure Startup"
echo "==========================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop first."
    exit 1
fi

# Check for SSL certificates
if [ ! -f "config/ssl/prometheus.crt" ] || [ ! -f "config/ssl/grafana.crt" ]; then
    echo "⚠️  SSL certificates not found. Generating..."
    ./scripts/generate-ssl.sh
fi

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Creating from template..."
    cp .env.example .env
    echo "   Please edit .env and set your secrets!"
    echo "   Especially: GRAFANA_SECRET_KEY"
fi

# Security warnings
echo ""
echo "🔒 Security Checklist:"
echo "   [ ] Changed default Prometheus password?"
echo "   [ ] Changed default Grafana password?"
echo "   [ ] Set GRAFANA_SECRET_KEY in .env?"
echo "   [ ] Verified .env is in .gitignore?"
echo ""
read -p "Continue with startup? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Startup cancelled."
    exit 1
fi

# Start services
echo ""
echo "🚀 Starting secured monitoring stack..."
docker-compose -f docker-compose.prod.yml up -d redis prometheus grafana

# Wait for services to be healthy
echo ""
echo "⏳ Waiting for services to be ready..."
sleep 5

# Check service health
echo ""
echo "✅ Service Status:"
docker ps --filter "name=aurora" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "🎉 Monitoring stack started successfully!"
echo ""
echo "📊 Access URLs:"
echo "   Prometheus: http://localhost:9090 (auth: admin / EXPELLIARMUS@ISTE)"
echo "   Grafana:    https://localhost:3001 (auth: admin / EXPELLIARMUS@ISTE)"
echo ""
echo "⚠️  Remember to:"
echo "   1. Generate unique passwords for production"
echo "   2. Accept self-signed certificate warnings (dev only)" 
echo "   3. Use proper CA-signed certs for production"
echo ""
