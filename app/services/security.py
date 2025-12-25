
import re
from better_profanity import profanity
from app.core.config import settings

class SecurityService:
    def __init__(self):
        # Load blocked patterns from config or hardcoded for now (Defense in Depth)
        self.blocked_patterns = [
             r'(.)\1{10,}',  # Repeated characters (aaaaaaaaaaa)
             r'\b(test){5,}\b',  # Repeated words
             r'(ignore|bypass|override|hack|break|crash)\s+(prompt|instruction|rule|system)',
             r'(you\s+are|act\s+as|pretend|roleplay)\s+(not|now)',
             r'(drop|delete|insert|update)\s+(table|database)',
             r'<script|javascript:|onerror=',
        ]
        # Initialize profanity filter
        profanity.load_censor_words()

    def moderate_content(self, query: str) -> tuple[bool, str]:
        """
        Moderate user input.
        Returns: (is_valid, reason)
        """
        query_lower = query.lower().strip()
        
        # 1. Length Check
        if len(query) < 2:
            return False, "Query too short"
        if len(query) > 500:
            return False, "Query too long (max 500 characters)"

        # 2. Profanity Check (Library)
        if profanity.contains_profanity(query):
            return False, "Inappropriate content detected"

        # 3. Security/Spam Patterns (Regex)
        for pattern in self.blocked_patterns:
            if re.search(pattern, query_lower):
                return False, "Security/Spam pattern detected"

        return True, ""

security_service = SecurityService()

def get_security():
    return security_service
