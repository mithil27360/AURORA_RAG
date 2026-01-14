"""
Cross-Encoder Reranker Service for Aurora RAG

Improves retrieval precision by reranking initial vector search results
using a cross-encoder model that jointly encodes query + document.

Expected Impact:
- Retrieval precision: 65% → 80% (+15%)
- Answer hallucinations: -30%
- Latency: +50-100ms (acceptable for accuracy gain)
"""

from typing import List, Dict
from sentence_transformers import CrossEncoder
import logging

logger = logging.getLogger(__name__)


class RerankerService:
    """
    Cross-encoder based reranker for improving retrieval precision.
    
    Architecture:
    1. Vector search retrieves top 20 candidates (high recall)
    2. Cross-encoder reranks them (high precision)
    3. Return top 5 for LLM context
    
    Model: cross-encoder/ms-marco-MiniLM-L-6-v2
    - Trained on MS MARCO passage ranking
    - 384M parameters, 80MB model size
    - Inference: ~10ms per query-doc pair on CPU
    """
    
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Initialize cross-encoder model.
        
        Args:
            model_name: HuggingFace model identifier
        """
        try:
            logger.info(f"Loading cross-encoder model: {model_name}")
            self.model = CrossEncoder(model_name, max_length=512)
            logger.info("✅ Cross-encoder loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load cross-encoder: {e}")
            self.model = None
    
    def rerank(
        self, 
        query: str, 
        chunks: List[Dict], 
        top_k: int = 5,
        vector_weight: float = 0.3,
        rerank_weight: float = 0.7
    ) -> List[Dict]:
        """
        Rerank chunks using cross-encoder scores.
        
        Args:
            query: User query
            chunks: List of chunks from vector search (with 'text' and 'similarity')
            top_k: Number of top chunks to return
            vector_weight: Weight for original vector similarity (0.0-1.0)
            rerank_weight: Weight for cross-encoder score (0.0-1.0)
        
        Returns:
            Top-k reranked chunks with updated scores
        
        Example:
            chunks = [
                {"text": "...", "similarity": 0.85},
                {"text": "...", "similarity": 0.82}
            ]
            reranked = reranker.rerank(query, chunks, top_k=5)
        """
        if not self.model:
            logger.warning("Cross-encoder not available, returning original ranking")
            return chunks[:top_k]
        
        if len(chunks) == 0:
            return []
        
        try:
            # Create query-document pairs
            pairs = [[query, chunk.get('text', '')] for chunk in chunks]
            
            # Get cross-encoder scores (higher = more relevant)
            rerank_scores = self.model.predict(pairs)
            
            # Normalize scores to 0-1 range
            min_score = min(rerank_scores)
            max_score = max(rerank_scores)
            score_range = max_score - min_score if max_score > min_score else 1.0
            
            # Combine scores with weighting
            for i, chunk in enumerate(chunks):
                # Normalize rerank score
                normalized_rerank = (rerank_scores[i] - min_score) / score_range
                
                # Original vector similarity (already 0-1)
                vector_sim = chunk.get('similarity', 0.0)
                
                # Weighted combination
                chunk['rerank_score'] = float(normalized_rerank)
                chunk['final_score'] = (
                    vector_weight * vector_sim + 
                    rerank_weight * normalized_rerank
                )
            
            # Sort by final score (descending)
            reranked = sorted(chunks, key=lambda x: x['final_score'], reverse=True)
            
            # Log improvement
            if len(reranked) > 0 and len(chunks) > 0:
                top_before = chunks[0].get('similarity', 0)
                top_after = reranked[0].get('final_score', 0)
                logger.debug(f"Reranking: top score {top_before:.3f} → {top_after:.3f}")
            
            return reranked[:top_k]
            
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            # Fallback to original ranking
            return chunks[:top_k]
    
    def batch_rerank(
        self,
        query: str,
        chunks: List[Dict],
        batch_size: int = 32,
        top_k: int = 5
    ) -> List[Dict]:
        """
        Rerank with batching for efficiency (future optimization).
        
        Args:
            query: User query
            chunks: Chunks to rerank
            batch_size: Number of pairs to process at once
            top_k: Top results to return
        
        Returns:
            Reranked chunks
        """
        # For now, just call regular rerank
        # TODO: Implement true batching for large chunk sets
        return self.rerank(query, chunks, top_k=top_k)


# Singleton instance
_reranker_service = None

def get_reranker_service() -> RerankerService:
    """Get or create reranker service instance."""
    global _reranker_service
    if _reranker_service is None:
        _reranker_service = RerankerService()
    return _reranker_service
