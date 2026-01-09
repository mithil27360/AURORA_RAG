
import time
import uuid
import hashlib
import logging
import re
import asyncio
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Header
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.api.deps import get_db_redis, get_interaction_logger, get_vector_store, get_llm, get_security_service
from app.db.redis import RedisClient
from app.db.sqlite import InteractionLogger
from app.services.vector import VectorService
from app.services.llm import LLMService
from app.services.security import SecurityService
from app.services.sheets import get_sheets_service
from app.services.abuse import get_abuse_detector

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)
GREETED_SESSIONS = set()

def get_client_ip(request: Request) -> tuple:
    """Get client IP (returns original and normalized IPv4 if applicable)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        logger.info(f"DEBUG: X-Forwarded-For: {forwarded}")
        original_ip = forwarded.split(",")[0].strip()
    else:
        logger.info("DEBUG: No X-Forwarded-For header found")
        original_ip = request.client.host if request.client else "unknown"
    
    # Keep original for logging, but also extract IPv4 if available
    ipv4 = original_ip
    if original_ip.startswith("::ffff:"):
        ipv4 = original_ip[7:]  # Extract IPv4 from mapped address
    
    if original_ip in ("::1", "localhost"):
        ipv4 = "127.0.0.1"
    
    return original_ip, ipv4

def normalize_query(query: str) -> str:
    """FAANG-level query normalization for better cache hits."""
    import re
    q = query.lower().strip()
    # Remove extra whitespace
    q = re.sub(r'\s+', ' ', q)
    # Remove punctuation except key chars
    q = re.sub(r'[^\w\s?]', '', q)
    # Common typo corrections for event names
    typo_map = {
        'astragavanz': 'astravaganza', 'adtagavanza': 'astravaganza',
        'astravaganz': 'astravaganza', 'astravganza': 'astravaganza',
        'hackthon': 'hackathon', 'hackathn': 'hackathon',
        'registeration': 'registration', 'registation': 'registration',
        'schdule': 'schedule', 'schedul': 'schedule',
    }
    for typo, correct in typo_map.items():
        q = q.replace(typo, correct)
    return q

# --- Schemas ---
class ChatRequest(BaseModel):
    query: str
    threshold: Optional[float] = settings.CONFIDENCE_THRESHOLD
    client_data: Optional[dict] = None  # Cookies, localStorage, screen info

class ChatResponse(BaseModel):
    answer: str
    confidence: float
    tier: str
    response_time_ms: float
    intent: str
    timestamp: str
    interaction_id: str  # For feedback submission 

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    expires_in: int

class FeedbackRequest(BaseModel):
    interaction_id: str
    feedback: str  # "helpful" or "not_helpful"

# --- Helpers ---
def parse_user_agent(ua: str) -> dict:
    """Parse User-Agent to extract device type, browser, and OS"""
    device_type = "Desktop"
    browser = "Unknown"
    os = "Unknown"
    
    if not ua:
        return {"device_type": device_type, "browser": browser, "os": os}
    
    ua_lower = ua.lower()
    
    # Device type
    if any(x in ua_lower for x in ["mobile", "android", "iphone", "ipod"]):
        device_type = "Mobile"
    elif any(x in ua_lower for x in ["ipad", "tablet"]):
        device_type = "Tablet"
    
    # Browser
    if "firefox" in ua_lower:
        browser = "Firefox"
    elif "edg" in ua_lower:
        browser = "Edge"
    elif "chrome" in ua_lower:
        browser = "Chrome"
    elif "safari" in ua_lower:
        browser = "Safari"
    elif "opera" in ua_lower or "opr" in ua_lower:
        browser = "Opera"
    
    # OS
    if "windows" in ua_lower:
        os = "Windows"
    elif "mac os" in ua_lower or "macos" in ua_lower:
        os = "macOS"
    elif "linux" in ua_lower:
        os = "Linux"
    elif "android" in ua_lower:
        os = "Android"
    elif "iphone" in ua_lower or "ipad" in ua_lower:
        os = "iOS"
    
    return {"device_type": device_type, "browser": browser, "os": os}

# --- Routes ---

# Helper for IP Geolocation
async def enrich_client_data(ip: str, client_data: dict) -> dict:
    """Fetch accurate location from IP and merge with client data."""
    if not client_data:
        client_data = {}
    
    # Skip localhost/private IPs
    if ip in ("127.0.0.1", "::1", "unknown") or ip.startswith("192.168.") or ip.startswith("10."):
        client_data["location"] = {"city": "Local Network", "country": "Local", "isp": "Local"}
        return client_data

    import httpx
    
    # Provider 1: ip-api.com (Fast, HTTP, Limit: 45/min)
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"http://ip-api.com/json/{ip}?fields=status,country,city,isp,lat,lon,timezone,mobile")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    client_data["location"] = {
                        "city": data.get("city"),
                        "country": data.get("country"),
                        "isp": data.get("isp"),
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "timezone": data.get("timezone"),
                        "mobile": data.get("mobile")
                    }
                    return client_data
    except Exception:
        pass # Try next provider

    # Provider 2: ipapi.co (Better IPv6 support, HTTPS, Limit: 1000/day)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"https://ipapi.co/{ip}/json/")
            if resp.status_code == 200:
                data = resp.json()
                if "error" not in data:
                    client_data["location"] = {
                        "city": data.get("city"),
                        "country": data.get("country_name"),
                        "isp": data.get("org"),
                        "lat": data.get("latitude"),
                        "lon": data.get("longitude"),
                        "timezone": data.get("timezone"),
                        "mobile": None # ipapi.co doesn't explicit mobile field in free tier easily
                    }
                    return client_data
    except Exception as e:
        logger.warning(f"IP Geolocation failed for {ip}: {e}")
    
    # Fallback: Use client-side timezone if available and IP geo failed
    if "location" not in client_data and client_data.get("timezone"):
        tz = client_data.get("timezone", "")
        if "/" in tz:
            region, city = tz.split("/", 1)
            client_data["location"] = {
                "city": city.replace("_", " "),
                "country": region, # Rough approximation (e.g. Asia, Europe) - better than nothing
                "isp": "Unknown (derived from timezone)",
                "timezone": tz
            }
            # Specific mappings for common timezones
            if "Kolkata" in city: client_data["location"]["country"] = "India"
            elif "New_York" in city or "Los_Angeles" in city: client_data["location"]["country"] = "USA"
            elif "London" in city: client_data["location"]["country"] = "UK"
    
    return client_data

@router.post("/chat", response_model=ChatResponse)
@limiter.limit(settings.RATE_LIMIT_CHAT)
async def serve_chat(
    request: Request, 
    req: ChatRequest,
    redis: RedisClient = Depends(get_db_redis),
    vector_store: VectorService = Depends(get_vector_store),
    llm: LLMService = Depends(get_llm),
    security: SecurityService = Depends(get_security_service),
    interaction_logger: InteractionLogger = Depends(get_interaction_logger)
):
    request_id = str(uuid.uuid4())
    original_ip, ip = get_client_ip(request)  # original_ip for logging, ip for IPv4
    logger.info(f"Received chat request [{request_id}] from {ip}")
    start = time.time()
    
    # FAANG-level query normalization for better cache hits
    normalized_query = normalize_query(req.query)
    
    # Parse device info
    user_agent = request.headers.get("user-agent", "")
    device_info = parse_user_agent(user_agent)
    
    # Get abuse detector
    abuse_detector = get_abuse_detector()
    ip_hash = abuse_detector.hash_ip(ip)
    
    # Check abuse detection (score-based, not single-signal)
    status, block_reason, abuse_data = abuse_detector.process_request(ip, req.query, str(request.url.path))
    
    if status == "hard_block":
        logger.warning(f"Request [{request_id}] BLOCKED (Hard): {abuse_data}")
        await interaction_logger.log_temp_ip(ip, ip_hash, request_id, is_blocked=True)
        raise HTTPException(status_code=403, detail=block_reason)
        
    elif status == "soft_block":
        logger.warning(f"Request [{request_id}] REFUSED (Soft): {abuse_data}")
        # Log purely for analytics but don't process LLM
        # We raise 400 so UI shows the warning message
        raise HTTPException(status_code=400, detail=block_reason)

    # Content moderation
    is_valid, reason = security.moderate_content(req.query)
    if not is_valid:
        logger.warning(f"Request [{request_id}] blocked: {reason}")
        response_time = (time.time() - start) * 1000
        
        # Flag in abuse tracker (not blocking yet, just scoring)
        abuse_detector.flag_blocked_query(ip_hash)
        
        # Log blocked query to analytics
        blocked_answer = f"[BLOCKED] {reason}"
        await interaction_logger.log_interaction(
            interaction_id=request_id,
            query=req.query,
            answer=blocked_answer,
            intent="blocked",
            confidence=0.0,
            response_time_ms=response_time,
            cached=False,
            user_id=hashlib.md5(ip.encode()).hexdigest()[:16],
            ip_hash=ip_hash,
            device_type=device_info["device_type"],
            browser=device_info["browser"],
            os=device_info["os"]
        )
        # Log temp IP for moderation blocks
        await interaction_logger.log_temp_ip(ip, ip_hash, request_id, is_blocked=True)
        
        raise HTTPException(
            status_code=400, 
            detail="Sorry, I can't process that message. Please keep your questions professional and related to Aurora Fest events."
        )

    # Intent classification
    query_lower = req.query.lower()
    intent = "general"
    if any(x in query_lower for x in ["schedule", "when", "time", "date", "calendar", "event", "events"]):
        intent = "schedule"
    elif any(x in query_lower for x in ["where", "venue", "location", "place", "room"]):
        intent = "venue"
    elif any(x in query_lower for x in ["contact", "phone", "email", "reach", "call"]):
        intent = "contact"
    elif any(x in query_lower for x in ["rule", "prerequisite", "eligible", "requirement"]):
        intent = "rules"

    # User Identification & Greeting Logic
    user_id = hashlib.md5(ip.encode()).hexdigest()[:16]
    
    basic_greetings = ["hi", "hello", "hey"]
    is_greeting = req.query.lower().strip().rstrip('!.?') in basic_greetings
    
    if is_greeting and user_id in GREETED_SESSIONS:
        response_time = (time.time() - start) * 1000
        return ChatResponse(
            answer="How can I help?",
            confidence=1.0,
            tier="High",
            response_time_ms=response_time,
            intent="general",
            timestamp=datetime.now().isoformat(),
            interaction_id=request_id
        )
    
    # Mark active
    GREETED_SESSIONS.add(user_id)

    # Check cache (exact match first, then semantic)
    cache_key = hashlib.md5(f"{normalized_query}|{intent}|{req.threshold}".encode()).hexdigest()
    cached_response = await redis.get_cache(cache_key)
    
    # Try semantic cache if exact match fails
    if not cached_response:
        cached_response = await redis.get_semantic_cache(req.query)
    
    if cached_response:
        logger.info(f"Cache HIT for [{request_id}]")
        response_time = (time.time() - start) * 1000
        user_id = hashlib.md5(ip.encode()).hexdigest()[:16]
        # Background task for logging with enrichment
        async def log_cached_bg():
            try:
                enriched = await enrich_client_data(ip, req.client_data)
                await interaction_logger.log_interaction(
                     interaction_id=request_id,
                     query=req.query,
                     answer=cached_response["answer"],
                     intent=intent,
                     confidence=cached_response["confidence"],
                     response_time_ms=response_time,
                     cached=True,
                     user_id=user_id,
                     ip_hash=ip_hash,
                     device_type=device_info["device_type"],
                     browser=device_info["browser"],
                     os=device_info["os"],
                     client_data=enriched
                )
                await interaction_logger.log_temp_ip(ip, ip_hash, request_id)
            except Exception as e:
                logger.error(f"Background cached log failed: {e}")
                
        asyncio.create_task(log_cached_bg())
        return ChatResponse(
            answer=cached_response["answer"],
            confidence=cached_response["confidence"],
            tier="High", # Cached is always high tier
            response_time_ms=response_time,
            intent=intent,
            timestamp=datetime.now().isoformat(),
            interaction_id=request_id
        )

    # Build retrieval filters
    filters = None
    if intent == "schedule":
        filters = {"type": {"$in": ["schedule", "general", "event_list", "about"]}}
    elif intent == "venue":
        # Venue info is stored in schedule chunks, so include both
        filters = {"type": {"$in": ["schedule", "venue", "general", "event_list"]}}
    elif intent == "rules":
        filters = {"type": {"$in": ["rules", "general", "about"]}}

    # Fuzzy Augmentation for Typos
    search_query = req.query
    try:
        fuzzy_matches = await vector_store.fuzzy_search_event(req.query)
        if fuzzy_matches:
            # Augment query with correct names to boost vector/keyword match
            search_query = f"{req.query} {' '.join(fuzzy_matches)}"
            logger.info(f"[{request_id}] Fuzzy match augmented: {search_query}")
    except Exception as e:
        logger.warning(f"Fuzzy search failed: {e}")

    # Vector retrieval with timeout
    try:
        chunks = await asyncio.wait_for(
            vector_store.search(search_query, k=settings.TOP_K_RESULTS, filters=filters),
            timeout=10.0  # 10 second hard timeout for vector search
        )
    except asyncio.TimeoutError:
        logger.error(f"[{request_id}] Vector search timeout")
        chunks = []
    except Exception as e:
        logger.error(f"[{request_id}] Vector search failed: {e}")
        chunks = []
        
    # FORCE INCLUDE master list for "event list" queries
    if intent == "schedule" and ("event" in normalized_query or "events" in normalized_query):
        master_chunk = await vector_store.get_master_event_list()
        if master_chunk:
            # Avoid duplicate if it was already retrieved
            if not any(c["id"] == master_chunk["id"] for c in chunks):
                chunks.insert(0, master_chunk) # Prioritize it
                logger.info(f"[{request_id}] Force included master_event_list")
    
    if not chunks:
        response_time = (time.time() - start) * 1000
        return ChatResponse(
            answer="I'm having trouble accessing my knowledge base right now. Please try again in a moment, or ask me something else about Aurora Fest.",
            confidence=0.0,
            tier="Low",
            response_time_ms=response_time,
            intent=intent,
            timestamp=datetime.now().isoformat(),
            interaction_id=request_id
        )
    
    # Get conversation history
    user_id = hashlib.md5(ip.encode()).hexdigest()[:16]
    try:
        history = await asyncio.wait_for(redis.get_history(user_id), timeout=2.0)
    except Exception:
        history = []  # Continue without history
    

    # Generate response
    try:
        llm_result = await asyncio.wait_for(
            asyncio.to_thread(llm.get_answer, req.query, chunks, intent, history),
            timeout=settings.LLM_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        logger.error(f"[{request_id}] LLM timeout after {settings.LLM_TIMEOUT_SECONDS}s")
        response_time = (time.time() - start) * 1000
        return ChatResponse(
            answer="I'm taking too long to think! Please try asking your question again. Our system is experiencing high load.",
            confidence=0.0,
            tier="Low",
            response_time_ms=response_time,
            intent=intent,
            timestamp=datetime.now().isoformat(),
            interaction_id=request_id
        )
    except Exception as e:
        logger.error(f"[{request_id}] LLM failed: {e}")
        response_time = (time.time() - start) * 1000
        return ChatResponse(
            answer="I'm having trouble generating a response right now. Please try again in a moment!",
            confidence=0.0,
            tier="Low",
            response_time_ms=response_time,
            intent=intent,
            timestamp=datetime.now().isoformat(),
            interaction_id=request_id
        )
    
    response_time = (time.time() - start) * 1000
    

    # Background tasks (non-blocking) with enrichment
    async def log_bg_task():
        try:
             enriched = await enrich_client_data(ip, req.client_data)
             
             # Log history & cache
             await redis.add_history(user_id, req.query, llm_result["answer"])
             await redis.set_cache(cache_key, {
                "answer": llm_result["answer"],
                "confidence": llm_result["confidence"],
                "intent": intent
             }, query=req.query)

             await interaction_logger.log_interaction(
                 interaction_id=request_id,
                 query=req.query,
                 answer=llm_result["answer"],
                 intent=intent,
                 retrieved_docs=chunks,
                 confidence=llm_result["confidence"],
                 used_docs=llm_result["used_docs"],
                 response_time_ms=response_time,
                 cached=False,
                 user_id=user_id,
                 ip_hash=ip_hash,
                 device_type=device_info["device_type"],
                 browser=device_info["browser"],
                 os=device_info["os"],
                 client_data=enriched
            )
            # Log real IP
             await interaction_logger.log_temp_ip(ip, ip_hash, request_id)
        except Exception as e:
            logger.error(f"Background log failed: {e}")

    asyncio.create_task(log_bg_task())
    
    tier = "High" if llm_result["confidence"] > 0.75 else "Medium" if llm_result["confidence"] > 0.5 else "Low"

    return ChatResponse(
        answer=llm_result["answer"],
        confidence=llm_result["confidence"],
        tier=tier,
        response_time_ms=response_time,
        intent=intent,
        timestamp=datetime.now().isoformat(),
        interaction_id=request_id
    )

@router.post("/refresh")
async def refresh_kb(background_tasks: BackgroundTasks):
    sheets = get_sheets_service()
    vector = get_vector_store()
    
    # Run in background
    background_tasks.add_task(_refresh_task, sheets, vector)
    
    return {"status": "refresh_started"}

async def _refresh_task(sheets, vector):
    try:
        events = sheets.fetch_events()
        await vector.update_kb(events)
    except Exception as e:
        logger.error(f"Background refresh failed: {e}")

# --- Auth & Analytics Endpoints ---

@router.get("/login-page")
async def login_page():
    from fastapi.responses import FileResponse
    return FileResponse(settings.BASE_DIR / "app/static/login.html")

@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    if req.username == settings.DASHBOARD_USERNAME and req.password == settings.DASHBOARD_PASSWORD:
        # Simple session token (stateless for this demo)
        token = f"session-{uuid.uuid4()}"
        return LoginResponse(
            token=token,
            expires_in=86400
        )
    raise HTTPException(status_code=401, detail="Invalid credentials")

@router.get("/analytics")
async def get_analytics(
    interaction_logger: InteractionLogger = Depends(get_interaction_logger)
    # logger: InteractionLogger = Depends(get_interaction_logger) # verify token here if needed
):
    # In a real app, verify dependencies. For this sprint, we assume UI handles auth check or we add a dependency.
    return await interaction_logger.get_analytics_summary()

@router.get("/interactions/all")
async def get_all_interactions(
    interaction_logger: InteractionLogger = Depends(get_interaction_logger)
):
    data = await interaction_logger.get_all_interactions()
    return {"interactions": data}

@router.get("/api-stats")
async def get_api_stats(
    llm: LLMService = Depends(get_llm)
):
    """Get API key usage statistics for dashboard"""
    return {
        "status": "ok",
        "api_keys": llm.get_usage_stats()
    }

@router.post("/feedback")
async def submit_feedback(
    req: FeedbackRequest,
    interaction_logger: InteractionLogger = Depends(get_interaction_logger)
):
    """Submit user feedback (helpful/not_helpful) for an interaction"""
    if req.feedback not in ["helpful", "not_helpful"]:
        raise HTTPException(status_code=400, detail="Feedback must be 'helpful' or 'not_helpful'")
    
    success = await interaction_logger.update_feedback(req.interaction_id, req.feedback)
    if success:
        return {"status": "ok", "message": "Feedback recorded"}
    raise HTTPException(status_code=404, detail="Interaction not found")

@router.get("/abuse-stats")
async def get_abuse_stats():
    """Get abuse detection statistics"""
    detector = get_abuse_detector()
    return {
        "status": "ok",
        "abuse_stats": detector.get_stats()
    }

@router.post("/backup-logs")
async def backup_logs(
    interaction_logger: InteractionLogger = Depends(get_interaction_logger)
):
    """Create a manual backup of the interactions database"""
    backup_path = interaction_logger._create_backup("manual")
    if backup_path:
        return {"status": "ok", "backup_path": backup_path}
    raise HTTPException(status_code=500, detail="Backup failed")

@router.get("/export-logs")
async def export_logs(
    interaction_logger: InteractionLogger = Depends(get_interaction_logger)
):
    """Export all logs as JSON for download"""
    data = await interaction_logger.get_all_interactions()
    return {
        "status": "ok",
        "exported_at": datetime.now().isoformat(),
        "count": len(data),
        "interactions": data
    }
