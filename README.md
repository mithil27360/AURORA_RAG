# Aurora Fest RAG Chatbot

![Architecture Diagram](https://via.placeholder.com/800x200?text=Google+Sheets+%2B+Vector+DB+%2B+Groq+LLM)

## Problem Statement
College fests generate chaos: thousands of students asking the same questions ("When is X?", "Where is Y?") to a handful of overwhelmed volunteers. Human support scales poorly and information on static websites becomes outdated instantly.

**Solution**: A production-grade RAG chatbot that provides:
1.  **Instant Answers**: <2s latency for schedule/venue queries.
2.  **Zero Hallucinations**: Strict context-only retrieval.
3.  **Live Updates**: Syncs with the "source of truth" Google Sheet every 5 minutes.

## Architecture Overview
This system provides an intelligent chatbot interface powered by advanced natural language processing, vector search, and real-time data synchronization.

-   **Frontend**: JS/HTML5 Widget.
-   **Backend**: FastAPI Server.
-   **Knowledge**: ChromaDB (Vector) + SQLite (Logs).
-   **Brain**: Llama-3 (Groq API).

## Technology Stack

- **Backend Framework:** FastAPI (Python 3.11+)
- **Vector Database:** ChromaDB with sentence-transformers
- **LLM Integration:** Groq API (Llama 3.3-70B)
- **Data Source:** Google Sheets API
- **Database:** SQLite (interaction logging)
- **Authentication:** HTTP Basic Auth + Session Tokens
- **Frontend:** Vanilla JavaScript + HTML5/CSS3

## Core Features

### Intelligent Query Processing
- Multi-tier intent classification system
- Semantic vector search with configurable similarity thresholds
- Context-aware response generation
- Conversation history management
- Response caching for improved performance

### Data Management
- Real-time Google Sheets synchronization
- Automatic data ingestion and chunking
- Vector database updates with change detection
- Flattened event structure support

### Analytics & Monitoring
- Comprehensive interaction logging
- Real-time analytics dashboard
- Device and browser tracking
- Response time metrics
- Response time metrics
- Confidence score tracking (Ranking signal, not calibrated probability)
- Cached vs. non-cached response analysis

### Security
- Dashboard authentication (username/password)
- Session-based token management (24-hour validity)
- CORS configuration
- Security headers (XSS, clickjacking protection)
- Rate limiting (30 requests/minute per IP)
- Input validation and sanitization
- Constant-time password comparison

## Project Structure

```
iste-rag/
├── app/                         # Modular application package
│   ├── api/                     # API routes and dependencies
│   ├── core/                    # Configuration and settings
│   ├── db/                      # Database clients (Redis, SQLite)
│   ├── services/                # Business logic (LLM, Vector, Sheets, Security)
│   └── static/                  # Frontend assets (HTML, CSS, JS, Images)
├── requirements.txt             # Python dependencies
├── .env                         # Environment configuration (not in git)
├── .env.example                 # Environment template
├── credentials.json             # Google API credentials (not in git)
├── start.sh                     # Server launcher script
├── Dockerfile                   # container definition
├── rag_interactions.db          # SQLite database (not in git)
└── chroma_data/                 # Vector database storage (not in git)
```

## Installation

### Prerequisites
- Python 3.11 or higher
- pip package manager
- Virtual environment (recommended)

### Setup Steps

1. **Clone Repository**
   ```bash
   git clone <repository-url>
   cd "iste rag"
   ```

2. **Create Virtual Environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

5. **Add Google Credentials**
   - Place `credentials.json` in project root
   - Obtain from Google Cloud Console

6. **Start Server**
   ```bash
   chmod +x start.sh
   ./start.sh
   ```

## Configuration

### Environment Variables

Required variables in `.env`:

```env
# Groq API Configuration
GROQ_API_KEY=your_groq_api_key_here

# Google Sheets Configuration
GOOGLE_SHEETS_ID=your_google_sheets_id_here
GOOGLE_CREDENTIALS_FILE=credentials.json

# Application Settings
LOG_LEVEL=WARNING
SYNC_INTERVAL_MINUTES=1

# Security Configuration (CORS)
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

# Dashboard Authentication
DASHBOARD_USERNAME=your_username
DASHBOARD_PASSWORD=your_secure_password
```

### Google Sheets Setup

1. Create Google Cloud Project
2. Enable Google Sheets API
3. Create Service Account
4. Download credentials as `credentials.json`
5. Share your Google Sheet with service account email

## API Endpoints

### Public Endpoints
- `GET /` - Chatbot interface
- `POST /chat` - Process user queries
- `GET /health` - System health check

### Authenticated Endpoints
- `GET /dashboard` - Analytics dashboard (requires auth)
- `GET /analytics` - Analytics data (requires auth)
- `GET /interactions/all` - Full interaction logs (requires auth)

### Authentication Endpoints
- `GET /login-page` - Login interface
- `POST /login` - Authenticate and get session token

## Usage

### Starting the Application

```bash
./start.sh
```

Server will be available at:
- Chatbot: http://localhost:8000
- Dashboard: http://localhost:8000/dashboard
- Login: http://localhost:8000/login-page

### Dashboard Access

1. Navigate to http://localhost:8000/dashboard
2. Enter credentials (configured in `.env`)
3. View real-time analytics and interaction logs

### Stopping the Server

Press `Ctrl+C` in the terminal running the server.

## Development

### Code Style
- Follow PEP 8 guidelines
- Use type hints for function signatures
- Document complex logic with inline comments
- Maintain consistent naming conventions

### Testing

Run the server in development mode:
```bash
uvicorn app.main:app --reload
```

### Logging

Configure log level in `.env`:
- `DEBUG` - Detailed diagnostic information
- `INFO` - General informational messages
- `WARNING` - Warning messages (production recommended)
- `ERROR` - Error messages only

## Deployment

### Production Considerations

1. **Environment Variables**
   - Set all required variables in platform dashboard
   - Never commit `.env` to version control

2. **Security**
   - Use strong passwords for dashboard authentication
   - Configure ALLOWED_ORIGINS for your domain
   - Enable HTTPS (automatic on most platforms)

3. **Database**
   - Implement regular backups of `rag_interactions.db`
   - Consider migrating to PostgreSQL for production scale

4. **Monitoring**
   - Set up logging aggregation
   - Monitor rate limit violations
   - Track response times and confidence scores

### Supported Platforms
- Google Cloud Run
- Railway.app
- Heroku
- Any platform supporting Python 3.11+ and Docker

## Security

### Authentication Flow
1. User accesses dashboard
2. Redirected to login page if not authenticated
3. Credentials validated against environment variables
4. Session token generated (24-hour validity)
5. Token stored client-side and validated server-side

### Security Features
- Constant-time password comparison (timing attack prevention)
- Session token expiration
- Failed login attempt logging
- Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
- CORS restrictions
- Rate limiting per IP address

## Design Philosophy (Implementation Choices)

### 1. Confidence Scores
Our `confidence_score` is designed as a **Relative Ranking Signal**, not a calibrated probability. It combines vector cosine similarity with metadata boosts (e.g., specific event matches) to prioritize "best-effort" retrieval over strict probabilistic confidence.

### 2. Regex Intent Classification
We explicitly chose Regex over LLM-based classification for the first pass because:
- **Determinism**: Critical for routing (e.g., "Schedule" queries MUST hit schedule filters).
- **Latency**: <1ms execution time vs 500ms+ for LLM.
- **Auditability**: Rules are transparent and easily debugged.

### 3. Trust Model
See [SECURITY.md](SECURITY.md) for full details. We treat Google Sheets as a **Trusted Source** within our boundary, while treating all User Input as untrusted.

## Troubleshooting

### Common Issues

**Server won't start:**
- Check if port 8000 is already in use
- Verify all environment variables are set
- Ensure virtual environment is activated

**Authentication fails:**
- Verify credentials in `.env`
- Check for typos in username/password
- Clear browser cache/cookies

**Google Sheets sync fails:**
- Verify `credentials.json` is present
- Check service account has sheet access
- Confirm GOOGLE_SHEETS_ID is correct

## License

[Specify your license]

## Support

For issues or questions, contact the development team or create an issue in the repository.

## Acknowledgments

Built with:
- FastAPI
- ChromaDB
- Groq API
- SentenceTransformers
- Google Sheets API

---

**Version:** 2.0.0  
**Last Updated:** 2025-12-24  
**Status:** Production Ready
