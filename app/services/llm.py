"""LLM Service - Handles Groq API interactions for answer generation."""

import logging
from groq import Groq
from typing import Dict, List
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """Groq-based LLM service for RAG answer generation."""
    
    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.total_requests = 0
        
        if not self.api_key:
            logger.warning("GROQ_API_KEY not set")
            self.client = None
        else:
            self.client = Groq(api_key=self.api_key)
            self.model = "llama-3.3-70b-versatile"
    
    def get_usage_stats(self) -> Dict:
        """Return API usage statistics."""
        return {
            "total_keys": 1,
            "current_key_index": 1,
            "total_requests": self.total_requests,
            "key_rotations": 0
        }

    def get_answer(self, query: str, chunks: List[Dict], intent: str = "general", history: List[Dict] = None) -> Dict:
        """Generate answer from context chunks using LLM."""
        if not self.client:
            return self._error_response("LLM not initialized")
            
        context_text = "\n\n".join([c["text"] for c in chunks])
        if not context_text:
            return self._error_response("I don't have enough specific information about that.", confidence=0.0)

        history_text = ""
        if history:
            history_text = "\n".join([f"User: {h['query']}\nAI: {h['answer']}" for h in history])

        system_instruction = ""
        if settings.STRICT_MODE:
            system_instruction = """
- STRICT MODE: Answer ONLY from provided context.
- Do NOT hallucinate. If unsure, say "I don't have that information".
- For follow-ups, refer to conversation history.
"""

        prompt = f"""You are Aurora Fest Assistant for ISTE's Aurora college fest.

Context:
{context_text}

History:
{history_text if history_text else "(None)"}

Question: {query}
Intent: {intent}

RULES:
{system_instruction}
1. Greetings (hi/thanks/bye): respond socially, don't list events.
2. Follow-ups: use history context.
3. Topic searches: check descriptions and topics, not just names.
4. Keep answers concise (2-3 sentences).
5. Only say "I don't have that information" if truly nothing is relevant.

Answer:"""

        try:
            temp = 0.0 if settings.STRICT_MODE else settings.LLM_TEMPERATURE

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temp,
                max_tokens=400,
                timeout=settings.LLM_TIMEOUT_SECONDS
            )
            
            self.total_requests += 1
            answer = response.choices[0].message.content.strip()
            avg_score = max([c["score"] for c in chunks]) if chunks else 0.0
            
            return {
                "answer": answer,
                "confidence": avg_score,
                "used_docs": [c["id"] for c in chunks]
            }

        except Exception as e:
            logger.error(f"LLM error: {e}")
            return self._error_response("I'm having trouble right now. Please try again!")

    def _error_response(self, msg: str, confidence: float = 0.0):
        return {"answer": msg, "confidence": confidence, "used_docs": []}


llm_service = LLMService()

def get_llm_service():
    return llm_service
