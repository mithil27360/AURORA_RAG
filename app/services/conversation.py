"""
Aurora RAG Chatbot - Conversation Management Service

Handles multi-turn context, entity extraction, and session persistence.
"""

import asyncio
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from collections import deque
from datetime import datetime, timedelta
import json
import re

from app.core.config import settings

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Message:
    """Single conversation message."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    intent: Optional[str] = None
    confidence: Optional[float] = None
    entities: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "intent": self.intent,
            "confidence": self.confidence,
            "entities": self.entities
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Message":
        return cls(**data)


@dataclass
class ConversationContext:
    """
    Conversation context for multi-turn interactions.
    
    Tracks:
    - Message history
    - Extracted entities
    - Current topic/intent
    - User preferences
    """
    session_id: str
    messages: List[Message] = field(default_factory=list)
    entities: Dict[str, Any] = field(default_factory=dict)
    current_topic: Optional[str] = None
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    greeted: bool = False
    
    def add_message(self, role: str, content: str, **kwargs) -> None:
        """Add a message to history."""
        message = Message(role=role, content=content, **kwargs)
        self.messages.append(message)
        self.updated_at = time.time()
        
        # Update entities if provided
        if message.entities:
            self.entities.update(message.entities)
        
        # Update topic if intent is strong
        if message.intent and message.confidence and message.confidence > 0.7:
            self.current_topic = message.intent
    
    def get_history(self, max_turns: int = 10) -> List[Dict]:
        """Get recent conversation history."""
        recent = self.messages[-max_turns * 2:] if len(self.messages) > max_turns * 2 else self.messages
        return [m.to_dict() for m in recent]
    
    def get_history_text(self, max_turns: int = 5) -> str:
        """Get history as formatted text for LLM."""
        recent = self.messages[-max_turns * 2:] if len(self.messages) > max_turns * 2 else self.messages
        
        lines = []
        for msg in recent:
            prefix = "User" if msg.role == "user" else "Assistant"
            lines.append(f"{prefix}: {msg.content}")
        
        return "\n".join(lines) if lines else ""
    
    def get_summary(self) -> str:
        """Get conversation summary."""
        if not self.messages:
            return "No conversation history."
        
        user_queries = [m.content for m in self.messages if m.role == "user"]
        topics = set(m.intent for m in self.messages if m.intent)
        
        summary = f"Conversation with {len(user_queries)} queries"
        if topics:
            summary += f" about: {', '.join(topics)}"
        if self.entities:
            summary += f". Mentioned: {', '.join(self.entities.keys())}"
        
        return summary
    
    def is_expired(self, ttl_seconds: int = 3600) -> bool:
        """Check if context has expired."""
        return time.time() - self.updated_at > ttl_seconds
    
    def to_dict(self) -> Dict:
        """Serialize context."""
        return {
            "session_id": self.session_id,
            "messages": [m.to_dict() for m in self.messages],
            "entities": self.entities,
            "current_topic": self.current_topic,
            "user_preferences": self.user_preferences,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "greeted": self.greeted
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "ConversationContext":
        """Deserialize context."""
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            session_id=data["session_id"],
            messages=messages,
            entities=data.get("entities", {}),
            current_topic=data.get("current_topic"),
            user_preferences=data.get("user_preferences", {}),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            greeted=data.get("greeted", False)
        )


# =============================================================================
# ENTITY EXTRACTOR
# =============================================================================

class EntityExtractor:
    """
    Extract entities from user queries.
    
    Supported entities:
    - Events (by name)
    - Dates (today, tomorrow, specific)
    - Times
    - Clubs/organizers
    - Venues
    """
    
    # Date patterns
    DATE_PATTERNS = [
        (r'\b(today|tonight)\b', 'today'),
        (r'\b(tomorrow)\b', 'tomorrow'),
        (r'\b(yesterday)\b', 'yesterday'),
        (r'\b(\d{4}-\d{2}-\d{2})\b', 'date'),
        (r'\b(\d{1,2}(?:st|nd|rd|th)?(?:\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*))\b', 'date'),
        (r'\b(day\s*\d+)\b', 'day'),
        (r'\b(next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b', 'day'),
    ]
    
    # Time patterns
    TIME_PATTERNS = [
        (r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b', 'time'),
        (r'\b(morning|afternoon|evening|night)\b', 'time_of_day'),
    ]
    
    # Event type patterns
    EVENT_TYPES = [
        'workshop', 'hackathon', 'tech talk', 'competition',
        'seminar', 'panel', 'networking', 'quiz'
    ]
    
    def __init__(self, known_events: List[str] = None, known_clubs: List[str] = None):
        self.known_events = set(e.lower() for e in (known_events or []))
        self.known_clubs = set(c.lower() for c in (known_clubs or []))
    
    def extract(self, text: str) -> Dict[str, Any]:
        """Extract all entities from text."""
        text_lower = text.lower()
        entities = {}
        
        # Extract dates
        for pattern, entity_type in self.DATE_PATTERNS:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                entities['date_reference'] = match.group(1)
                entities['date_type'] = entity_type
                break
        
        # Extract times
        for pattern, entity_type in self.TIME_PATTERNS:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                entities['time_reference'] = match.group(1)
                entities['time_type'] = entity_type
                break
        
        # Extract event types
        for event_type in self.EVENT_TYPES:
            if event_type in text_lower:
                entities['event_type'] = event_type
                break
        
        # Extract known events
        for event in self.known_events:
            if event in text_lower:
                entities['event_name'] = event
                break
        
        # Extract known clubs
        for club in self.known_clubs:
            if club in text_lower:
                entities['club_name'] = club
                break
        
        # Extract ordinal references (first, second, etc.)
        ordinal_match = re.search(r'\b(first|second|third|fourth|fifth|next|last)\b', text_lower)
        if ordinal_match:
            entities['ordinal'] = ordinal_match.group(1)
        
        return entities
    
    def update_known_events(self, events: List[str]) -> None:
        """Update known events list."""
        self.known_events = set(e.lower() for e in events)
    
    def update_known_clubs(self, clubs: List[str]) -> None:
        """Update known clubs list."""
        self.known_clubs = set(c.lower() for c in clubs)


# =============================================================================
# CONVERSATION MANAGER
# =============================================================================

class ConversationManager:
    """
    Manages conversation sessions and context.
    
    Features:
    - In-memory session storage (with Redis fallback)
    - Automatic session expiry
    - Context persistence
    - Multi-turn tracking
    """
    
    def __init__(
        self,
        redis_client=None,
        max_sessions: int = 10000,
        session_ttl: int = 3600,
        max_history: int = 10
    ):
        self.redis = redis_client
        self.max_sessions = max_sessions
        self.session_ttl = session_ttl
        self.max_history = max_history
        
        # In-memory fallback
        self._sessions: Dict[str, ConversationContext] = {}
        self._access_order: deque = deque()
        self._lock = asyncio.Lock()
        
        # Entity extractor
        self.entity_extractor = EntityExtractor()
    
    async def get_or_create(self, session_id: str) -> ConversationContext:
        """Get existing session or create new one."""
        context = await self.get(session_id)
        if context is None:
            context = ConversationContext(session_id=session_id)
            await self.save(context)
        return context
    
    async def get(self, session_id: str) -> Optional[ConversationContext]:
        """Get session context."""
        # Try Redis first
        if self.redis:
            try:
                data = await self.redis.get(f"session:{session_id}")
                if data:
                    return ConversationContext.from_dict(json.loads(data))
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")
        
        # Fall back to in-memory
        async with self._lock:
            context = self._sessions.get(session_id)
            if context and not context.is_expired(self.session_ttl):
                return context
            elif context:
                del self._sessions[session_id]
        
        return None
    
    async def save(self, context: ConversationContext) -> None:
        """Save session context."""
        context.updated_at = time.time()
        
        # Try Redis first
        if self.redis:
            try:
                await self.redis.setex(
                    f"session:{context.session_id}",
                    self.session_ttl,
                    json.dumps(context.to_dict())
                )
                return
            except Exception as e:
                logger.warning(f"Redis save failed: {e}")
        
        # Fall back to in-memory
        async with self._lock:
            # Evict if at capacity
            while len(self._sessions) >= self.max_sessions:
                if self._access_order:
                    oldest = self._access_order.popleft()
                    self._sessions.pop(oldest, None)
            
            self._sessions[context.session_id] = context
            
            # Update access order
            if context.session_id in self._access_order:
                self._access_order.remove(context.session_id)
            self._access_order.append(context.session_id)
    
    async def delete(self, session_id: str) -> bool:
        """Delete session."""
        deleted = False
        
        if self.redis:
            try:
                result = await self.redis.delete(f"session:{session_id}")
                deleted = result > 0
            except Exception as e:
                logger.warning(f"Redis delete failed: {e}")
        
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                if session_id in self._access_order:
                    self._access_order.remove(session_id)
                deleted = True
        
        return deleted
    
    async def process_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_response: str,
        intent: Optional[str] = None,
        confidence: Optional[float] = None
    ) -> ConversationContext:
        """Process a conversation turn (user query + assistant response)."""
        context = await self.get_or_create(session_id)
        
        # Extract entities from user query
        entities = self.entity_extractor.extract(user_query)
        
        # Add user message
        context.add_message(
            role="user",
            content=user_query,
            intent=intent,
            entities=entities
        )
        
        # Add assistant message
        context.add_message(
            role="assistant",
            content=assistant_response,
            confidence=confidence
        )
        
        # Trim history if needed
        if len(context.messages) > self.max_history * 2:
            context.messages = context.messages[-self.max_history * 2:]
        
        await self.save(context)
        return context
    
    async def get_context_for_llm(self, session_id: str) -> Dict[str, Any]:
        """Get formatted context for LLM prompt."""
        context = await self.get(session_id)
        
        if not context:
            return {
                "history": "",
                "entities": {},
                "topic": None,
                "greeted": False
            }
        
        return {
            "history": context.get_history_text(max_turns=5),
            "entities": context.entities,
            "topic": context.current_topic,
            "greeted": context.greeted
        }
    
    async def mark_greeted(self, session_id: str) -> None:
        """Mark session as greeted."""
        context = await self.get_or_create(session_id)
        context.greeted = True
        await self.save(context)
    
    async def is_greeted(self, session_id: str) -> bool:
        """Check if session has been greeted."""
        context = await self.get(session_id)
        return context.greeted if context else False
    
    async def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count removed."""
        removed = 0
        
        async with self._lock:
            expired = [
                sid for sid, ctx in self._sessions.items()
                if ctx.is_expired(self.session_ttl)
            ]
            
            for sid in expired:
                del self._sessions[sid]
                if sid in self._access_order:
                    self._access_order.remove(sid)
                removed += 1
        
        if removed > 0:
            logger.debug(f"Cleaned up {removed} expired sessions")
        
        return removed
    
    def get_stats(self) -> Dict:
        """Get conversation manager statistics."""
        return {
            "active_sessions": len(self._sessions),
            "max_sessions": self.max_sessions,
            "session_ttl": self.session_ttl,
            "redis_connected": self.redis is not None
        }


# =============================================================================
# INTENT CHAINING
# =============================================================================

class IntentChain:
    """
    Tracks intent sequences for follow-up handling.
    
    Example chains:
    - schedule -> venue (user asks about timing, then location)
    - registration -> contact (user wants to register, needs help)
    """
    
    # Common follow-up patterns
    FOLLOW_UP_PATTERNS = {
        ("schedule", "venue"): "You might also want to know where this event is held.",
        ("schedule", "registration"): "Would you like to register for this event?",
        ("venue", "schedule"): "Would you like to know when this event starts?",
        ("registration", "contact"): "Need help with registration? Here's who to contact.",
    }
    
    def __init__(self):
        self._chains: Dict[str, List[str]] = {}  # session_id -> [intents]
    
    def add_intent(self, session_id: str, intent: str) -> Optional[str]:
        """
        Add intent to chain and return any follow-up suggestion.
        """
        if session_id not in self._chains:
            self._chains[session_id] = []
        
        chain = self._chains[session_id]
        
        # Get potential follow-up if there's a previous intent
        follow_up = None
        if chain:
            prev_intent = chain[-1]
            follow_up = self.FOLLOW_UP_PATTERNS.get((prev_intent, intent))
        
        # Add to chain (keep last 5)
        chain.append(intent)
        if len(chain) > 5:
            chain.pop(0)
        
        return follow_up
    
    def get_chain(self, session_id: str) -> List[str]:
        """Get intent chain for session."""
        return self._chains.get(session_id, [])
    
    def clear(self, session_id: str) -> None:
        """Clear chain for session."""
        self._chains.pop(session_id, None)


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

_conversation_manager: Optional[ConversationManager] = None
_intent_chain: IntentChain = IntentChain()


def get_conversation_manager() -> Optional[ConversationManager]:
    """Get global conversation manager."""
    return _conversation_manager


async def init_conversation_manager(redis_client=None, **kwargs) -> ConversationManager:
    """Initialize global conversation manager."""
    global _conversation_manager
    
    _conversation_manager = ConversationManager(
        redis_client=redis_client,
        max_sessions=kwargs.get('max_sessions', settings.MAX_CONVERSATION_USERS),
        session_ttl=kwargs.get('session_ttl', settings.SESSION_TTL_SECONDS),
        max_history=kwargs.get('max_history', settings.MAX_HISTORY_TURNS)
    )
    
    logger.info("Conversation manager initialized")
    return _conversation_manager


def get_intent_chain() -> IntentChain:
    """Get global intent chain tracker."""
    return _intent_chain
