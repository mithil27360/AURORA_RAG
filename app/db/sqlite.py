
import sqlite3
import json
import logging
import uuid
import asyncio
import shutil
import os
from datetime import datetime
from typing import List, Dict, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class InteractionLogger:
    def __init__(self, db_path: str = str(settings.DB_PATH)):
        self.db_path = db_path
        self.backup_dir = settings.BASE_DIR / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        self._create_backup("startup")  # Backup on every startup
        self._init_db()
    
    def _create_backup(self, reason: str = "manual"):
        """Create a timestamped backup of the database"""
        try:
            if not os.path.exists(self.db_path):
                return None
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"interactions_backup_{timestamp}_{reason}.db"
            backup_path = self.backup_dir / backup_name
            
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"Created backup: {backup_name}")
            
            # Keep only last 10 backups
            self._cleanup_old_backups()
            return str(backup_path)
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return None
    
    def _cleanup_old_backups(self, keep: int = 10):
        """Keep only the most recent backups"""
        try:
            backups = sorted(self.backup_dir.glob("interactions_backup_*.db"), reverse=True)
            for old_backup in backups[keep:]:
                old_backup.unlink()
                logger.info(f"Removed old backup: {old_backup.name}")
        except Exception as e:
            logger.warning(f"Backup cleanup failed: {e}")
    
    def _init_db(self):
        """Initialize SQLite database with WAL mode for high concurrency."""
        try:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            c = conn.cursor()
            
            # SQLite performance optimizations
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.execute("PRAGMA cache_size=10000")
            c.execute("PRAGMA temp_store=MEMORY")
            
            # Main interactions table
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
                    ip_hash TEXT,
                    feedback TEXT,
                    client_data TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Migration: Add client_data column if not exists
            try:
                c.execute("ALTER TABLE interactions ADD COLUMN client_data TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Temporary IP storage (for abuse detection, auto-cleaned after 48h)
            c.execute('''
                CREATE TABLE IF NOT EXISTS temp_ip_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT NOT NULL,
                    ip_hash TEXT NOT NULL,
                    interaction_id TEXT,
                    is_blocked INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Clean old temporary IPs (older than 48 hours)
            c.execute('''
                DELETE FROM temp_ip_log 
                WHERE created_at < datetime('now', '-48 hours')
            ''')
            
            # Add columns if missing (migration)
            for col, col_type in [('ip_hash', 'TEXT'), ('feedback', 'TEXT')]:
                try:
                    c.execute(f'ALTER TABLE interactions ADD COLUMN {col} {col_type}')
                except sqlite3.OperationalError:
                    pass  # Column already exists
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB Init failed: {e}")

    def log_interaction_sync(self, **kwargs):
        """Synchronous logging function to be run in executor"""
        try:
            interaction_id = kwargs.get("interaction_id", str(uuid.uuid4()))
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Prepare data
            retrieved_docs = kwargs.get("retrieved_docs", [])
            doc_ids = json.dumps([d.get('id', 'unknown') for d in retrieved_docs])
            scores = json.dumps([d.get('distance', 0.0) for d in retrieved_docs])
            used_docs_json = json.dumps(kwargs.get("used_docs", []))
            
            c.execute('''
                INSERT INTO interactions 
                (interaction_id, timestamp, user_id, query_text, detected_intent,
                 retrieved_doc_ids, retrieval_scores, answer, confidence_score,
                 response_type, used_doc_ids, llm_model, response_time_ms, cached,
                 device_type, browser, os, ip_hash, client_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                interaction_id,
                datetime.now().isoformat(),
                kwargs.get("user_id", "anonymous"),
                kwargs.get("query", ""),
                kwargs.get("intent", ""),
                doc_ids,
                scores,
                kwargs.get("answer", ""),
                kwargs.get("confidence", 0.0),
                kwargs.get("response_type", ""),
                used_docs_json,
                "llama-3.3-70b-versatile",
                kwargs.get("response_time_ms", 0.0),
                1 if kwargs.get("cached", False) else 0,
                kwargs.get("device_type"),
                kwargs.get("browser"),
                kwargs.get("os"),
                kwargs.get("ip_hash"),
                json.dumps(kwargs.get("client_data")) if kwargs.get("client_data") else None
            ))
            conn.commit()
            conn.close()
            return interaction_id
        except Exception as e:
            logger.error(f"Logging failed: {e}")
            return None
    
    def log_temp_ip_sync(self, ip_address: str, ip_hash: str, interaction_id: str, is_blocked: bool = False):
        """Log raw IP temporarily for abuse detection (auto-deleted after 48h)"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                INSERT INTO temp_ip_log (ip_address, ip_hash, interaction_id, is_blocked)
                VALUES (?, ?, ?, ?)
            ''', (ip_address, ip_hash, interaction_id, 1 if is_blocked else 0))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Temp IP log failed: {e}")
    
    async def log_temp_ip(self, ip_address: str, ip_hash: str, interaction_id: str, is_blocked: bool = False):
        """Async wrapper for temp IP logging"""
        await asyncio.to_thread(self.log_temp_ip_sync, ip_address, ip_hash, interaction_id, is_blocked)
    
    def update_feedback_sync(self, interaction_id: str, feedback: str):
        """Update feedback for an interaction (helpful/not_helpful)"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('UPDATE interactions SET feedback = ? WHERE interaction_id = ?', (feedback, interaction_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Feedback update failed: {e}")
            return False
    
    async def update_feedback(self, interaction_id: str, feedback: str):
        """Async wrapper for feedback update"""
        return await asyncio.to_thread(self.update_feedback_sync, interaction_id, feedback)

    async def log_interaction(self, **kwargs):
        """Async wrapper for logging (non-blocking)"""
        await asyncio.to_thread(self.log_interaction_sync, **kwargs)

    async def get_analytics_summary(self):
        """Get aggregate stats for dashboard"""
        return await asyncio.to_thread(self._sync_get_analytics)

    def _sync_get_analytics(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            # 1. Basic Stats
            c.execute('''
                SELECT 
                    COUNT(*) as total,
                    AVG(response_time_ms) as avg_time,
                    AVG(confidence_score) as avg_conf,
                    SUM(CASE WHEN cached=1 THEN 1 ELSE 0 END) as cache_hits,
                    SUM(CASE WHEN confidence_score < 0.5 THEN 1 ELSE 0 END) as low_conf_count
                FROM interactions
            ''')
            row = c.fetchone()
            total = row['total'] or 0
            
            # 2. Top Intents
            c.execute('''
                SELECT detected_intent, COUNT(*) as count 
                FROM interactions 
                GROUP BY detected_intent 
                ORDER BY count DESC 
                LIMIT 5
            ''')
            top_intents = {r['detected_intent'] or 'unknown': r['count'] for r in c.fetchall()}
            
            # 3. Recent Queries (include feedback)
            c.execute('''
                SELECT timestamp, query_text as query, detected_intent as intent, 
                       confidence_score as confidence, cached, response_time_ms, feedback
                FROM interactions 
                ORDER BY created_at DESC 
                LIMIT 10
            ''')
            recent = [dict(r) for r in c.fetchall()]
            
            # 4. Feedback counts
            c.execute('''
                SELECT 
                    SUM(CASE WHEN feedback='helpful' THEN 1 ELSE 0 END) as thumbs_up,
                    SUM(CASE WHEN feedback='not_helpful' THEN 1 ELSE 0 END) as thumbs_down
                FROM interactions
            ''')
            fb_row = c.fetchone()
            
            conn.close()
            
            # Calculate derived stats
            hit_rate = (row['cache_hits'] / total * 100) if total > 0 else 0
            
            return {
                "legacy_analytics": {
                    "total_queries": total,
                    "avg_response_time": row['avg_time'] or 0,
                    "recent_queries": recent
                },
                "cache_stats": {
                    "cache_hit_rate": round(hit_rate, 1),
                    "api_calls_saved": row['cache_hits'] or 0,
                    "cache_hits": row['cache_hits'] or 0,
                    "cache_size": total # Approximation
                },
                "production_stats": {
                    "avg_confidence": row['avg_conf'] or 0,
                    "low_confidence_count": row['low_conf_count'] or 0,
                    "top_intents": top_intents
                },
                "feedback_stats": {
                    "thumbs_up": fb_row['thumbs_up'] or 0,
                    "thumbs_down": fb_row['thumbs_down'] or 0
                }
            }
        except Exception as e:
            logger.error(f"Analytics query failed: {e}")
            return {}

    async def get_all_interactions(self, limit: int = 1000):
        return await asyncio.to_thread(self._sync_get_all, limit)

    def _sync_get_all(self, limit):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            # LEFT JOIN with temp_ip_log to get real IP (available for 24hrs)
            c.execute('''
                SELECT i.*, t.ip_address as real_ip
                FROM interactions i
                LEFT JOIN temp_ip_log t ON i.interaction_id = t.interaction_id
                ORDER BY i.created_at DESC 
                LIMIT ?
            ''', (limit,))
            rows = [dict(r) for r in c.fetchall()]
            conn.close()
            return rows
        except Exception as e:
            logger.error(f"Fetch all failed: {e}")
            return []

# Singleton
logger_instance = None

def get_logger():
    global logger_instance
    if logger_instance is None:
        logger_instance = InteractionLogger()
    return logger_instance
