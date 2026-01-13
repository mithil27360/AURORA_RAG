#!/bin/bash
# Ensure we are in the project root
cd "$(dirname "$0")/.."

# Kill existing process on 8001 if any
lsof -ti:8001 | xargs kill -9 2>/dev/null

# Start Uvicorn
nohup ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 > uvicorn_prod.log 2>&1 &
PID=$!
echo "Started Uvicorn on port 8001 with PID $PID"
echo $PID > app.pid
sleep 2
if ps -p $PID > /dev/null; then
    echo "Process $PID is running."
    exit 0
else
    echo "Process immediately died. Check uvicorn_prod.log:"
    cat uvicorn_prod.log
    exit 1
fi
