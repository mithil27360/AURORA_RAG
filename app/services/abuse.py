"""
Abuse Detection Service

High-confidence abuse detection with scoring system:
- Multiple signals required (never block on one)
- Decay over time (5 min window)
- Temporary blocking (15-60 min auto-unblock)
- Evidence logging, not emotion
"""

import time
import re
import hashlib
import logging
from typing import Dict, Tuple, List

logger = logging.getLogger(__name__)

# Abuse scoring weights
ABUSE_SCORES = {
    "malformed_input": 1,
    "spam_chars": 3,
    "sql_injection": 5,
    "xss_attempt": 5,
    "prompt_injection": 7,
    "admin_probe": 10,
    "rate_exceeded": 3,
    "repeated_blocked": 5,
}

# Detection patterns
SQL_PATTERNS = [
    r"(?i)(drop|delete|truncate|alter|insert|update)\s+(table|database|from)",
    r"(?i)(union\s+select|select\s+\*\s+from)",
    r"(?i)(--|;)\s*(drop|delete|select)",
    r"(?i)'\s*(or|and)\s*'?\d*'?\s*=\s*'?\d*",
]

XSS_PATTERNS = [
    r"(?i)<script[^>]*>",
    r"(?i)javascript:",
    r"(?i)onerror\s*=",
    r"(?i)onload\s*=",
    r"(?i)<iframe",
]

PROMPT_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(previous|all)\s+(instructions|prompts)",
    r"(?i)system\s*:\s*you\s+are",
    r"(?i)pretend\s+(you\s+are|to\s+be)\s+(an?\s+)?admin",
    r"(?i)reveal\s+(your|the)\s+(secret|password|key)",
    r"(?i)bypass\s+(moderation|filter|security)",
]

ADMIN_PROBE_PATTERNS = [
    r"/admin",
    r"/api/admin",
    r"/../",
    r"(?i)/etc/passwd",
    r"(?i)\.env",
]


class AbuseDetector:
    """Score-based abuse detection with decay and temp blocking"""
    
    def __init__(self, score_threshold: int = 10, block_duration_sec: int = 900):
        # In-memory trackers (use Redis in production for multi-instance)
        self.abuse_scores: Dict[str, dict] = {}  # ip_hash -> {score, last_seen, reasons}
        self.blocked_ips: Dict[str, float] = {}  # ip_hash -> unblock_time
        self.request_counts: Dict[str, List[float]] = {}  # ip_hash -> list of timestamps
        
        self.score_threshold = score_threshold  # Default: 10 points to block
        self.block_duration = block_duration_sec  # Default: 15 min
        self.decay_window = 300  # 5 minutes
        self.rate_limit_window = 60  # 1 minute
        self.rate_limit_max = 30  # Max requests per minute
    
    def hash_ip(self, ip: str) -> str:
        """Create consistent hash of IP for storage"""
        return hashlib.sha256(ip.encode()).hexdigest()[:16]
    
    def is_blocked(self, ip_hash: str) -> bool:
        """Check if IP is currently blocked"""
        if ip_hash not in self.blocked_ips:
            return False
        
        unblock_time = self.blocked_ips[ip_hash]
        if time.time() >= unblock_time:
            # Auto-unblock
            del self.blocked_ips[ip_hash]
            # Reset score
            if ip_hash in self.abuse_scores:
                del self.abuse_scores[ip_hash]
            logger.info(f"Auto-unblocked IP hash: {ip_hash[:8]}...")
            return False
        
        return True
    
    def check_rate_limit(self, ip_hash: str) -> bool:
        """Check if IP is exceeding rate limit (returns True if exceeded)"""
        now = time.time()
        
        if ip_hash not in self.request_counts:
            self.request_counts[ip_hash] = []
        
        # Clean old timestamps
        self.request_counts[ip_hash] = [
            ts for ts in self.request_counts[ip_hash] 
            if now - ts < self.rate_limit_window
        ]
        
        # Add current request
        self.request_counts[ip_hash].append(now)
        
        return len(self.request_counts[ip_hash]) > self.rate_limit_max
    
    def detect_abuse_signals(self, query: str, path: str = "") -> List[Tuple[str, int]]:
        """Detect abuse signals in query. Returns list of (signal_type, score)"""
        signals = []
        
        # SQL Injection
        for pattern in SQL_PATTERNS:
            if re.search(pattern, query):
                signals.append(("sql_injection", ABUSE_SCORES["sql_injection"]))
                break
        
        # XSS
        for pattern in XSS_PATTERNS:
            if re.search(pattern, query):
                signals.append(("xss_attempt", ABUSE_SCORES["xss_attempt"]))
                break
        
        # Prompt Injection
        for pattern in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, query):
                signals.append(("prompt_injection", ABUSE_SCORES["prompt_injection"]))
                break
        
        # Admin probing
        for pattern in ADMIN_PROBE_PATTERNS:
            if re.search(pattern, path + query):
                signals.append(("admin_probe", ABUSE_SCORES["admin_probe"]))
                break
        
        # Spam characters (repeated chars like "aaaaaaa")
        if re.search(r'(.)\1{10,}', query):
            signals.append(("spam_chars", ABUSE_SCORES["spam_chars"]))
        
        return signals
    
    def flag_abuse(self, ip_hash: str, signals: List[Tuple[str, int]]) -> dict:
        """Add abuse points and check if should block"""
        now = time.time()
        
        if ip_hash not in self.abuse_scores:
            self.abuse_scores[ip_hash] = {"score": 0, "last_seen": now, "reasons": []}
        
        data = self.abuse_scores[ip_hash]
        
        # Decay old behavior
        if now - data["last_seen"] > self.decay_window:
            data["score"] = 0
            data["reasons"] = []
        
        # Add new signals
        for signal_type, points in signals:
            data["score"] += points
            if signal_type not in data["reasons"]:
                data["reasons"].append(signal_type)
        
        data["last_seen"] = now
        self.abuse_scores[ip_hash] = data
        
        return data
    
    def flag_blocked_query(self, ip_hash: str):
        """Increment score when query is blocked by moderation"""
        self.flag_abuse(ip_hash, [("repeated_blocked", ABUSE_SCORES["repeated_blocked"])])
    
    def flag_rate_exceeded(self, ip_hash: str):
        """Increment score when rate limit is exceeded"""
        self.flag_abuse(ip_hash, [("rate_exceeded", ABUSE_SCORES["rate_exceeded"])])
    
    def should_block(self, ip_hash: str) -> Tuple[bool, dict]:
        """Check if IP should be blocked based on score"""
        data = self.abuse_scores.get(ip_hash, {"score": 0, "reasons": []})
        
        if data["score"] >= self.score_threshold:
            # Block the IP
            self.blocked_ips[ip_hash] = time.time() + self.block_duration
            
            log_data = {
                "ip_hash": ip_hash,
                "reasons": data["reasons"],
                "score": data["score"],
                "blocked_until": self.blocked_ips[ip_hash],
            }
            logger.warning(f"Blocking IP: {log_data}")
            return True, log_data
        
        return False, data
    
    def process_request(self, ip: str, query: str, path: str = "") -> Tuple[bool, str, dict]:
        """
        Main entry point. Returns (is_allowed, reason, abuse_data)
        - is_allowed: True if request should proceed
        - reason: Why blocked (if blocked)
        - abuse_data: Current abuse state for logging
        """
        ip_hash = self.hash_ip(ip)
        
        # Check if already blocked
        if self.is_blocked(ip_hash):
            return False, "Access temporarily blocked due to abusive behavior.", {"blocked": True}
        
        # Check rate limit
        if self.check_rate_limit(ip_hash):
            self.flag_rate_exceeded(ip_hash)
            blocked, data = self.should_block(ip_hash)
            if blocked:
                return False, "Access temporarily blocked due to abusive behavior.", data
        
        # Detect abuse signals
        signals = self.detect_abuse_signals(query, path)
        
        if signals:
            self.flag_abuse(ip_hash, signals)
            blocked, data = self.should_block(ip_hash)
            if blocked:
                return False, "Access temporarily blocked due to abusive behavior.", data
            return True, "", data  # Not blocked yet, but tracking
        
        return True, "", {"score": 0}
    
    def get_stats(self) -> dict:
        """Get current abuse detection stats"""
        return {
            "tracked_ips": len(self.abuse_scores),
            "blocked_ips": len(self.blocked_ips),
            "high_risk_ips": sum(1 for d in self.abuse_scores.values() if d["score"] >= 5),
        }


# Singleton
_detector = None

def get_abuse_detector() -> AbuseDetector:
    global _detector
    if _detector is None:
        _detector = AbuseDetector()
    return _detector
