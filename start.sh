#!/bin/bash

# Aurora Fest RAG Chatbot - Startup Script with Virtual Environment

echo "🚀 Aurora Fest RAG Chatbot - Starting..."
echo "═══════════════════════════════════════════"

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✅ Virtual environment activated"
else
    echo "❌ Virtual environment not found. Run: python3 -m venv venv"
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Check credentials file
if [ ! -f "$GOOGLE_CREDENTIALS_FILE" ]; then
    echo "❌ Error: $GOOGLE_CREDENTIALS_FILE not found!"
    exit 1
fi

# Check Groq API key
if [ -z "$GROQ_API_KEY" ]; then
    echo "❌ Error: GROQ_API_KEY not set in .env file!"
    exit 1
fi

# Check Google Sheets ID
if [ -z "$GOOGLE_SHEETS_ID" ]; then
    echo "❌ Error: GOOGLE_SHEETS_ID not set in .env file!"
    exit 1
fi

echo "✅ Configuration validated"
echo "✅ Credentials found"
echo ""
echo "📍 Starting server on http://$HOST:$PORT"
echo "🔄 Auto-sync interval: $SYNC_INTERVAL_MINUTES minutes"
echo "📊 Google Sheets ID: $GOOGLE_SHEETS_ID"
echo ""
echo "═══════════════════════════════════════════"
echo "Press Ctrl+C to stop the server"
echo "═══════════════════════════════════════════"
echo ""

# Start the server
python3 aurora_v2.py
