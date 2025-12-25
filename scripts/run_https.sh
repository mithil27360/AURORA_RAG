#!/usr/bin/env bash
set -e

echo "� Aurora Fest RAG Chatbot - Production Deployment"
echo "=================================================="

# Check Docker
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop."
    exit 1
fi
echo "✓ Docker daemon running"

# Check .env file
if [ ! -f .env ]; then
    echo "❌ .env file not found. Creating template..."
    cat > .env << 'EOF'
GROQ_API_KEY=your_groq_api_key_here
GOOGLE_SHEETS_ID=your_sheets_id_here
DASHBOARD_USERNAME=admin
DASHBOARD_PASSWORD=aurora2025
LOG_LEVEL=INFO
EOF
    echo "⚠ Please edit .env with your actual credentials, then run this script again."
    exit 1
fi
echo "✓ .env file exists"

# Check credentials.json
if [ ! -f credentials.json ]; then
    echo "❌ credentials.json not found. Add your Google Sheets service account key."
    exit 1
fi
echo "✓ credentials.json exists"

# Create required directories
mkdir -p nginx/certs backups logs
echo "✓ Directories created"

# Generate SSL certificates if missing
if [ ! -f nginx/certs/aurora.crt ]; then
    echo "📜 Generating SSL certificates..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout nginx/certs/aurora.key \
        -out nginx/certs/aurora.crt \
        -subj "/C=IN/ST=Karnataka/L=Manipal/O=ISTE/CN=localhost" \
        2>/dev/null
    echo "✓ SSL certificates generated"
fi

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker compose down --remove-orphans 2>/dev/null || true

# Build and start
echo "� Building containers (this may take 2-3 minutes on first run)..."
docker compose build --no-cache

echo "🚀 Starting services..."
docker compose up -d

# Wait for health
echo "⏳ Waiting for services to be healthy..."
for i in {1..30}; do
    if curl -sf http://localhost:80/health > /dev/null 2>&1 || curl -sfk https://localhost/health > /dev/null 2>&1; then
        echo ""
        echo "=================================================="
        echo "✅ DEPLOYMENT SUCCESSFUL!"
        echo "=================================================="
        echo ""
        echo "🌐 Access URLs:"
        echo "   Chat:      https://localhost"
        echo "   Dashboard: https://localhost/dashboard"
        echo ""
        echo "📝 Credentials (from .env):"
        grep -E "^DASHBOARD_" .env | sed 's/^/   /'
        echo ""
        echo "⚠ Browser will show security warning (self-signed cert) - click 'Accept Risk'"
        echo ""
        docker compose ps
        exit 0
    fi
    echo -n "."
    sleep 2
done

echo ""
echo "⚠ Services may still be starting. Check logs with:"
echo "   docker compose logs -f aurora-chatbot"
