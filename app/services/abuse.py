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
    "system_internals": 5,
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

SYSTEM_INTERNALS_PATTERNS = [
    r"(?i)(what|which)\s+(ai|llm|model|gpt)\s+(are|is)\s+(you|used|running)",
    r"(?i)how\s+(are|were)\s+(you|the\s+bot)\s+(made|built|created|trained)",
    r"(?i)who\s+(made|built|created|coded|programmed)\s+(you|this)",
    r"(?i)(system|internal)\s+(prompt|instructions|rules|logic)",
    r"(?i)(tech|technology)\s*stack",
    r"(?i)(source|backend)\s*code",
    r"(?i)(give|show|reveal|send)\s+(me\s+)?(your\s+)?code",
    r"(?i)backend\s+(technology|details)",
]

ADMIN_PROBE_PATTERNS = [
    r"/admin",
    r"/api/admin",
    r"/../",
    r"(?i)/etc/passwd",
    r"(?i)\.env",
]


# Allowed conversational inputs (Whitelist - Bypass all checks)
WHITELISTED_INPUTS = {
    "hi", "hello", "hey", "hlo", "hy", "help",
    "thanks", "thank you", "thx", "tks",
    "bye", "goodbye", "cya",
    "ok", "okay", "k", "cool",
    "yes", "no", "yup", "nope",
    "what", "when", "where", "how", "who" # Basic start words
}

class AbuseDetector:
    """Score-based abuse detection with layered security (Whitelist -> Soft -> Critical)"""
    
    def __init__(self, score_threshold: int = 20, block_duration_sec: int = 900):
        # In-memory trackers
        self.abuse_scores: Dict[str, dict] = {}  # ip_hash -> {score, last_seen, reasons}
        self.blocked_ips: Dict[str, float] = {}  # ip_hash -> unblock_time
        self.request_counts: Dict[str, List[float]] = {}  # ip_hash -> list of timestamps
        
        self.score_threshold = score_threshold  # Higher threshold (was 10, now 20)
        self.block_duration = block_duration_sec
        self.decay_window = 300  # 5 minutes
        self.rate_limit_window = 60  # 1 minute
        self.rate_limit_max = 60  # Relaxed rate limit (was 30)
    
    def hash_ip(self, ip: str) -> str:
        """Create consistent hash of IP for storage"""
        return hashlib.sha256(ip.encode()).hexdigest()[:16]
    
    def is_blocked(self, ip_hash: str) -> bool:
        """Check if IP is currently completely locked out"""
        if ip_hash not in self.blocked_ips:
            return False
        
        unblock_time = self.blocked_ips[ip_hash]
        if time.time() >= unblock_time:
            # Auto-unblock
            del self.blocked_ips[ip_hash]
            if ip_hash in self.abuse_scores:
                del self.abuse_scores[ip_hash]
            logger.info(f"Auto-unblocked IP hash: {ip_hash[:8]}...")
            return False
        
        return True
    
    def check_rate_limit(self, ip_hash: str) -> bool:
        """Check if IP is exceeding rate limit"""
        now = time.time()
        if ip_hash not in self.request_counts:
            self.request_counts[ip_hash] = []
        
        # Clean old timestamps
        self.request_counts[ip_hash] = [
            ts for ts in self.request_counts[ip_hash] 
            if now - ts < self.rate_limit_window
        ]
        
        self.request_counts[ip_hash].append(now)
        return len(self.request_counts[ip_hash]) > self.rate_limit_max
    
    def detect_abuse_signals(self, query: str, path: str = "") -> List[Tuple[str, int, str]]:
        """Detect abuse signals. Returns list of (signal_type, score, severity)"""
        signals = []
        query_lower = query.lower()
        
        # SQL Injection
        for pattern in SQL_PATTERNS:
            if re.search(pattern, query_lower):
                # Single attempt is SOFT (Warning), Repeated is handled by scoring
                signals.append(("sql_injection", ABUSE_SCORES["sql_injection"], "soft"))
                break
        
        # XSS - Soft
        for pattern in XSS_PATTERNS:
            if re.search(pattern, query_lower):
                signals.append(("xss_attempt", ABUSE_SCORES["xss_attempt"], "soft"))
                break
        
        # Prompt Injection - Soft/Medium
        for pattern in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, query_lower):
                signals.append(("prompt_injection", ABUSE_SCORES["prompt_injection"], "soft"))
                break
        
        # System Internals - Soft/Medium
        for pattern in SYSTEM_INTERNALS_PATTERNS:
            if re.search(pattern, query_lower):
                signals.append(("system_internals", ABUSE_SCORES["system_internals"], "soft"))
                break
        
        # Admin probing - CRITICAL
        for pattern in ADMIN_PROBE_PATTERNS:
            if re.search(pattern, path + query_lower):
                signals.append(("admin_probe", ABUSE_SCORES["admin_probe"], "critical"))
                break
        
        return signals
    
    def flag_abuse(self, ip_hash: str, signals: List[Tuple[str, int, str]]) -> dict:
        """Add abuse points"""
        now = time.time()
        
        if ip_hash not in self.abuse_scores:
            self.abuse_scores[ip_hash] = {"score": 0, "last_seen": now, "reasons": []}
        
        data = self.abuse_scores[ip_hash]
        
        # Decay
        if now - data["last_seen"] > self.decay_window:
            data["score"] = 0
            data["reasons"] = []
        
        # Add points
        for signal_type, points, severity in signals:
            data["score"] += points
            if signal_type not in data["reasons"]:
                data["reasons"].append(signal_type)
        
        data["last_seen"] = now
        self.abuse_scores[ip_hash] = data
        return data

    def flag_rate_exceeded(self, ip_hash: str):
        self.flag_abuse(ip_hash, [("rate_exceeded", ABUSE_SCORES["rate_exceeded"], "soft")])

    def flag_blocked_query(self, ip_hash: str):
        self.flag_abuse(ip_hash, [("repeated_blocked", ABUSE_SCORES["repeated_blocked"], "soft")])

    def should_block(self, ip_hash: str) -> bool:
        """Check if score threshold exceeded (Repeated offenses)"""
        data = self.abuse_scores.get(ip_hash, {"score": 0})
        if data["score"] >= self.score_threshold:
            self.blocked_ips[ip_hash] = time.time() + self.block_duration
            logger.warning(f"BLOCKING IP {ip_hash} (Score: {data['score']})")
            return True
        return False
    
    def process_request(self, ip: str, query: str, path: str = "") -> Tuple[str, str, dict]:
        """
        Main entry point.
        Returns: (status, message, data)
        - status: "allowed", "soft_block" (refusal), "hard_block" (403 lock)
        """
        ip_hash = self.hash_ip(ip)
        
        # 1. Check Whitelist (Bypass EVERYTHING - even locks)
        q_clean = query.lower().strip().rstrip("?!.,")
        if q_clean in WHITELISTED_INPUTS or len(q_clean) < 2:
            return "allowed", "", {"score": 0}

        # 2. Check Hard Block
        if self.is_blocked(ip_hash):
            return "hard_block", "Access denied due to repeated abusive behavior.", {"blocked": True}
            
        # 3. Check Rate Limit
        if self.check_rate_limit(ip_hash):
            self.flag_rate_exceeded(ip_hash)
            if self.should_block(ip_hash):
                 return "hard_block", "Rate limit exceeded. Access paused.", {"blocked": True}
        
        # 4. Check Abuse Signals
        signals = self.detect_abuse_signals(query, path)
        if signals:
            data = self.flag_abuse(ip_hash, signals)
            
            # Check if this push crossed the threshold for Hard Block
            if self.should_block(ip_hash):
                return "hard_block", "Security threshold exceeded.", data
            
            # Otherwise, it's a Soft Refusal (Warning)
            # We return "soft_block" so the UI shows a warning but user isn't locked
            return "soft_block", "I cannot process that request. Please keeping queries related to Aurora Fest events.", data

        return "allowed", "", {"score": 0}

    def get_stats(self) -> dict:
        return {
            "tracked_ips": len(self.abuse_scores),
            "blocked_ips": len(self.blocked_ips),
            "high_risk_ips": sum(1 for d in self.abuse_scores.values() if d["score"] >= 10),
        }


# Singleton
_detector = None

def get_abuse_detector() -> AbuseDetector:
    global _detector
    if _detector is None:
        _detector = AbuseDetector()
    return _detector
