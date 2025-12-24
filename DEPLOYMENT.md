# Deployment Guide

> **Production Readiness**: This application is designed to be "restart-friendly". Below are the recommended methods to run it in a production environment.

## 1. Simple Background Service (Recommended for Fest)

Use `nohup` to keep the server running even if you close your terminal.

```bash
# Start server in background
chmod +x start.sh
nohup ./start.sh > app.log 2>&1 &

# Check status
ps aux | grep aurora_v2

# Follow logs
tail -f app.log

# Stop server
pkill -f aurora_v2.py
```

## 2. Robust Session Management (Screen/Tmux)

Use `screen` to manage the session interactively.

```bash
# Create new session
screen -S aurora

# inside the screen session:
./start.sh

# Detach (Press Ctrl+A, then D)

# Reattach later
screen -r aurora
```

## 3. Process Manager (PM2 - Node.js required)

If you have Node.js installed, `pm2` provides auto-restart on crash.

```bash
# Install pm2
npm install -g pm2

# Start python script
pm2 start aurora_v2.py --interpreter python3 --name "aurora-rag"

# View logs
pm2 logs aurora-rag

# Monitor status
pm2 monit
```

## 4. Docker Deployment

For containerized environments (useful if moving to cloud).

```bash
# Build image
docker build -t aurora-bot .

# Run container (restart on failure)
docker run -d \
  --name aurora-container \
  --restart always \
  -p 8000:8000 \
  --env-file .env \
  -v $(pwd)/rag_interactions.db:/app/rag_interactions.db \
  aurora-bot
```

## Operational Checklist

- [ ] **STRICT_MODE**: Ensure `STRICT_MODE=True` in `.env` for production.
- [ ] **Logs**: Monitor `rag_interactions.db` (SQLite) or `app.log`.
- [ ] **Updates**: The system auto-syncs with Google Sheets every 5 minutes (configurable).
- [ ] **Backups**: periodically backup `rag_interactions.db`.
