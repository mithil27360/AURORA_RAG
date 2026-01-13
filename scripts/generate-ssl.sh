#!/bin/bash
# SSL Certificate Generation Script for Aurora Monitoring Stack
# Generates self-signed certificates for development/testing

set -e

echo "🔐 Generating SSL Certificates for Aurora Monitoring Stack..."

# Create SSL directory
mkdir -p config/ssl

# Prometheus Certificate
echo "  Generating Prometheus certificate..."
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout config/ssl/prometheus.key \
  -out config/ssl/prometheus.crt \
  -subj "/C=IN/ST=State/L=City/O=Aurora/CN=prometheus.local" \
  2>/dev/null

# Grafana Certificate  
echo "  Generating Grafana certificate..."
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout config/ssl/grafana.key \
  -out config/ssl/grafana.crt \
  -subj "/C=IN/ST=State/L=City/O=Aurora/CN=grafana.local" \
  2>/dev/null

# Set permissions
chmod 600 config/ssl/*.key
chmod 644 config/ssl/*.crt

echo "✅ SSL Certificates generated successfully!"
echo ""
echo "📁 Generated files:"
echo "  - config/ssl/prometheus.key"
echo "  - config/ssl/prometheus.crt"
echo "  - config/ssl/grafana.key" 
echo "  - config/ssl/grafana.crt"
echo ""
echo "⚠️  These are self-signed certificates for development only."
echo "   For production, use proper CA-signed certificates (e.g., Let's Encrypt)"
