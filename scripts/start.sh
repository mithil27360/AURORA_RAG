#!/bin/bash
# Aurora RAG Chatbot - Start Script

echo "🚀 Starting Aurora RAG Chatbot..."

# Navigate to project root
cd "$(dirname "$0")/.."

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "❌ No virtual environment found. Run: python -m venv .venv"
    exit 1
fi

# Check dependencies
if ! python -c "import uvicorn" 2>/dev/null; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
fi

# Start server
echo "✅ Server starting at http://localhost:8000"
echo "📊 Dashboard: http://localhost:8000/dashboard"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
