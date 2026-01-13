#!/bin/bash
# =============================================================================
# Aurora RAG - DigitalOcean Deployment Script
# =============================================================================
# Usage: ./deploy_do.sh <droplet_ip> [domain]
# Example: ./deploy_do.sh 159.89.161.81 aurora.example.com
# =============================================================================

set -e

# Configuration
DROPLET_IP="${1:?Usage: ./deploy_do.sh <droplet_ip> [domain]}"
DOMAIN="${2:-$DROPLET_IP}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
APP_DIR="/opt/aurora"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; exit 1; }

# Check SSH key
if [ ! -f "$SSH_KEY" ]; then
    if [ -f "$HOME/.ssh/id_rsa" ]; then
        SSH_KEY="$HOME/.ssh/id_rsa"
    else
        error "No SSH key found. Set SSH_KEY env var."
    fi
fi

SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no root@$DROPLET_IP"
SCP_CMD="scp -i $SSH_KEY -o StrictHostKeyChecking=no"

log "Deploying to $DROPLET_IP (domain: $DOMAIN)"

# =============================================================================
# Step 1: Server Setup
# =============================================================================
log "Step 1: Setting up server..."

$SSH_CMD << 'SETUP'
set -e

# Update system
apt update && apt upgrade -y

# Add swap if not exists
if [ ! -f /swapfile ]; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    echo "Swap created"
fi

# Install Docker
if ! command -v docker &> /dev/null; then
    apt install -y docker.io docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    
    # Log rotation
    cat > /etc/docker/daemon.json << EOF
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "3"
  }
}
EOF
    systemctl restart docker
    echo "Docker installed"
fi

# Install Nginx
if ! command -v nginx &> /dev/null; then
    apt install -y nginx
    systemctl enable nginx
    echo "Nginx installed"
fi

# Firewall
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Create app directory and set permissions
mkdir -p /opt/aurora/data/chroma
mkdir -p /opt/aurora/data/logs
mkdir -p /opt/aurora/data/backups
chmod -R 777 /opt/aurora/data

echo "Server setup complete"
SETUP

# =============================================================================
# Step 2: Run Redis
# =============================================================================
log "Step 2: Starting Redis..."

$SSH_CMD << 'REDIS'
if ! docker ps | grep -q redis; then
    docker rm -f redis 2>/dev/null || true
    docker run -d \
        --name redis \
        --restart unless-stopped \
        -p 127.0.0.1:6379:6379 \
        redis:7
    echo "Redis started"
else
    echo "Redis already running"
fi
REDIS

# =============================================================================
# Step 3: Sync Project Files
# =============================================================================
log "Step 3: Syncing project files..."

rsync -avz --progress \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude 'data/chroma_data' \
    --exclude '*.pyc' \
    --exclude '.env' \
    ./ root@$DROPLET_IP:$APP_DIR/

# =============================================================================
# Step 4: Setup Environment
# =============================================================================
log "Step 4: Setting up environment..."

if [ -f .env ]; then
    $SCP_CMD .env root@$DROPLET_IP:$APP_DIR/.env
    log "Copied .env file"
else
    warn ".env not found locally. Create one on server at $APP_DIR/.env"
fi

# =============================================================================
# Step 5: Build & Run Application
# =============================================================================
log "Step 5: Building and running application..."

$SSH_CMD << 'BUILD'
cd /opt/aurora

# Build image
docker build -t aurora:latest .

# Stop existing container
docker stop aurora-app 2>/dev/null || true
docker rm aurora-app 2>/dev/null || true

# Run new container
docker run -d \
    --name aurora-app \
    --restart unless-stopped \
    --env-file .env \
    -e ENVIRONMENT=development \
    -e REDIS_URL=redis://host.docker.internal:6379/0 \
    -e TRANSFORMERS_CACHE=/tmp/models \
    -e HF_HOME=/tmp/huggingface \
    -p 127.0.0.1:8001:8000 \
    -v /opt/aurora/app:/app/app \
    -v /opt/aurora/data/chroma:/app/data/chroma_data \
    -v /opt/aurora/data/logs:/app/logs \
    -v /opt/aurora/data/backups:/app/backups \
    --add-host=host.docker.internal:host-gateway \
    aurora:latest

echo "Application container started"
BUILD

# =============================================================================
# Step 6: Configure Nginx
# =============================================================================
log "Step 6: Configuring Nginx..."

$SSH_CMD << NGINX
cat > /etc/nginx/sites-available/aurora << 'EOF'
server {
    listen 80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 60s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/aurora /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "Nginx configured"
NGINX

# =============================================================================
# Step 7: Health Check
# =============================================================================
log "Step 7: Running health check..."

sleep 5

$SSH_CMD << 'HEALTH'
echo "Checking containers..."
docker ps

echo ""
echo "Checking health endpoint..."
curl -s http://localhost:8001/health | head -c 200 || echo "Health check failed"

echo ""
echo "Checking Nginx..."
curl -s -o /dev/null -w "%{http_code}" http://localhost/ || echo "Nginx check failed"
HEALTH

# =============================================================================
# Done
# =============================================================================
echo ""
log "=========================================="
log "Deployment complete!"
log "=========================================="
echo ""
echo "  HTTP:  http://$DOMAIN"
echo "  Health: http://$DOMAIN/health"
echo ""
echo "  Next steps:"
echo "    1. Verify: curl http://$DOMAIN/health"
echo "    2. HTTPS:  ssh root@$DROPLET_IP 'certbot --nginx -d $DOMAIN'"
echo ""
