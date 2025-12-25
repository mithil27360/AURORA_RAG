# Aurora RAG Chatbot

## Setup

### 1. Install Python 3.10+
```bash
python --version  # Should be 3.10 or higher
```

### 2. Create Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
# .venv\Scripts\activate    # Windows
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Add Credentials

Create `.env` file:
```
GROQ_API_KEY=your_groq_api_key
GOOGLE_SHEETS_ID=your_sheet_id
DASHBOARD_USERNAME=your_username
DASHBOARD_PASSWORD=your_password
```

Add `credentials.json` (Google service account key)

### 5. Run
```bash
./scripts/start.sh
```

Open: http://localhost:8000

## URLs

| Page | URL |
|------|-----|
| Chat | http://localhost:8000 |
| Dashboard | http://localhost:8000/dashboard |
| Health | http://localhost:8000/health |


