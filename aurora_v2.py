#!/usr/bin/env python3
"""
AURORA FEST RAG CHATBOT - PRODUCTION VERSION
With Google Sheets Integration, Auto-Sync, and Conversational AI
"""

import json, os, sys, hashlib, logging, time, asyncio, sqlite3, re, uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict
from user_agents import parse as parse_user_agent

# --- SILENCE WARNINGS ---
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["PYDANTIC_V1_ONLY_BACKCOMPAT"] = "1"  # For Python 3.14 compatibility
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="chromadb")

import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
import secrets  # For secure password comparison
import chromadb
from chromadb.utils import embedding_functions
from groq import Groq
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from apscheduler.schedulers.background import BackgroundScheduler
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

load_dotenv()

BASE_DIR = Path(__file__).parent
CHROMA_PATH = BASE_DIR / "chroma_data"

# Environment Variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL_MINUTES", "5"))
AUTO_SYNC = os.getenv("AUTO_SYNC_ENABLED", "true").lower() == "true"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# RAG Settings - Ultra-permissive for maximum event coverage
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.05"))  # Very permissive - retrieve everything relevant
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "50"))

# Production Limits & Timeouts (Explicit Constants)
MAX_CONVERSATION_USERS = 10000
MAX_CACHE_ENTRIES = 5000
CACHE_TTL_SECONDS = 300
LLM_TIMEOUT_SECONDS = 20.0
SYNC_TIMEOUT_SECONDS = 60.0  # Increased to 50 to catch detailed chunks
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# Setup Logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global State
last_sync_time: Optional[datetime] = None
sync_lock = asyncio.Lock()
analytics_log = []
interaction_logger = None  # Will be initialized on startup (InteractionLogger instance)

# Session Management for Dashboard Login
active_sessions = {}  # {token: {"username": str, "created_at": datetime}}
SESSION_TIMEOUT_HOURS = 24
conversation_history = {}  # Session-based conversation history: {user_id: [(query, answer), ...]}
response_cache = {}  # Response cache: {query_hash: {"answer": str, "confidence": float, "timestamp": float, "tier": str, "intent": str}}

# ═══════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    query: str
    threshold: Optional[float] = SIMILARITY_THRESHOLD

class ChatResponse(BaseModel):
    answer: str
    confidence: float
    tier: str
    response_time_ms: float
    intent: str
    timestamp: str

class HealthResponse(BaseModel):
    status: str
    last_sync: Optional[str]
    vector_db_count: int
    uptime_seconds: float
    auto_sync_enabled: bool

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    message: str

# ═══════════════════════════════════════════════════════════════════════════
# INTENT CLASSIFICATION (Production-Grade Query Routing)
# ═══════════════════════════════════════════════════════════════════════════

class IntentClassifier:
    """Classify user queries to route to appropriate retrieval strategies"""
    
    INTENT_PATTERNS = {
        "schedule": r"\b(when|time|date|day|schedule|timing|session|happening)\b",
        "prerequisites": r"\b(prerequisite|require|need|prior|should know|must know|background)\b",
        "certificate": r"\b(certificate|cert|certification)\b",
        "registration": r"\b(register|registration|sign up|enroll|join|participate)\b",
        "eligibility": r"\b(can i|eligible|allowed|who can|requirements for)\b",
        "technical": r"\b(learn|teach|cover|topic|content|what will|project|build)\b",
        "logistics": r"\b(venue|location|where|room|building|lab)\b",
        "contact": r"\b(who|contact|email|phone|coordinator|organizer|reach)\b",
        "comparison": r"\b(difference|compare|versus|vs|better|similar)\b",
        "list": r"\b(all|list|what are|show me|tell me about all|which|events)\b",
    }
    
    @classmethod
    def classify(cls, query: str) -> str:
        """Classify query intent using pattern matching"""
        query_lower = query.lower()
        
        # Check each pattern
        for intent, pattern in cls.INTENT_PATTERNS.items():
            if re.search(pattern, query_lower):
                return intent
        
        return "general"
    
    @classmethod
    def get_retrieval_filters(cls, intent: str) -> Dict:
        """Get ChromaDB filters based on intent"""
        filters = {"is_latest": True}
        
        if intent == "schedule":
            filters["type"] = {"$in": ["schedule_detailed", "schedule_time", "temporal_schedule"]}
        elif intent == "prerequisites":
            filters["type"] = {"$in": ["schedule_prerequisites", "event_detailed"]}
        elif intent == "certificate":
            filters["type"] = {"$in": ["event_requirements", "certificate_opportunities"]}
        elif intent == "contact":
            filters["type"] = {"$in": ["contact_detailed", "contact_quick", "cross_reference"]}
        elif intent == "venue":
            filters["type"] = {"$in": ["venue_detailed", "venue_location", "cross_reference"]}
        
        return filters

# ═══════════════════════════════════════════════════════════════════════════
# INTERACTION LOGGING (Production-Grade Observability)
# ═══════════════════════════════════════════════════════════════════════════

class InteractionLogger:
    """SQLite-based interaction logging for post-analysis and debugging"""
    
    def __init__(self, db_path: str = "rag_interactions.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database with schema"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # DEV MODE: Drop table to ensure schema update (since we calculate cols matching insert)
        # In production, use ALTER TABLE or migrations
        try:
            # Check if columns are missing by selecting
            c.execute("SELECT cached FROM interactions LIMIT 1")
        except sqlite3.OperationalError:
            # Column missing or table doesn't exist - safer to recreate
            logger.warning("Schema mismatch detected. Recreating interactions table.")
            c.execute("DROP TABLE IF EXISTS interactions")
            
        c.execute('''
            CREATE TABLE IF NOT EXISTS interactions (
                interaction_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                user_id TEXT,
                query_text TEXT NOT NULL,
                detected_intent TEXT,
                retrieved_doc_ids TEXT,
                retrieval_scores TEXT,
                answer TEXT NOT NULL,
                confidence_score REAL,
                response_type TEXT,
                used_doc_ids TEXT,
                llm_model TEXT,
                response_time_ms REAL,
                cached INTEGER DEFAULT 0,
                device_type TEXT,
                browser TEXT,
                os TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
        logger.info(f"Interaction logging initialized: {self.db_path}")
    
    def log_interaction(
        self,
        query: str,
        answer: str,
        intent: str,
        retrieved_docs: List[Dict],
        confidence: float,
        response_type: str,
        used_docs: List[str],
        response_time_ms: float,
        user_id: Optional[str] = None,
        cached: bool = False,
        device_type: Optional[str] = None,
        browser: Optional[str] = None,
        os: Optional[str] = None,
        interaction_id: Optional[str] = None
    ):
        """Log a complete RAG interaction"""
        if interaction_id is None:
            interaction_id = str(uuid.uuid4())
        
        # Extract doc IDs and scores
        doc_ids = [d.get('id', 'unknown') for d in retrieved_docs]
        scores = [d.get('distance', 0.0) for d in retrieved_docs]
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO interactions 
            (interaction_id, timestamp, user_id, query_text, detected_intent,
             retrieved_doc_ids, retrieval_scores, answer, confidence_score,
             response_type, used_doc_ids, llm_model, response_time_ms, cached,
             device_type, browser, os)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            interaction_id,
            datetime.now().isoformat(),  # Changed from utcnow() to now() for IST
            user_id or "anonymous",
            query,
            intent,
            json.dumps(doc_ids),
            json.dumps(scores),
            answer,
            confidence,
            response_type,
            json.dumps(used_docs),
            "llama-3.3-70b-versatile",
            response_time_ms,
            1 if cached else 0,
            device_type,
            browser,
            os
        ))
        conn.commit()
        conn.close()
        
        return interaction_id
    
    def get_stats(self) -> Dict:
        """Get interaction statistics"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        stats = {}
        
        # Total interactions
        c.execute("SELECT COUNT(*) FROM interactions")
        stats['total_interactions'] = c.fetchone()[0]
        
        # Top intents
        c.execute("""
            SELECT detected_intent, COUNT(*) as count
            FROM interactions
            GROUP BY detected_intent
            ORDER BY count DESC
            LIMIT 5
        """)
        stats['top_intents'] = dict(c.fetchall())
        
        # Low confidence count
        c.execute("SELECT COUNT(*) FROM interactions WHERE confidence_score < 0.5")
        stats['low_confidence_count'] = c.fetchone()[0]
        
        # Average confidence
        c.execute("SELECT AVG(confidence_score) FROM interactions")
        stats['avg_confidence'] = c.fetchone()[0] or 0.0
        
        conn.close()
        return stats

# ═══════════════════════════════════════════════════════════════════════════
# CONVERSATIONAL INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════════════

class ConversationalHandler:
    """Handles casual conversation and intent classification"""
    
    GREETINGS = [
        "hi", "hello", "hey", "good morning", "good afternoon", 
        "good evening", "namaste", "hola", "greetings"
    ]
    
    FAREWELLS = [
        "bye", "goodbye", "see you", "later", "cya", "take care"
    ]
    
    GRATITUDE = [
        "thank", "thanks", "appreciate", "grateful", "thx"
    ]
    
    GREETING_RESPONSES = [
        "Hello! Welcome to Aurora Fest! I'm here to help you with event schedules, venues, registration, and any questions you have. What would you like to know?",
        "Hey there! Welcome to Aurora Fest 2025! Ask me anything about our events, timings, venues, or how to register!",
        "✨ Hi! I'm your Aurora Fest assistant. I can help you with event details, schedules, locations, and more. How can I assist you today?"
    ]
    
    FAREWELL_RESPONSES = [
        "You're welcome! Enjoy Aurora Fest! Feel free to ask if you have more questions. See you! ",
        "✨ Happy to help! Have an amazing time at Aurora Fest! Come back if you need anything! ",
        "🌟 Glad I could help! Enjoy the fest and all the events! See you around! 💫"
    ]
    
    GRATITUDE_RESPONSES = [
        "😊 You're very welcome! Happy to help! If you have any other questions about Aurora Fest, just ask!",
        "🎊 My pleasure! That's what I'm here for! Feel free to ask anything else!",
        "💫 Anytime! Enjoy Aurora Fest and don't hesitate to reach out if you need more help!"
    ]
    
    def classify_intent(self, query: str) -> str:
        """Classify user intent"""
        q_lower = query.lower().strip()
        
        # Check for greetings
        if any(greet in q_lower for greet in self.GREETINGS):
            # If it's just a greeting (short message), classify as greeting
            if len(q_lower.split()) <= 3:
                return "greeting"
        
        # Check for gratitude
        if any(thanks in q_lower for thanks in self.GRATITUDE):
            return "gratitude"
        
        # Check for farewells
        if any(bye in q_lower for bye in self.FAREWELLS):
            return "farewell"
        
        # Otherwise, it's a question
        return "question"
    
    def get_casual_response(self, intent: str) -> str:
        """Get appropriate casual response"""
        import random
        
        if intent == "greeting":
            return random.choice(self.GREETING_RESPONSES)
        elif intent == "farewell" or intent == "gratitude":
            # Use same response pool for both
            return random.choice(self.FAREWELL_RESPONSES + self.GRATITUDE_RESPONSES)
        return ""

# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS DATA LOADER
# ═══════════════════════════════════════════════════════════════════════════

class GoogleSheetsChunker:
    """Load data from Google Sheets instead of Excel"""
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets.readonly',
        'https://www.googleapis.com/auth/drive.readonly'
    ]
    
    def __init__(self, sheets_id: str, creds_file: str):
        self.sheets_id = sheets_id
        self.creds_file = creds_file
        self._connect()
        self._load_sheets()
    
    def _connect(self):
        """Authenticate and connect to Google Sheets"""
        try:
            creds_path = BASE_DIR / self.creds_file
            if not creds_path.exists():
                raise FileNotFoundError(f"Credentials file not found: {creds_path}")
            
            creds = Credentials.from_service_account_file(
                str(creds_path), 
                scopes=self.SCOPES
            )
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open_by_key(self.sheets_id)
            logger.info(f"Connected to Google Sheets: {self.spreadsheet.title}")
        except Exception as e:
            logger.error(f"Google Sheets connection failed: {e}")
            raise
    
    def _load_sheets(self):
        """Load worksheets - supports both NEW flattened and OLD multi-sheet structures"""
        try:
            # Try NEW flattened structure first (single "Events_Complete" sheet)
            events_flat = self._get_df('Events_Complete')
            
            if not events_flat.empty and 'event_name' in events_flat.columns:
                logger.info("Detected NEW flattened sheet structure")
                self.use_flat_structure = True
                self.events_flat = events_flat
                # Still load FAQs (separate sheet)
                self.faqs = self._get_df('FAQs')
                logger.info(f"Loaded {len(events_flat)} event-day entries from flattened structure")
            else:
                # Fall back to OLD multi-sheet structure
                logger.info("Using OLD multi-sheet structure")
                self.use_flat_structure = False
                self.events = self._get_df('Events_Master')
                self.details = self._get_df('Event_Details')
                self.faqs = self._get_df('FAQs')
                self.venues = self._get_df('Venues')
                self.contacts = self._get_df('Contacts')
                self.campus = self._get_df('Campus_Info')
                self.flags = self._get_df('Live_Flags')
                logger.info(f"Loaded {len(self.events)} events from Google Sheets")
        except Exception as e:
            logger.error(f"Error loading sheets: {e}")
            raise
    
    def _get_df(self, sheet_name: str) -> pd.DataFrame:
        """Get worksheet as DataFrame"""
        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
            data = worksheet.get_all_records()
            return pd.DataFrame(data)
        except Exception as e:
            logger.warning(f"Sheet '{sheet_name}' not found or empty, using empty DataFrame")
            return pd.DataFrame()
    
    def val(self, row, col, default='N/A') -> str:
        """Safe value extraction"""
        try:
            v = row.get(col, default)
            if pd.isna(v) or v == '':
                return default
            return str(v).strip()
        except:
            return default
    
    
    def chunks(self) -> List[Dict]:
        """PRODUCTION-GRADE CHUNKING - Supports both flat and multi-sheet structures"""
        # Route to appropriate chunking method based on detected structure
        if hasattr(self, 'use_flat_structure') and self.use_flat_structure:
            return self._chunks_from_flat_structure()
        else:
            return self._chunks_from_multi_sheet()
    
    def _chunks_from_multi_sheet(self) -> List[Dict]:
        """high-quality CHUNKING - Multiple chunk types per sheet for maximum retrieval (OLD STRUCTURE)"""
        chunks = []
        
        # ═══════════════════════════════════════════════════════════════
        # 1. EVENTS_MASTER - 6 Chunk Types per Event
        # ═══════════════════════════════════════════════════════════════
        event_list = []
        events_by_type = {}  # For type-based summaries
        
        for _, e in self.events.iterrows():
            event_id = self.val(e, 'event_id')
            name = self.val(e, 'event_name')
            club = self.val(e, 'club_name')
            etype = self.val(e, 'event_type')
            status = self.val(e, 'status')
            priority = self.val(e, 'priority')
            start = self.val(e, 'start_date')
            end = self.val(e, 'end_date')
            days = self.val(e, 'num_days')
            reg_req = self.val(e, 'registration_required')
            cert = self.val(e, 'certificate_offered')
            
            if name != 'N/A':
                event_list.append(name)
                events_by_type.setdefault(etype, []).append(name)
                
                # CHUNK 1: Detailed Information Chunk
                detailed = f"""Event: {name}
Type: {etype}
Organized by: {club}
Status: {status}
Priority: {priority}
Duration: {start} to {end} ({days} days)
Registration Required: {reg_req}
Certificate Offered: {cert}
Event ID: {event_id}"""
                chunks.append({
                    "text": detailed,
                    "meta": {"type": "event_detailed", "event": name, "event_id": event_id, "event_type": etype}
                })
                
                # CHUNK 2: Conversational "What is" Chunk
                conversational = f"{name} is a {days}-day {etype} event organized by {club}. It runs from {start} to {end}."
                if reg_req.lower() == 'yes':
                    conversational += f" Registration is required."
                if cert.lower() == 'yes':
                    conversational += f" Participants will receive certificates."
                chunks.append({
                    "text": conversational,
                    "meta": {"type": "event_conversational", "event": name}
                })
                
                # CHUNK 3: Date-focused Chunk (for "when" queries)
                date_chunk = f"{name} happens from {start} to {end} ({days} days). Priority: {priority}."
                chunks.append({
                    "text": date_chunk,
                    "meta": {"type": "event_dates", "event": name, "start_date": start, "end_date": end}
                })
                
                # CHUNK 4: Club/Organizer focused Chunk
                organizer_chunk = f"{club} is organizing {name}, a {etype} event. Contact them for more details about this {priority.lower()} priority event."
                chunks.append({
                    "text": organizer_chunk,
                    "meta": {"type": "event_organizer", "event": name, "club": club}
                })
                
                # CHUNK 5: Requirements Chunk
                if reg_req != 'N/A' or cert != 'N/A':
                    req_chunk = f"{name} - Registration {'required' if reg_req.lower() == 'yes' else 'not required'}. Certificate {'offered' if cert.lower() == 'yes' else 'not offered'}."
                    chunks.append({
                        "text": req_chunk,
                        "meta": {"type": "event_requirements", "event": name}
                    })
        
        # CHUNK 6: Master Event List
        if event_list:
            all_events = "Complete Event List at Aurora Fest 2025:\n" + "\n".join([f"{i+1}. {evt}" for i, evt in enumerate(event_list)])
            chunks.append({
                "text": all_events,
                "meta": {"type": "event_list_master", "count": len(event_list)}
            })
        
        # CHUNK 7: Events by Type Summary
        for etype, events in events_by_type.items():
            type_summary = f"{etype}s at Aurora Fest: " + ", ".join(events)
            chunks.append({
                "text": type_summary,
                "meta": {"type": "events_by_type", "event_type": etype, "count": len(events)}
            })
        
        # ═══════════════════════════════════════════════════════════════
        # 2. EVENT_DETAILS - 4 Chunk Types per Session
        # ═══════════════════════════════════════════════════════════════
        for _, s in self.details.iterrows():
            event_id = self.val(s, 'event_id')
            name = self.val(s, 'event_name', 'Unknown Event')
            session = self.val(s, 'session_number', '1')
            date = self.val(s, 'date')
            start = self.val(s, 'start_time')
            end = self.val(s, 'end_time')
            venue = self.val(s, 'venue_id', '')
            knowledge = self.val(s, 'preferred_knowledge', '')
            outcome = self.val(s, 'expected_outcome', '')
            
            if name != 'N/A' and name != 'Unknown Event':
                # CHUNK 1: Complete Schedule Chunk
                schedule = f"""{name} - Session {session}
Date: {date}
Time: {start} to {end}
Venue: {venue if venue != 'N/A' else 'TBD'}"""
                if knowledge and knowledge != 'N/A':
                    schedule += f"\nPrerequisites: {knowledge}"
                if outcome and outcome != 'N/A':
                    schedule += f"\nYou'll Learn: {outcome}"
                    
                chunks.append({
                    "text": schedule,
                    "meta": {"type": "schedule_detailed", "event": name, "session": session, "date": date}
                })
                
                # CHUNK 2: Time-focused Chunk (for "when" queries)
                time_chunk = f"{name} session {session} is on {date} from {start} to {end}."
                chunks.append({
                    "text": time_chunk,
                    "meta": {"type": "schedule_time", "event": name, "date": date}
                })
                
                # CHUNK 3: Prerequisites Chunk (for "what do I need" queries)
                if knowledge and knowledge != 'N/A':
                    prereq_chunk = f"For {name}, you should know: {knowledge}. This will help you get the most out of the session."
                    chunks.append({
                        "text": prereq_chunk,
                        "meta": {"type": "schedule_prerequisites", "event": name}
                    })
                
                # CHUNK 4: Outcomes Chunk (for "what will I learn" queries)
                if outcome and outcome != 'N/A':
                    outcome_chunk = f"In {name}, you will: {outcome}. This is a hands-on session designed for practical learning."
                    chunks.append({
                        "text": outcome_chunk,
                        "meta": {"type": "schedule_outcomes", "event": name}
                    })
        
        # ═══════════════════════════════════════════════════════════════
        # 3. FAQS - 3 Chunk Types per FAQ
        # ═══════════════════════════════════════════════════════════════
        faq_by_category = {}
        
        for _, f in self.faqs.iterrows():
            q = self.val(f, 'question')
            a = self.val(f, 'answer')
            category = self.val(f, 'category', 'General')
            event_id = self.val(f, 'event_id', '')
            
            if q != 'N/A' and a != 'N/A':
                # CHUNK 1: Standard Q&A Format
                chunks.append({
                    "text": f"Q: {q}\nA: {a}",
                    "meta": {"type": "faq_standard", "category": category, "event_id": event_id}
                })
                
                # CHUNK 2: Natural Language Format (for conversational queries)
                natural = f"Regarding {category.lower()}: {q} {a}"
                chunks.append({
                    "text": natural,
                    "meta": {"type": "faq_natural", "category": category}
                })
                
                # CHUNK 3: Answer-focused (for direct info retrieval)
                chunks.append({
                    "text": a,
                    "meta": {"type": "faq_answer", "question": q[:50], "category": category}
                })
                
                # Track for category summary
                faq_by_category.setdefault(category, []).append(q)
        
        # FAQ Category Summaries
        for category, questions in faq_by_category.items():
            category_summary = f"{category} FAQs cover: " + ", ".join([q[:40] + "..." if len(q) > 40 else q for q in questions])
            chunks.append({
                "text": category_summary,
                "meta": {"type": "faq_category_summary", "category": category}
            })
        
        # ═══════════════════════════════════════════════════════════════
        # 4. VENUES - 4 Chunk Types per Venue
        # ═══════════════════════════════════════════════════════════════
        venue_list = []
        
        for _, v in self.venues.iterrows():
            venue_id = self.val(v, 'venue_id')
            name = self.val(v, 'venue_name')
            building = self.val(v, 'building')
            capacity = self.val(v, 'capacity', '')
            amenities = self.val(v, 'amenities', '')
            contact = self.val(v, 'booking_contact', '')
            
            if name != 'N/A':
                venue_list.append(f"{name} ({building})")
                
                # CHUNK 1: Complete Venue Info
                venue_complete = f"""Venue: {name}
Building: {building}
Capacity: {capacity if capacity != 'N/A' else 'Not specified'}
Amenities: {amenities if amenities != 'N/A' else 'Standard facilities'}"""
                if contact and contact != 'N/A':
                    venue_complete += f"\nBooking: {contact}"
                    
                chunks.append({
                    "text": venue_complete,
                    "meta": {"type": "venue_detailed", "venue": name, "venue_id": venue_id, "building": building}
                })
                
                # CHUNK 2: Location-focused (for "where" queries)
                location_chunk = f"{name} is located in {building}. It can accommodate {capacity if capacity != 'N/A' else 'multiple'} people."
                chunks.append({
                    "text": location_chunk,
                    "meta": {"type": "venue_location", "venue": name}
                })
                
                # CHUNK 3: Amenities-focused
                if amenities and amenities != 'N/A':
                    amenity_chunk = f"{name} features: {amenities}. Perfect for events requiring these facilities."
                    chunks.append({
                        "text": amenity_chunk,
                        "meta": {"type": "venue_amenities", "venue": name}
                    })
                
                # CHUNK 4: Capacity-focused (for planning queries)
                if capacity and capacity != 'N/A':
                    capacity_chunk = f"{name} in {building} has a capacity of {capacity} people, making it suitable for medium to large events."
                    chunks.append({
                        "text": capacity_chunk,
                        "meta": {"type": "venue_capacity", "venue": name}
                    })
        
        # Venue Summary
        if venue_list:
            venue_summary = "Available venues: " + ", ".join(venue_list)
            chunks.append({
                "text": venue_summary,
                "meta": {"type": "venue_list", "count": len(venue_list)}
            })
        
        # ═══════════════════════════════════════════════════════════════
        # 5. CONTACTS - 3 Chunk Types per Contact
        # ═══════════════════════════════════════════════════════════════
        contacts_by_club = {}
        
        for _, c in self.contacts.iterrows():
            name = self.val(c, 'name')
            role = self.val(c, 'role')
            phone = self.val(c, 'phone')
            email = self.val(c, 'email', '')
            club = self.val(c, 'club_affiliation', '')
            event_id = self.val(c, 'event_id', '')
            
            if name != 'N/A':
                # CHUNK 1: Complete Contact Card
                contact_full = f"""Contact: {name}
Role: {role}
Club: {club if club != 'N/A' else 'Aurora Team'}
Phone: {phone if phone != 'N/A' else 'Available on request'}
Email: {email if email != 'N/A' else 'Available on request'}"""
                chunks.append({
                    "text": contact_full,
                    "meta": {"type": "contact_detailed", "name": name, "role": role, "club": club}
                })
                
                # CHUNK 2: Quick Reference (for "who to contact" queries)
                quick_contact = f"For {role} matters, contact {name}"
                if phone and phone != 'N/A':
                    quick_contact += f" at {phone}"
                if club and club != 'N/A':
                    quick_contact += f" from {club}"
                chunks.append({
                    "text": quick_contact,
                    "meta": {"type": "contact_quick", "name": name}
                })
                
                # CHUNK 3: Role-specific (for "who is in charge of" queries)  
                role_chunk = f"{name} is the {role}"
                if club and club != 'N/A':
                    role_chunk += f" for {club}"
                role_chunk += ". Reach out for event-specific queries."
                chunks.append({
                    "text": role_chunk,
                    "meta": {"type": "contact_role", "role": role, "name": name}
                })
                
                # Track for club summary
                if club and club != 'N/A':
                    contacts_by_club.setdefault(club, []).append(f"{name} ({role})")
        
        # Contact Summaries by Club
        for club, members in contacts_by_club.items():
            club_contacts = f"{club} team: " + ", ".join(members)
            chunks.append({
                "text": club_contacts,
                "meta": {"type": "contact_club_summary", "club": club}
            })
        
        # ═══════════════════════════════════════════════════════════════
        # 6. CAMPUS_INFO - 4 Chunk Types per Service
        # ═══════════════════════════════════════════════════════════════
        services_by_category = {}
        
        for _, ci in self.campus.iterrows():
            category = self.val(ci, 'category')
            title = self.val(ci, 'title')
            description = self.val(ci, 'description')
            location = self.val(ci, 'location', '')
            contact = self.val(ci, 'contact', '')
            hours = self.val(ci, 'hours', '')
            
            if title != 'N/A' and description != 'N/A':
                # CHUNK 1: Complete Service Info
                service_full = f"""{title} - {category}
{description}
Location: {location if location != 'N/A' else 'Contact for details'}
Hours: {hours if hours != 'N/A' else 'Variable'}"""
                if contact and contact != 'N/A':
                    service_full += f"\nContact: {contact}"
                    
                chunks.append({
                    "text": service_full,
                    "meta": {"type": "campus_detailed", "title": title, "category": category}
                })
                
                # CHUNK 2: Location-focused (for "where is" queries)
                if location and location != 'N/A':
                    location_chunk = f"{title} is located at {location}. {description}"
                    chunks.append({
                        "text": location_chunk,
                        "meta": {"type": "campus_location", "title": title}
                    })
                
                # CHUNK 3: Hours-focused (for "when is X open" queries)
                if hours and hours != 'N/A':
                    hours_chunk = f"{title} is open {hours}. Find it at {location if location != 'N/A' else 'campus'}."
                    chunks.append({
                        "text": hours_chunk,
                        "meta": {"type": "campus_hours", "title": title}
                    })
                
                # CHUNK 4: Category-focused Description
                category_chunk = f"{title} ({category}): {description}"
                chunks.append({
                    "text": category_chunk,
                    "meta": {"type": "campus_category", "category": category, "title": title}
                })
                
                # Track for category summary
                services_by_category.setdefault(category, []).append(title)
        
        # Campus Service Categories
        for category, services in services_by_category.items():
            category_summary = f"{category} services on campus: " + ", ".join(services)
            chunks.append({
                "text": category_summary,
                "meta": {"type": "campus_category_summary", "category": category}
            })
        
        # ═══════════════════════════════════════════════════════════════
        # 7. LIVE_FLAGS - 2 Chunk Types per Active Flag
        # ═══════════════════════════════════════════════════════════════
        for _, lf in self.flags.iterrows():
            flag_type = self.val(lf, 'flag_type')
            message = self.val(lf, 'message')
            event_id = self.val(lf, 'event_id', '')
            is_active = self.val(lf, 'is_active', 'No')
            start_time = self.val(lf, 'start_time', '')
            end_time = self.val(lf, 'end_time', '')
            
            if is_active.lower() == 'yes' and message != 'N/A':
                # CHUNK 1: Urgent Alert Format
                alert = f"🚨 {flag_type.upper()}: {message}"
                if start_time and start_time != 'N/A':
                    alert += f" (Valid from {start_time}"
                    if end_time and end_time != 'N/A':
                        alert += f" to {end_time}"
                    alert += ")"
                chunks.append({
                    "text": alert,
                    "meta": {"type": "live_flag_urgent", "flag_type": flag_type, "event_id": event_id}
                })
                
                # CHUNK 2: Conversational Format
                conversational_alert = f"Important {flag_type.lower()} update: {message}"
                chunks.append({
                    "text": conversational_alert,
                    "meta": {"type": "live_flag_info", "flag_type": flag_type}
                })
        
        # ═══════════════════════════════════════════════════════════════
        # optimized ENHANCEMENTS
        # ═══════════════════════════════════════════════════════════════
        
        # 8. CROSS-REFERENCE CHUNKS - Link events with venues and contacts
        event_venue_map = {}
        for _, s in self.details.iterrows():
            event_name = self.val(s, 'event_name')
            venue_id = self.val(s, 'venue_id')
            if event_name != 'N/A' and venue_id != 'N/A':
                event_venue_map.setdefault(event_name, []).append(venue_id)
        
        for event_name, venue_ids in event_venue_map.items():
            # Find venue names
            venue_names = []
            for vid in venue_ids:
                for _, v in self.venues.iterrows():
                    if self.val(v, 'venue_id') == vid:
                        venue_names.append(self.val(v, 'venue_name'))
                        break
            
            if venue_names:
                cross_ref = f"{event_name} will be held at {', '.join(set(venue_names))}. "
                # Find event organizer
                for _, e in self.events.iterrows():
                    if self.val(e, 'event_name') == event_name:
                        club = self.val(e, 'club_name')
                        if club != 'N/A':
                            cross_ref += f"Organized by {club}. "
                            # Find contact
                            for _, c in self.contacts.iterrows():
                                if self.val(c, 'club_affiliation') == club or self.val(c, 'event_id') == self.val(e, 'event_id'):
                                    contact_name = self.val(c, 'name')
                                    if contact_name != 'N/A':
                                        cross_ref += f"Contact: {contact_name}."
                                        break
                        break
                
                chunks.append({
                    "text": cross_ref,
                    "meta": {"type": "cross_reference", "event": event_name}
                })
        
        # 9. TEMPORAL CHUNKS - Organize by date
        events_by_date = {}
        for _, s in self.details.iterrows():
            date = self.val(s, 'date')
            event = self.val(s, 'event_name')
            time = self.val(s, 'start_time')
            if date != 'N/A' and event != 'N/A':
                events_by_date.setdefault(date, []).append(f"{event} ({time})")
        
        for date, events in events_by_date.items():
            date_schedule = f"Events happening on {date}: " + ", ".join(events)
            chunks.append({
                "text": date_schedule,
                "meta": {"type": "temporal_schedule", "date": date, "event_count": len(events)}
            })
        
        # 10. EVENT TYPE RELATIONSHIPS - "Similar events"
        for etype, events in events_by_type.items():
            if len(events) > 1:
                relationship = f"If you're interested in {etype}s, check out: " + ", ".join(events) + ". All are organized as part of Aurora Fest technical track."
                chunks.append({
                    "text": relationship,
                    "meta": {"type": "event_relationships", "event_type": etype}
                })
        
        # 11. CLUB-BASED EVENT GROUPING
        events_by_club = {}
        for _, e in self.events.iterrows():
            club = self.val(e, 'club_name')
            event = self.val(e, 'event_name')
            if club != 'N/A' and event != 'N/A':
                events_by_club.setdefault(club, []).append(event)
        
        for club, events in events_by_club.items():
            if len(events) > 1:
                club_chunk = f"{club} is hosting multiple events at Aurora Fest: " + ", ".join(events)
                chunks.append({
                    "text": club_chunk,
                    "meta": {"type": "club_events", "club": club, "count": len(events)}
                })
        
        # 12. MULTI-DAY EVENT TRACKING
        for _, e in self.events.iterrows():
            name = self.val(e, 'event_name')
            days = self.val(e, 'num_days')
            start = self.val(e, 'start_date')
            end = self.val(e, 'end_date')
            
            if name != 'N/A' and days != 'N/A':
                try:
                    if int(days) > 1:
                        multi_day = f"{name} is a multi-day event spanning {days} days from {start} to {end}. Plan accordingly to attend all sessions!"
                        chunks.append({
                            "text": multi_day,
                            "meta": {"type": "multi_day_event", "event": name, "days": days}
                        })
                except:
                    pass
        
        # 13. DIFFICULTY/PREREQUISITE SUMMARIES
        beginner_events = []
        advanced_events = []
        for _, s in self.details.iterrows():
            event = self.val(s, 'event_name')
            prereq = self.val(s, 'preferred_knowledge', '').lower()
            if event != 'N/A' and prereq:
                if 'basic' in prereq or 'none' in prereq or 'beginner' in prereq:
                    beginner_events.append(event)
                elif 'advanced' in prereq or 'intermediate' in prereq or prereq != 'n/a':
                    advanced_events.append(event)
        
        if beginner_events:
            beginner_summary = "Beginner-friendly events (no prior experience needed): " + ", ".join(set(beginner_events))
            chunks.append({
                "text": beginner_summary,
                "meta": {"type": "difficulty_beginner", "count": len(set(beginner_events))}
            })
        
        if advanced_events:
            advanced_summary = "Events requiring prior knowledge: " + ", ".join(set(advanced_events))
            chunks.append({
                "text": advanced_summary,
                "meta": {"type": "difficulty_advanced", "count": len(set(advanced_events))}
            })
        
        # 14. CERTIFICATE OPPORTUNITIES
        cert_events = []
        for _, e in self.events.iterrows():
            name = self.val(e, 'event_name')
            cert =self.val(e, 'certificate_offered')
            if name != 'N/A' and cert.lower() == 'yes':
                cert_events.append(name)
        
        if cert_events:
            cert_summary = "Get certificates by participating in: " + ", ".join(cert_events)
            chunks.append({
                "text": cert_summary,
                "meta": {"type": "certificate_opportunities", "count": len(cert_events)}
            })
        
        # 15. PRIORITY EVENT HIGHLIGHTS
        high_priority = []
        for _, e in self.events.iterrows():
            name = self.val(e, 'event_name')
            priority = self.val(e, 'priority')
            if name != 'N/A' and priority.lower() == 'high':
                high_priority.append(name)
        
        if high_priority:
            priority_summary = "Don't miss these HIGH PRIORITY events: " + ", ".join(high_priority)
            chunks.append({
                "text": priority_summary,
                "meta": {"type": "priority_highlights", "count": len(high_priority)}
            })
        
        # 16. VENUE CAPACITY PLANNING
        large_venues = []
        for _, v in self.venues.iterrows():
            name = self.val(v, 'venue_name')
            capacity = self.val(v, 'capacity', '')
            if name != 'N/A' and capacity != 'N/A':
                try:
                    if int(capacity) >= 100:
                        large_venues.append(f"{name} ({capacity} capacity)")
                except:
                    pass
        
        if large_venues:
            capacity_info = "Large venues for major events: " + ", ".join(large_venues)
            chunks.append({
                "text": capacity_info,
                "meta": {"type": "venue_capacity_planning"}
            })
        
        logger.info(f"Generated {len(chunks)} optimized chunks from Google Sheets")
        logger.info(f"Chunk distribution: Events={len([c for c in chunks if 'event' in c['meta'].get('type', '')])}, "
                   f"Schedules={len([c for c in chunks if 'schedule' in c['meta'].get('type', '')])}, "
                   f"FAQs={len([c for c in chunks if 'faq' in c['meta'].get('type', '')])}, "
                   f"Venues={len([c for c in chunks if 'venue' in c['meta'].get('type', '')])}, "
                   f"Contacts={len([c for c in chunks if 'contact' in c['meta'].get('type', '')])}, "
                   f"Campus={len([c for c in chunks if 'campus' in c['meta'].get('type', '')])}, "
                   f"Cross-refs={len([c for c in chunks if 'cross' in c['meta'].get('type', '') or 'temporal' in c['meta'].get('type', '') or 'relationship' in c['meta'].get('type', '')])}, "
                   f"Flags={len([c for c in chunks if 'flag' in c['meta'].get('type', '')])}")
        
        
        return chunks
    
    def _chunks_from_flat_structure(self) -> List[Dict]:
        """PRODUCTION CHUNKING - New flattened single-sheet structure"""
        chunks = []
        
        # Group by event_name to handle multi-day events
        events_grouped = self.events_flat.groupby('event_name')
        event_list = []
        events_by_type = {}
        
        for event_name, event_days in events_grouped:
            # Get first row for event-level info
            first_day = event_days.iloc[0]
            club = self.val(first_day, 'club_name')
            etype = self.val(first_day, 'event_type')
            start_date = self.val(first_day, 'start_date')
            end_date = self.val(first_day, 'end_date')
            num_days = self.val(first_day, 'num_days')
            reg_req = self.val(first_day, 'registration_required')
            cert = self.val(first_day, 'certificate_offered')
            project_desc = self.val(first_day, 'project_description')
            contact_name = self.val(first_day, 'contact_name')
            contact_email = self.val(first_day, 'contact_email')
            contact_phone = self.val(first_day, 'contact_phone')
            
            event_list.append(event_name)
            events_by_type.setdefault(etype, []).append(event_name)
            
            # CHUNK 1: Comprehensive Overview with ALL key information
            # Get ALL unique topics and prerequisites across all days
            all_topics = []
            all_prereqs = []
            for _, day_row in event_days.iterrows():
                topics = self.val(day_row, 'topics_covered', '')
                prereqs = self.val(day_row, 'prerequisites', '')
                if topics and topics != 'N/A':
                    all_topics.append(topics)
                if prereqs and prereqs != 'N/A':
                    all_prereqs.append(prereqs)
            
            # Combine unique topics and prereqs
            topics_text = ", ".join(set(all_topics)) if all_topics else "N/A"
            prereqs_text = ", ".join(set(all_prereqs)) if all_prereqs else "N/A"
            
            overview = f"""Event: {event_name}
Type: {etype}
Organized by: {club}
Duration: {start_date} to {end_date} ({num_days} days)
Topics Covered: {topics_text}
Prerequisites: {prereqs_text}
Registration: {reg_req}
Certificate: {cert}
Project: {project_desc}
Contact: {contact_name} ({contact_email}, {contact_phone})"""
            
            if "CONVenient" in event_name:
                logger.info(f"DEBUG: CONVenient Chunk Content:\n{overview}")
                
            chunks.append({
                "text": overview,
                "meta": {"type": "event_detailed", "event": event_name, "event_type": etype, "is_latest": True}
            })
            
            # CHUNK 2: Day-specific sessions
            for idx, day_row in event_days.iterrows():
                day_num = self.val(day_row, 'day_num')
                start_time = self.val(day_row, 'start_time')
                end_time = self.val(day_row, 'end_time')
                venue = self.val(day_row, 'venue')
                topics = self.val(day_row, 'topics_covered')
                prereqs = self.val(day_row, 'prerequisites')
                
                session = f"""{event_name} - Day {day_num}
Time: {start_time} to {end_time}
Venue: {venue}
Topics: {topics}
Prerequisites: {prereqs}"""
                chunks.append({
                    "text": session,
                    "meta": {"type": "schedule_detailed", "event": event_name, "day": day_num, "is_latest": True}
                })
                
                # Prerequisites chunk
                if prereqs != 'N/A':
                    chunks.append({
                        "text": f"For {event_name}, you need: {prereqs}",
                        "meta": {"type": "schedule_prerequisites", "event": event_name, "is_latest": True}
                    })
                
                # Topics/Learning outcomes chunk
                if topics != 'N/A':
                    chunks.append({
                        "text": f"In {event_name}, you'll learn: {topics}",
                        "meta": {"type": "schedule_outcomes", "event": event_name, "is_latest": True}
                    })
            
            # CHUNK 3: Contact info
            if contact_name != 'N/A':
                chunks.append({
                    "text": f"For {event_name}, contact {contact_name} at {contact_email} or {contact_phone}",
                    "meta": {"type": "contact_quick", "event": event_name, "name": contact_name, "is_latest": True}
                })
            
            # CHUNK 4: Project description
            if project_desc != 'N/A':
                chunks.append({
                    "text": f"{event_name}: {project_desc}",
                    "meta": {"type": "event_project", "event": event_name, "is_latest": True}
                })
        
        # Event list summary
        if event_list:
            chunks.append({
                "text": "All events at Aurora Fest: " + ", ".join(event_list),
                "meta": {"type": "event_list_master", "count": len(event_list), "is_latest": True}
            })
        
        # Events by type
        for etype, events in events_by_type.items():
            chunks.append({
                "text": f"{etype}s at Aurora Fest: " + ", ".join(events),
                "meta": {"type": "events_by_type", "event_type": etype, "is_latest": True}
            })
        
        # FAQs (if present)
        if hasattr(self, 'faqs') and not self.faqs.empty:
            for _, f in self.faqs.iterrows():
                q = self.val(f, 'question')
                a = self.val(f, 'answer')
                cat = self.val(f, 'category', 'General')
                if q != 'N/A' and a != 'N/A':
                    chunks.append({
                        "text": f"Q: {q}\nA: {a}",
                        "meta": {"type": "faq_standard", "category": cat, "is_latest": True}
                    })
        
        
        # ═══════════════════════════════════════════════════════════════
        # FUTURE-PROOF: Dynamic column auto-detection
        # Handles ANY new columns added to Google Sheets automatically
        # ═══════════════════════════════════════════════════════════════
        
        all_columns = list(self.events_flat.columns)
        processed_columns = {
            'event_name', 'club_name', 'event_type', 'start_date', 'end_date', 
            'num_days', 'registration_required', 'certificate_offered', 
            'day_num', 'start_time', 'end_time', 'venue', 
            'contact_name', 'contact_email', 'contact_phone',
            'topics_covered', 'prerequisites', 'project_description'
        }
        
        new_columns = [col for col in all_columns if col not in processed_columns]
        
        if new_columns:
            logger.info(f"Auto-chunking NEW columns: {new_columns}")
            for _, row in self.events_flat.iterrows():
                event = self.val(row, 'event_name')
                for new_col in new_columns:
                    val = self.val(row, new_col, '')
                    if val and val != 'N/A' and len(str(val).strip()) > 2:
                        chunks.append({
                            "text": f"{event} - {new_col.replace('_', ' ')}: {val}",
                            "meta": {"type": f"auto_{new_col}", "event": event, "is_latest": True}
                        })
        
        logger.info(f"Generated {len(chunks)} chunks (with auto-column-detection)")
        return chunks


# ═══════════════════════════════════════════════════════════════════════════
# VECTOR SEARCH ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class VectorSearch:
    """ChromaDB-based vector search with live updates"""
    
    def __init__(self, chunks: List[Dict]):
        CHROMA_PATH.mkdir(exist_ok=True)
        
        self.embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        
        self.db = chromadb.PersistentClient(path=str(CHROMA_PATH))
        
        # Initialize with Blue/Green deployment strategy
        # Start fresh or load latest version
        self.active_collection_name = f"Aurora_v_{int(time.time())}"
        self.collection = self.db.get_or_create_collection(
            name=self.active_collection_name,
            embedding_function=self.embedding,
            metadata={"hnsw:space": "cosine"}
        )
        
        # Load initial data
        self._load_chunks(self.collection, chunks)
        
        # Clean up old collections on startup
        self._cleanup_old_collections()
    
    def _load_chunks(self, collection, chunks: List[Dict]):
        """Load or update chunks into a specific collection"""
        # Optimized batch loading
        if not chunks:
            return
            
        logger.info(f"DEBUG: Loading {len(chunks)} chunks into {collection.name}")
        
        # Prepare batches
        ids = []
        docs = []
        metas = []
        
        for i, chunk in enumerate(chunks):
            # Using stable ID generation
            chunk_hash = hashlib.md5(chunk["text"].encode()).hexdigest()
            doc_id = f"{chunk['meta'].get('type', 'gen')}_{i}_{chunk_hash[:8]}"
            
            ids.append(doc_id)
            docs.append(chunk["text"])
            metas.append(chunk["meta"])
        
        # Upsert in one go (Chroma handles batching internally mostly, or we can chunk if huge)
        if ids:
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            logger.info(f"✅ Loaded {len(ids)} documents into {collection.name}")
    
    def _cleanup_old_collections(self, keep: int = 2):
        """Keep only the latest N collections to save space"""
        try:
            collections = self.db.list_collections()
            aurora_cols = [c for c in collections if c.name.startswith("Aurora_v_")]
            
            # Sort by timestamp (DESC)
            aurora_cols.sort(key=lambda c: int(c.name.split("_v_")[1]) if "_v_" in c.name else 0, reverse=True)
            
            # Delete older than 'keep'
            for col in aurora_cols[keep:]:
                logger.info(f"🗑️ Deleting old collection: {col.name}")
                self.db.delete_collection(col.name)
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")

    def update(self, new_chunks: List[Dict]):
        """Zero-downtime update using Blue/Green deployment"""
        try:
            # 1. Create NEW collection (Green)
            new_version = f"Aurora_v_{int(time.time())}"
            logger.info(f"🔄 Starting zero-downtime update -> {new_version}")
            
            new_collection = self.db.create_collection(
                name=new_version,
                embedding_function=self.embedding,
                metadata={"hnsw:space": "cosine"}
            )
            
            # 2. Load data into NEW collection
            self._load_chunks(new_collection, new_chunks)
            
            # 3. Validation (safe update check)
            new_count = new_collection.count()
            old_count = self.collection.count() if self.collection else 0
            
            if new_count == 0 and len(new_chunks) > 0:
                logger.error("❌ Update failed: New collection is empty! Aborting swap.")
                self.db.delete_collection(new_version)
                return

            if old_count > 0 and new_count < (old_count * 0.8):
                logger.error(f"❌ Update unsafe: New count ({new_count}) is < 80% of old ({old_count}). Aborting.")
                self.db.delete_collection(new_version)
                return
            
            # 4. Atomic Swap (Blue -> Green)
            old_name = self.active_collection_name
            self.collection = new_collection
            self.active_collection_name = new_version
            logger.info(f"✅ Swapped active collection: {old_name} -> {new_version} (Docs: {new_count})")
            
            # 5. Cleanup old versions
            self._cleanup_old_collections()
            
        except Exception as e:
            logger.error(f"Error updating vector store: {e}")
    
    
    def search(self, query: str, k: int = TOP_K_RESULTS, threshold: float = SIMILARITY_THRESHOLD, filters: Dict = None):
        """
        Hybrid search: keyword matching for event names + semantic search
        ARGS:
            query: User question
            k: Number of results
            threshold: Similarity cutoff
            filters: ChromaDB where clause for intent-based filtering (e.g. {'type': {'$in': [...]}})
        """
        try:
            # HYBRID SEARCH: Check if query mentions specific event names
            # Get list of all known event names from metadata
            all_results = self.collection.get()
            event_names = set()
            if all_results and all_results.get("metadatas"):
                for meta in all_results["metadatas"]:
                    if meta and "event" in meta:
                        event_names.add(meta["event"].lower())
            
            # Check if query contains any event name (case-insensitive)
            query_lower = query.lower()
            matched_events = [e for e in event_names if e in query_lower]
            logger.info(f"DEBUG: Search query='{query}', Matched events={matched_events}")
            
            retrieved = []
            forced_ids = set()
            
            # FORCE FETCH: If event matches, get the detailed overview chunk directly (Deterministic)
            for event in matched_events:
                # Find the actual event name case from metadata (matched_events are lowercase)
                # We need to scan event_names again or rely on lowercase match?
                # Chroma filter is case sensitive? Usually.
                # Let's try to match case insensitive by getting all 'event_detailed' and filtering
                try:
                    # Get all detailed chunks (small subset)
                    detailed_chunks = self.collection.get(where={"type": "event_detailed"})
                    if detailed_chunks and detailed_chunks.get("documents"):
                        for j, meta in enumerate(detailed_chunks["metadatas"]):
                            if meta.get("event", "").lower() == event:
                                # Found match! Add to retrieved
                                doc_id = detailed_chunks["ids"][j]
                                if doc_id not in forced_ids:
                                    logger.info(f"DEBUG: Force adding detailed chunk for {event}")
                                    retrieved.append({
                                        "text": detailed_chunks["documents"][j],
                                        "score": 2.0, # Maximum priority
                                        "distance": 0.0,
                                        "id": doc_id,
                                        "meta": meta
                                    })
                                    forced_ids.add(doc_id)
                except Exception as e:
                    logger.error(f"Error in force fetch: {e}")
            
            # If event name is mentioned, boost those chunks
            # Apply filters if provided
            if filters:
                logger.info(f"DEBUG: Applying intent filters: {filters}")
                results = self.collection.query(
                    query_texts=[query], 
                    n_results=k * 2,
                    where=filters
                )
            else:
                results = self.collection.query(query_texts=[query], n_results=k * 2)
            
            if results["documents"]:
                # logger.debug(f"Raw results count: {len(results['documents'][0])}")
                for i, doc in enumerate(results["documents"][0]):
                    distance = results["distances"][0][i]
                    metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                    doc_id = results["ids"][0][i] if results["ids"] else f"doc_{i}"
                    
                    # Convert distance to similarity
                    similarity = max(0.0, 1.0 - (distance / 2.0))
                    
                    # BOOST: If this chunk is for a mentioned event, lower the threshold AND boost score
                    is_relevant_event = False
                    score_boost = 0.0
                    
                    if metadata and "event" in metadata:
                        event_in_chunk = metadata["event"].lower()
                        if any(matched in event_in_chunk or event_in_chunk in matched for matched in matched_events):
                            is_relevant_event = True
                            # Major boost for detailed overview of the matched event
                            if metadata.get("type") == "event_detailed":
                                score_boost = 0.5
                            else:
                                score_boost = 0.2
                    
                    # Use lower threshold for matched events, normal threshold otherwise
                    effective_threshold = 0.0 if is_relevant_event else threshold
                    
                    # Apply boost to similarity
                    final_score = similarity + score_boost
                    
                    logger.info(f"DEBUG: Doc {i} Sim={similarity:.4f} Boost={score_boost} Final={final_score:.4f} Event={metadata.get('event')}")
                    
                    if final_score >= effective_threshold:
                        retrieved.append({
                            "text": doc,
                            "score": final_score,
                            "distance": distance,
                            "id": doc_id,
                            "meta": metadata
                        })
            
            logger.info(f"DEBUG: Final retrieved count: {len(retrieved)}")
            # Sort by similarity (highest first) and return top k
            
            # Sort by similarity (highest first) and return top k
            retrieved.sort(key=lambda x: x["score"], reverse=True)
            return retrieved[:k]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

# ═══════════════════════════════════════════════════════════════════════════
# LLM HANDLER
# ═══════════════════════════════════════════════════════════════════════════

class SmartLLM:
    """Groq LLM with automatic API key failover for production reliability"""
    
    def __init__(self, api_key: str, fallback_keys: List[str] = None):
        # Primary API key
        self.api_keys = [api_key]
        
        # Add fallback keys if provided
        if fallback_keys:
            self.api_keys.extend([k.strip() for k in fallback_keys if k.strip()])
        
        self.current_key_index = 0
        self.client = Groq(api_key=self.api_keys[self.current_key_index])
        
        # Track usage per API key
        self.key_usage_count = {i: 0 for i in range(len(self.api_keys))}
        self.key_rotation_count = 0
        self.total_requests = 0
        
        logger.info(f"LLM initialized with {len(self.api_keys)} API key(s) (1 primary + {len(self.api_keys)-1} fallback)")
    
    def _rotate_api_key(self):
        """Rotate to next available API key"""
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self.client = Groq(api_key=self.api_keys[self.current_key_index])
        self.key_rotation_count += 1
        logger.warning(f"Rotated to API key #{self.current_key_index + 1}/{len(self.api_keys)} (Total rotations: {self.key_rotation_count})")
    
    
    def get_usage_stats(self) -> Dict:
        """Get API key usage statistics"""
        return {
            "total_keys": len(self.api_keys),
            "current_key_index": self.current_key_index + 1,
            "total_requests": self.total_requests,
            "key_rotations": self.key_rotation_count,
            "usage_per_key": [
                {
                    "key_number": i + 1,
                    "requests": self.key_usage_count[i],
                    "percentage": round((self.key_usage_count[i] / self.total_requests * 100) if self.total_requests > 0 else 0, 1),
                    "is_current": i == self.current_key_index
                }
                for i in range(len(self.api_keys))
            ]
        }
    
    def answer(self, query: str, chunks: List[Dict], intent: str = "general", history: List[tuple] = None) -> Dict:
        """Generate answer from context with confidence scoring and conversation history"""
        # Check if we have relevant context
        if not chunks:
            return {
                "answer": "I don't have specific information about that. Could you rephrase your question or ask about event schedules, venues, or registration?",
                "confidence": 0.0,
                "response_type": "no_information",
                "used_docs": []
            }
        
        # Calculate confidence based on top similarity score
        top_score = chunks[0].get('score', 0.0)  # Already converted similarity (0-1)
        confidence = top_score  # No conversion needed - score is already similarity
        
        # Low confidence gate - adjusted for new scale
        if confidence < 0.15:  # Lowered from 0.3 since our scale is more permissive
            return {
                "answer": "I found some information, but I'm not confident it fully answers your question. Could you please rephrase or provide more details?",
                "confidence": confidence,
                "response_type": "low_confidence",
                "used_docs": [c.get('id', 'unknown') for c in chunks[:1]]
            }
        
        # Use more chunks for list queries
        num_chunks = 5 if any(word in query.lower() for word in ['all', 'list', 'events', 'what are']) else 3
        context = "\n".join([f"- {c['text']}" for c in chunks[:num_chunks]])
        used_doc_ids = [c.get('id', 'unknown') for c in chunks[:num_chunks]]
        
        # Build conversation history context (last 3 exchanges)
        history_context = ""
        if history and len(history) > 0:
            recent_history = history[-3:]  # Last 3 exchanges
            history_lines = []
            for i, (prev_q, prev_a) in enumerate(recent_history, 1):
                history_lines.append(f"User: {prev_q}")
                history_lines.append(f"Assistant: {prev_a[:150]}...")  # Truncate long answers
            history_context = "\n".join(history_lines)
        
        try:
            # FAANG-GRADE: Strict Deterministic Mode
            # If enabled, valid ONLY context-based answers (no hallucinations)
            strict_mode = os.getenv("STRICT_MODE", "True").lower() == "true"
            
            system_instruction = ""
            if strict_mode:
                system_instruction = """
- STRICT MODE ENABLED: Answer ONLY using the provided Context Information.
- Do NOT use outside knowledge or hallucinate facts.
- If the exact answer is not in the context, say 'I don't have that information in my knowledge base'.
- Do not make up dates, times, or venues.
"""
            
            prompt = f"""You are Aurora Fest Assistant, a helpful chatbot for ISTE's Aurora college fest.

{"Conversation History (for context):" if history_context else ""}
{history_context}

{"Current Query Context Information:" if history_context else "Context Information:"}
{context}

User Question: {query}

Instructions:
{system_instruction}
- You can answer from TWO sources: the Context Information above AND the Conversation History
- If the user asks about something they mentioned earlier (like their name), use the Conversation History
- For questions about Aurora Fest events, use the Context Information
- IMPORTANT: Make semantic connections - if user asks about broad topics, look for related specific terms in the context:
  • "AI/ML" or "Machine Learning" → Look for events with Neural Networks, CNNs, Computer Vision, Deep Learning
  • "Cybersecurity" → Look for events with Cryptography, Security, Hacking, Exploitation
  • "Hardware" or "Electronics" → Look for events with Circuits, PCB, Embedded Systems, Microcontrollers
  • "Design" or "UI/UX" → Look for events with Wireframes, Prototypes, Interface Design
- Be concise, friendly, and enthusiastic about Aurora Fest!
- If asked to list events, present them in a clean bulleted format
- Include specific details like dates, times, venues, organizers when available
- If neither context nor history has the answer, say you don't have that information

Answer:"""
            
            # PRODUCTION: Automatic API key failover on rate limits
            max_retries = len(self.api_keys)
            last_error = None
            
            # Use deterministic temperature in strict mode
            temperature = 0.0 if strict_mode else 0.3
            
            for attempt in range(max_retries):
                try:
                    response = self.client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=temperature,
                        max_tokens=400,
                        timeout=LLM_TIMEOUT_SECONDS
                    )
                    
                    # Track successful request
                    self.total_requests += 1
                    self.key_usage_count[self.current_key_index] += 1

                    answer = response.choices[0].message.content.strip()
                    
                    return {
                        "answer": answer,
                        "confidence": confidence,
                        "response_type": "grounded_answer",
                        "used_docs": used_doc_ids
                    }
                
                except Exception as e:
                    last_error = e
                    error_msg = str(e).lower()
                    
                    # Check if rate limit - rotate to next key
                    if ('rate' in error_msg or 'limit' in error_msg or 'quota' in error_msg) and attempt < max_retries - 1:
                        logger.warning(f"Rate limit on key #{self.current_key_index + 1}, rotating...")
                        self._rotate_api_key()
                        continue  # Retry
                    else:
                        break  # Other error or no more keys
            
            # All keys failed
            logger.error(f"All {max_retries} API keys failed. Last error: {last_error}")
            
            # Production-grade error handling with user-friendly messages
            error_msg = str(e).lower()
            if 'rate' in error_msg or 'limit' in error_msg or 'quota' in error_msg:
                user_message = "🌟 Aurora Fest Assistant is experiencing high traffic right now! Please try again in a moment. We're here to help! ✨"
            else:
                user_message = "I'm having a brief issue connecting to my knowledge base. Please try asking your question again! "
            
            return {
                "answer": user_message,
                "confidence": 0.0,
                "response_type": "system_error",
                "used_docs": []
            }
        
        except Exception as outer_error:
            logger.error(f"Unexpected error: {outer_error}")
            return {
                "answer": "I encountered an unexpected error. Please try again!",
                "confidence": 0.0,
                "response_type": "system_error",
                "used_docs": []
            }

# ═══════════════════════════════════════════════════════════════════════════
# FASTAPI APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Aurora Fest RAG Chatbot",
    description="Production-grade RAG chatbot with Google Sheets integration",
    version="2.0.0"
)

# CORS Configuration - PRODUCTION SECURE
# Get allowed origins from environment or use defaults
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # Restricted to specific domains
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # Only allow necessary methods
    allow_headers=["Content-Type", "Authorization"],  # Specific headers only
)

# HTTP Basic Authentication for Dashboard
security = HTTPBasic()

# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses"""
    response = await call_next(request)
    
    # Prevent content type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    
    # Enable XSS protection
    response.headers["X-XSS-Protection"] = "1; mode=block"
    
    # Force HTTPS in production (HSTS)
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    
    # Content Security Policy
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:;"
    
    return response

# Rate Limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Global objects
searcher: Optional[VectorSearch] = None
llm: Optional[SmartLLM] = None
conversation_handler = ConversationalHandler()
start_time = datetime.now()

# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND SYNC
# ═══════════════════════════════════════════════════════════════════════════

async def refresh_knowledge_base():
    """Background task to sync from Google Sheets"""
    global last_sync_time, searcher
    
    try:
        async with sync_lock:
            logger.info("Starting Google Sheets sync...")
            
            chunker = GoogleSheetsChunker(GOOGLE_SHEETS_ID, GOOGLE_CREDS_FILE)
            new_chunks = chunker.chunks()
            
            if searcher:
                searcher.update(new_chunks)
            
            last_sync_time = datetime.now()
            logger.info(f"Sync completed at {last_sync_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    except Exception as e:
        logger.error(f"Sync failed: {e}")

def start_background_sync():
    """Start the background scheduler"""
    if not AUTO_SYNC:
        logger.info("Auto-sync disabled")
        return
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: asyncio.run(asyncio.wait_for(refresh_knowledge_base(), timeout=SYNC_TIMEOUT_SECONDS)),
        'interval',
        minutes=SYNC_INTERVAL,
        id='google_sheets_sync'
    )
    scheduler.start()
    logger.info(f"Background sync started (every {SYNC_INTERVAL} minutes)")

# ═══════════════════════════════════════════════════════════════════════════
# STATIC FILE SERVING
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the main chat interface"""
    html_file = BASE_DIR / "chat.html"
    if not html_file.exists():
        return HTMLResponse(
            content=f"Error: chat.html not found in {BASE_DIR}",
            status_code=404
        )
    with open(html_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/iste_manipal_cover.jpeg")
async def serve_banner():
    """Serve banner image"""
    file_path = BASE_DIR / "iste_manipal_cover.jpeg"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Banner image not found")
    return FileResponse(file_path)

@app.get("/1630568350176.jpeg")
async def serve_logo():
    """Serve logo image"""
    file_path = BASE_DIR / "1630568350176.jpeg"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Logo image not found")
    return FileResponse(file_path)

@app.get("/login-page")
async def serve_login_page():
    """Serve custom login page"""
    html_file = BASE_DIR / "login.html"
    if not html_file.exists():
        return HTMLResponse(
            content="Error: login.html not found",
            status_code=404
        )
    with open(html_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate user and return session token"""
    # Verify credentials
    correct_username = os.getenv("DASHBOARD_USERNAME", "admin")
    correct_password = os.getenv("DASHBOARD_PASSWORD", "aurora2025")
    
    # Constant-time comparison
    is_correct_username = secrets.compare_digest(request.username, correct_username)
    is_correct_password = secrets.compare_digest(request.password, correct_password)
    
    if not (is_correct_username and is_correct_password):
        logger.warning(f"Failed login attempt for username: {request.username}")
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )
    
    # Generate session token
    token = secrets.token_urlsafe(32)
    active_sessions[token] = {
        "username": request.username,
        "created_at": datetime.now()
    }
    
    logger.info(f"Successful login: {request.username}")
    
    return LoginResponse(
        token=token,
        message="Login successful"
    )

def verify_session_token(token: str) -> bool:
    """Verify if session token is valid and not expired"""
    if token not in active_sessions:
        return False
    
    session = active_sessions[token]
    # Check if session is expired (24 hours)
    if (datetime.now() - session["created_at"]).total_seconds() > SESSION_TIMEOUT_HOURS * 3600:
        del active_sessions[token]
        return False
    
    return True

@app.get("/dashboard")
async def serve_analytics_dashboard(request: Request):
    """Serve analytics dashboard with token-based authentication"""
    authenticated = False
    username = None
    
    # Check for token in Authorization header (Bearer token)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
        if verify_session_token(token):
            authenticated = True
            username = active_sessions[token]["username"]
    
    # Check for token in query parameter (from localStorage)
    if not authenticated:
        token_param = request.query_params.get("token")
        if token_param and verify_session_token(token_param):
            authenticated = True
            username = active_sessions[token_param]["username"]
    
    # If not authenticated, redirect to login page
    if not authenticated:
        # Use JavaScript redirect for better UX
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
                <head>
                    <title>Redirecting...</title>
                    <script>
                        window.location.href = '/login-page';
                    </script>
                </head>
                <body>
                    <p>Redirecting to login page...</p>
                </body>
            </html>
            """,
            status_code=200
        )
    
    logger.info(f"Dashboard accessed by: {username}")
    
    html_file = BASE_DIR / "analytics.html"
    if not html_file.exists():
        return HTMLResponse(
            content=f"Error: analytics.html not found in {BASE_DIR}",
            status_code=404
        )
    with open(html_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

# ═══════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    uptime = (datetime.now() - start_time).total_seconds()
    
    doc_count = 0
    if searcher:
        try:
            doc_count = searcher.collection.count()
        except:
            pass
    
    return HealthResponse(
        status="healthy" if searcher else "initializing",
        last_sync=last_sync_time.isoformat() if last_sync_time else None,
        vector_db_count=doc_count,
        uptime_seconds=uptime,
        auto_sync_enabled=AUTO_SYNC
    )

@app.get("/api-stats")
async def api_key_stats():
    """Get API key usage statistics"""
    if llm:
        stats = llm.get_usage_stats()
        return {
            "status": "ok",
            "api_keys": stats
        }
    return {"status": "not_initialized", "api_keys": None}

@app.post("/refresh")
async def manual_refresh(request: Request):
    """Manual refresh endpoint"""
    await refresh_knowledge_base()
    return JSONResponse({
        "status": "success",
        "message": "Knowledge base refreshed",
        "timestamp": datetime.now().isoformat()
    })

def moderate_content(query: str) -> tuple[bool, str]:
    """
    Moderate user input to prevent abuse and inappropriate content.
    Returns: (is_valid, reason_if_invalid)
    """
    query_lower = query.lower().strip()
    
    # Check minimum length
    if len(query) < 2:
        return False, "Query too short"
    
    # Check maximum length
    if len(query) > 500:
        return False, "Query too long (max 500 characters)"
    
    # Blocked patterns - inappropriate content
    blocked_patterns = [
        # Strong profanity only (removed mild words: damn, hell, crap, ass)
        r'\b(fuck|shit|bitch|bastard|asshole)\b',
        # Spam patterns
        r'(.)\1{10,}',  # Repeated characters (aaaaaaaaaaa)
        r'\b(test){5,}\b',  # Repeated words
        # Attempts to break system
        r'(ignore|bypass|override|hack|break|crash)\s+(prompt|instruction|rule|system)',
        r'(you\s+are|act\s+as|pretend|roleplay)\s+(not|now)',
        # SQL injection attempts
        r'(drop|delete|insert|update)\s+(table|database)',
        # Script injection
        r'<script|javascript:|onerror=',
    ]
    
    for pattern in blocked_patterns:
        if re.search(pattern, query_lower, re.IGNORECASE):
            logger.warning(f"Content moderation blocked query: {query[:50]}...")
            return False, "Inappropriate content detected"
    
    # Check for excessive special characters (likely spam)
    special_char_count = sum(1 for c in query if not c.isalnum() and not c.isspace())
    if special_char_count > len(query) * 0.5:  # More than 50% special chars
        return False, "Invalid input format"
    
    return True, ""

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(request: Request, req: ChatRequest):
    """Main chat endpoint"""
@app.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def serve_chat(request: Request, req: ChatRequest):
    """
    Main chat endpoint with strict RAG pipeline
    """
    # Observability: Generate request ID
    request_id = str(uuid.uuid4())
    logger.info(f"Received chat request [{request_id}] from {get_remote_address(request)}")
    
    start = time.time()
    
    # Content moderation
    is_valid, reason = moderate_content(req.query)
    if not is_valid:
        logger.warning(f"Request [{request_id}] blocked: {reason}")
        raise HTTPException(
            status_code=400,
            detail="I'm unable to process that message. Please keep your questions professional and related to Aurora Fest events. How can I help you with event information?"
        )
    
    if not searcher or not llm:
        raise HTTPException(status_code=503, detail="System initializing, please wait...")
    
    # Classify intent
    intent = conversation_handler.classify_intent(req.query)
    
    # Handle casual conversation
    if intent in ["greeting", "farewell", "gratitude"]:
        answer = conversation_handler.get_casual_response(intent)
        response_time = (time.time() - start) * 1000
        
        # Log interaction
        analytics_log.append({
            "timestamp": datetime.now().isoformat(),
            "query": req.query,
            "intent": intent,
            "response_time_ms": response_time,
            "request_id": request_id
        })
        
        return ChatResponse(
            answer=answer,
            confidence=1.0,
            tier="Conversational",
            response_time_ms=response_time,
            intent=intent,
            timestamp=datetime.now().isoformat()
        )
    
    # Handle question with RAG - PRODUCTION-GRADE with Conversation History + Response Caching
    try:
        # 0. Get user ID for session tracking
        user_id = hashlib.md5(str(get_remote_address(request)).encode()).hexdigest()[:16]
        
        # 0.5. Parse device information from User-Agent header
        try:
            user_agent_string = request.headers.get('user-agent', '')
            user_agent = parse_user_agent(user_agent_string)
            device_type = "Mobile" if user_agent.is_mobile else ("Tablet" if user_agent.is_tablet else ("Desktop" if user_agent.is_pc else "Unknown"))
            browser = f"{user_agent.browser.family} {user_agent.browser.version_string}"
            os = f"{user_agent.os.family} {user_agent.os.version_string}"
        except Exception as e:
            logger.warning(f"Failed to parse user agent: {e}")
            device_type, browser, os = "Unknown", "Unknown", "Unknown"
        
        # 1. Classify intent using production classifier
        rag_intent = IntentClassifier.classify(req.query)
        
        # 2. Check response cache (5-minute TTL)
        query_normalized = req.query.lower().strip().replace("?", "").replace("!", "")
        
        # FAANG-FIX: Cache key must depend on intent and threshold to ensure correctness
        # Old: cache_key = hashlib.md5(query_normalized.encode()).hexdigest()
        cache_key_str = f"{query_normalized}|{rag_intent}|{req.threshold}"
        cache_key = hashlib.md5(cache_key_str.encode()).hexdigest()
        cache_ttl = 300  # 5 minutes in seconds

        # FAANG-FIX: Memory leak protection - Cap conversation history size
        if len(conversation_history) > 10000:
             # Rudimentary LRU/cleanup: Clear if too big (Acceptable trade-off for simple dict)
             logger.warning("Conversation history exceeded limit. Clearing to prevent memory leak.")
             conversation_history.clear()
        
        current_time = time.time()
        
        # Clean old cache entries (older than 10 minutes)
        expired_keys = [k for k, v in response_cache.items() if current_time - v.get("timestamp", 0) > 600]
        for k in expired_keys:
            response_cache.pop(k, None)
        
        # Check if we have a fresh cached response
        if cache_key in response_cache:
            cached = response_cache[cache_key]
            if current_time - cached["timestamp"] < cache_ttl:
                logger.info(f"Cache HIT for: '{req.query[:50]}...'")
                response_time = (time.time() - start) * 1000
                
                # Still track in analytics
                analytics_log.append({
                    "timestamp": datetime.now().isoformat(),
                    "query": req.query,
                    "intent": cached["intent"],
                    "confidence": cached["confidence"],
                    "cached": True,
                    "response_time_ms": response_time,
                    "request_id": request_id
                })
                
                # Log cached interaction to SQLite
                if interaction_logger:
                    try:
                        user_id = hashlib.md5(str(get_remote_address(request)).encode()).hexdigest()[:16]
                        interaction_logger.log_interaction(
                            query=req.query,
                            answer=cached["answer"],
                            intent=cached["intent"],
                            retrieved_docs=[],
                            confidence=cached["confidence"],
                            response_type="cached_response",
                            used_docs=[],
                            response_time_ms=response_time,
                            user_id=user_id,
                            cached=True,
                            device_type=device_type,
                            browser=browser,
                            os=os,
                            interaction_id=request_id
                        )
                    except Exception as log_err:
                        logger.warning(f"Logging failed: {log_err}")
                
                return ChatResponse(
                    answer=cached["answer"],
                    confidence=cached["confidence"],
                    tier=cached["tier"],
                    response_time_ms=response_time,
                    intent=cached["intent"],
                    timestamp=datetime.now().isoformat()
                )
        
        # 3. Cache MISS - proceed with normal RAG flow
        logger.info(f"💾 Cache MISS for: '{req.query[:50]}...'")
        
        # 4. Get conversation history for this user (last 3 exchanges)
        user_history = conversation_history.get(user_id, [])
        
        # 4.5. Query expansion for better retrieval (expand abbreviations/domain terms)
        expanded_query = req.query
        query_lower = req.query.lower()
        
        # Expand common abbreviations and domain terms for better semantic matching
        # NOTE: Uses only generic terms, no specific event names (events change yearly)
        if any(term in query_lower for term in ['ai', 'ml', 'machine learning', 'artificial intelligence']):
            expanded_query = f"{req.query} neural networks CNN computer vision deep learning artificial intelligence"
        elif any(term in query_lower for term in ['cyber', 'security', 'hacking']):
            expanded_query = f"{req.query} cryptography security exploitation penetration hacking"
        elif any(term in query_lower for term in ['hardware', 'electronics', 'circuit']):
            expanded_query = f"{req.query} electronics circuits embedded systems microcontroller"
        elif any(term in query_lower for term in ['design', 'ui', 'ux', 'interface']):
            expanded_query = f"{req.query} wireframes prototypes interface user experience design"
        elif any(term in query_lower for term in ['web', 'frontend', 'backend', 'fullstack']):
            expanded_query = f"{req.query} development programming coding software web application"
        
        # 5. Retrieve relevant chunks (using expanded query for better matching)
        # Apply intent-based filtering if intent was detected
        filters = None
        if rag_intent and rag_intent != "general":
            filters = IntentClassifier.get_retrieval_filters(rag_intent)
            
        chunks = searcher.search(expanded_query, threshold=req.threshold, filters=filters)
        
        # PRODUCTION SAFETY: Fallback if no documents retrieved
        if not chunks or len(chunks) == 0:
            logger.warning(f"Zero documents retrieved for query: {req.query[:50]}...")
            
            # Return refusal message instead of hallucinating
            fallback_answer = "I don't have information about that in my knowledge base. Please contact the Aurora Fest organizers directly for this specific query, or try rephrasing your question."
            
            response_time = (time.time() - start) * 1000
            
            # Log the failed retrieval
            if interaction_logger:
                try:
                    interaction_logger.log_interaction(
                        query=req.query,
                        answer=fallback_answer,
                        intent=rag_intent,
                        retrieved_docs=[],
                        confidence=0.0,
                        response_type="no_retrieval",
                        used_docs=[],
                        response_time_ms=response_time,
                        user_id=user_id,
                        cached=False,
                        device_type=device_type,
                        browser=browser,
                        os=os
                    )
                except Exception as log_err:
                    logger.warning(f"Logging failed: {log_err}")
            
            return ChatResponse(
                answer=fallback_answer,
                confidence=0.0,
                tier="No Data",
                response_time_ms=response_time,
                intent=rag_intent,
                timestamp=datetime.now().isoformat()
            )
        
        # 4. Generate answer with confidence scoring AND conversation history
        llm_response = llm.answer(req.query, chunks, intent=rag_intent, history=user_history)
        
        answer = llm_response["answer"]
        confidence = llm_response["confidence"]
        response_type = llm_response["response_type"]
        used_docs = llm_response["used_docs"]
        
        tier = "High" if confidence > 0.75 else "Medium" if confidence > 0.5 else "Low"
        response_time = (time.time() - start) * 1000
        
        # 5. Update conversation history (keep last 5 exchanges per user)
        if user_id not in conversation_history:
            conversation_history[user_id] = []
        conversation_history[user_id].append((req.query, answer))
        # Keep only last 5 exchanges
        conversation_history[user_id] = conversation_history[user_id][-5:]
        
        # 6. Log interaction to SQLite (production observability)
        if interaction_logger:
            try:
                user_id = hashlib.md5(str(get_remote_address(request)).encode()).hexdigest()[:16]
                interaction_logger.log_interaction(
                    query=req.query,
                    answer=answer,
                    intent=rag_intent,
                    retrieved_docs=chunks,
                    confidence=confidence,
                    response_type=response_type,
                    used_docs=used_docs,
                    response_time_ms=response_time,
                    user_id=user_id,
                    cached=False,
                    device_type=device_type,
                    browser=browser,
                    os=os,
                    interaction_id=request_id
                )
            except Exception as log_err:
                logger.warning(f"Logging failed: {log_err}")
        
        # 5. Legacy analytics log (keep for backward compat)
        analytics_log.append({
            "timestamp": datetime.now().isoformat(),
            "query": req.query,
            "intent": rag_intent,
            "confidence": confidence,
            "chunks_found": len(chunks),
            "response_time_ms": response_time
        })
        
        # 6. Store response in cache (for future identical queries)
        response_cache[cache_key] = {
            "answer": answer,
            "confidence": confidence,
            "tier": tier,
            "intent": rag_intent,
            "timestamp": current_time
        }
        # logger.info(f"Cached response for: '{req.query[:50]}...'")
        
        return ChatResponse(
            answer=answer,
            confidence=confidence,
            tier=tier,
            response_time_ms=response_time,
            intent=rag_intent,
            timestamp=datetime.now().isoformat()
        )
    
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail="Error processing request")

@app.get("/analytics")
async def get_analytics():
    """Get comprehensive analytics from both sources"""
    # Calculate cache stats
    cache_hits = len([q for q in analytics_log if q.get("cached", False)])
    total_queries = len(analytics_log)
    cache_hit_rate = (cache_hits / total_queries * 100) if total_queries > 0 else 0
    
    stats = {
        "legacy_analytics": {
            "total_queries": total_queries,
            "recent_queries": analytics_log[-10:] if analytics_log else [],
            "avg_response_time": float(np.mean([q.get("response_time_ms", 0) for q in analytics_log])) if analytics_log else 0.0
        },
        "cache_stats": {
            "cache_size": len(response_cache),
            "cache_hits": cache_hits,
            "cache_hit_rate": round(cache_hit_rate, 2),
            "api_calls_saved": cache_hits
        }
    }
    
    # Add production SQLite stats if available
    if interaction_logger:
        try:
            stats["production_stats"] = interaction_logger.get_stats()
        except Exception as e:
            logger.warning(f"Could not fetch production stats: {e}")
            stats["production_stats"] = {}
    
    return JSONResponse(stats)

@app.get("/interactions/all")
async def get_all_interactions():
    """Get all interaction logs from SQLite database"""
    if not interaction_logger:
        return JSONResponse({
            "interactions": [],
            "total": 0,
            "message": "Interaction logger not initialized"
        })
    
    try:
        conn = sqlite3.connect(interaction_logger.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                interaction_id,
                timestamp,
                user_id,
                query_text,
                detected_intent,
                answer,
                confidence_score,
                response_type,
                response_time_ms,
                cached,
                device_type,
                browser,
                os,
                created_at
            FROM interactions
            ORDER BY created_at DESC
        ''')
        
        rows = cursor.fetchall()
        interactions = [dict(row) for row in rows]
        conn.close()
        
        return JSONResponse({
            "interactions": interactions,
            "total": len(interactions)
        })
    except Exception as e:
        logger.error(f"Error fetching interactions: {e}")
        return JSONResponse({
            "interactions": [],
            "total": 0,
            "error": str(e)
        })

# ═══════════════════════════════════════════════════════════════════════════
# STARTUP & SHUTDOWN
# ═══════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
async def startup():
    """Initialize system on startup"""
    global searcher, llm, last_sync_time, interaction_logger
    
    logger.info("Starting Aurora Fest RAG Chatbot...")
    
    # Initialize interaction logger (production observability)
    interaction_logger = InteractionLogger(db_path=str(BASE_DIR / "rag_interactions.db"))
    
    # Validate configuration
    if not GROQ_API_KEY:
        logger.error("GROQ_API_KEY not set!")
        sys.exit(1)
    
    if not GOOGLE_SHEETS_ID:
        logger.warning("GOOGLE_SHEETS_ID not set - using fallback mode")
        # You could fall back to Excel here if needed
    
    try:
        # Initialize LLM
        # Load fallback API keys from environment
        fallback_keys_str = os.getenv("GROQ_API_KEY_FALLBACK", "")
        fallback_keys = [k.strip() for k in fallback_keys_str.split(",") if k.strip()] if fallback_keys_str else []
        llm = SmartLLM(GROQ_API_KEY, fallback_keys=fallback_keys)
        logger.info("LLM initialized")
        
        # Load initial data
        if GOOGLE_SHEETS_ID:
            chunker = GoogleSheetsChunker(GOOGLE_SHEETS_ID, GOOGLE_CREDS_FILE)
            chunks = chunker.chunks()
            searcher = VectorSearch(chunks)
            last_sync_time = datetime.now()
            logger.info("Initial data loaded from Google Sheets")
            
            # Start background sync
            start_background_sync()
        else:
            logger.warning("Running without data source")
        
        logger.info("SYSTEM READY!")
        logger.info(f"Server: http://{HOST}:{PORT}")
        logger.info(f"Auto-sync: {'Enabled' if AUTO_SYNC else 'Disabled'}")
        
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    logger.info("Shutting down Aurora Fest RAG Chatbot...")

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        app, 
        host=HOST, 
        port=PORT,
        log_level=LOG_LEVEL.lower()
    )
