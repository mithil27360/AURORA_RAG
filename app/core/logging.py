"""
Aurora RAG Chatbot - Structured Logging Service

JSON logging with request IDs, sensitive data masking, and rotation.
"""

import json
import logging
import sys
import time
import traceback
import re
from datetime import datetime
from typing import Any, Dict, Optional, Union
from contextvars import ContextVar
from pathlib import Path
from functools import wraps
import asyncio

# Context variable for request-scoped data
request_context: ContextVar[Dict[str, Any]] = ContextVar("request_context", default={})


# =============================================================================
# SENSITIVE DATA MASKING
# =============================================================================

class SensitiveDataMasker:
    """Mask sensitive data in log messages."""
    
    PATTERNS = [
        # API Keys
        (r'(api[_-]?key["\s:=]+)["\']?([a-zA-Z0-9_-]{20,})["\']?', r'\1***REDACTED***'),
        (r'(bearer\s+)([a-zA-Z0-9_.-]+)', r'\1***REDACTED***'),
        
        # Passwords
        (r'(password["\s:=]+)["\']?([^"\'\s,}]+)["\']?', r'\1***REDACTED***'),
        (r'(secret["\s:=]+)["\']?([^"\'\s,}]+)["\']?', r'\1***REDACTED***'),
        
        # Email (partial mask)
        (r'([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', r'***@\2'),
        
        # Phone numbers
        (r'\b(\d{3})[-.]?(\d{3})[-.]?(\d{4})\b', r'\1***\3'),
        
        # IP addresses (last octet masked)
        (r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}\b', r'\1***'),
        
        # Credit card numbers
        (r'\b(\d{4})[\s-]?(\d{4})[\s-]?(\d{4})[\s-]?(\d{4})\b', r'\1-****-****-\4'),
        
        # JWT tokens
        (r'(eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*)', r'***JWT_REDACTED***'),
    ]
    
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), replacement)
            for pattern, replacement in self.PATTERNS
        ]
    
    def mask(self, message: str) -> str:
        """Mask sensitive data in message."""
        if not self.enabled or not message:
            return message
        
        result = message
        for pattern, replacement in self.compiled_patterns:
            result = pattern.sub(replacement, result)
        
        return result
    
    def mask_dict(self, data: Dict) -> Dict:
        """Recursively mask sensitive data in dictionary."""
        if not self.enabled:
            return data
        
        masked = {}
        sensitive_keys = {'password', 'secret', 'token', 'api_key', 'apikey', 'key', 'auth'}
        
        for key, value in data.items():
            key_lower = key.lower()
            
            if any(s in key_lower for s in sensitive_keys):
                masked[key] = "***REDACTED***"
            elif isinstance(value, dict):
                masked[key] = self.mask_dict(value)
            elif isinstance(value, str):
                masked[key] = self.mask(value)
            else:
                masked[key] = value
        
        return masked


# =============================================================================
# JSON FORMATTER
# =============================================================================

class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.
    
    Output format:
    {
        "timestamp": "2025-01-10T12:30:45.123Z",
        "level": "INFO",
        "logger": "app.services.llm",
        "message": "LLM request completed",
        "request_id": "abc123",
        "duration_ms": 150.5,
        "extra": {...}
    }
    """
    
    def __init__(self, masker: Optional[SensitiveDataMasker] = None):
        super().__init__()
        self.masker = masker or SensitiveDataMasker()
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Base log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": self.masker.mask(record.getMessage()),
        }
        
        # Add request context if available
        ctx = request_context.get()
        if ctx:
            log_entry["request_id"] = ctx.get("request_id")
            log_entry["user_id"] = ctx.get("user_id")
            log_entry["ip"] = ctx.get("ip")
        
        # Add location info
        log_entry["location"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        # Add extra fields
        standard_attrs = {
            'name', 'msg', 'args', 'created', 'filename', 'funcName',
            'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'pathname', 'process', 'processName', 'relativeCreated',
            'stack_info', 'exc_info', 'exc_text', 'thread', 'threadName',
            'message', 'taskName'
        }
        
        extra = {}
        for key, value in record.__dict__.items():
            if key not in standard_attrs:
                try:
                    # Ensure value is JSON serializable
                    json.dumps(value)
                    extra[key] = value
                except (TypeError, ValueError):
                    extra[key] = str(value)
        
        if extra:
            log_entry["extra"] = self.masker.mask_dict(extra)
        
        return json.dumps(log_entry)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter for development."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def __init__(self, use_colors: bool = True, masker: Optional[SensitiveDataMasker] = None):
        super().__init__()
        self.use_colors = use_colors
        self.masker = masker or SensitiveDataMasker()
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as readable text."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        level = record.levelname
        
        # Add color
        if self.use_colors and level in self.COLORS:
            level = f"{self.COLORS[level]}{level:8}{self.RESET}"
        else:
            level = f"{level:8}"
        
        # Request ID from context
        ctx = request_context.get()
        request_id = ctx.get("request_id", "")[:8] if ctx else ""
        
        message = self.masker.mask(record.getMessage())
        
        # Base format
        output = f"{timestamp} | {level} | {record.name:30} | {message}"
        
        if request_id:
            output = f"{timestamp} | {level} | [{request_id}] | {record.name:25} | {message}"
        
        # Add exception if present
        if record.exc_info:
            output += "\n" + "".join(traceback.format_exception(*record.exc_info))
        
        return output


# =============================================================================
# LOGGER FACTORY
# =============================================================================

class LoggerFactory:
    """Factory for creating configured loggers."""
    
    _initialized = False
    _root_handler = None
    _file_handler = None
    _masker = SensitiveDataMasker()
    
    @classmethod
    def initialize(
        cls,
        level: str = "INFO",
        format_type: str = "json",  # "json" or "text"
        log_file: Optional[str] = None,
        use_colors: bool = True,
        mask_sensitive: bool = True
    ) -> None:
        """Initialize logging configuration."""
        if cls._initialized:
            return
        
        cls._masker = SensitiveDataMasker(enabled=mask_sensitive)
        
        # Get root logger
        root = logging.getLogger()
        root.setLevel(getattr(logging, level.upper()))
        
        # Remove existing handlers
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        
        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))
        
        if format_type == "json":
            console_handler.setFormatter(JSONFormatter(cls._masker))
        else:
            console_handler.setFormatter(TextFormatter(use_colors, cls._masker))
        
        root.addHandler(console_handler)
        cls._root_handler = console_handler
        
        # Create file handler if specified
        if log_file:
            cls._setup_file_handler(log_file, level, format_type)
        
        cls._initialized = True
    
    @classmethod
    def _setup_file_handler(cls, log_file: str, level: str, format_type: str) -> None:
        """Setup file handler with rotation."""
        from logging.handlers import RotatingFileHandler
        
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5
        )
        file_handler.setLevel(getattr(logging, level.upper()))
        
        # Always use JSON for file logs
        file_handler.setFormatter(JSONFormatter(cls._masker))
        
        logging.getLogger().addHandler(file_handler)
        cls._file_handler = file_handler
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """Get a configured logger instance."""
        if not cls._initialized:
            cls.initialize()
        
        return logging.getLogger(name)
    
    @classmethod
    def set_level(cls, level: str, logger_name: Optional[str] = None) -> None:
        """Set log level for a specific logger or root."""
        target = logging.getLogger(logger_name) if logger_name else logging.getLogger()
        target.setLevel(getattr(logging, level.upper()))


# =============================================================================
# CONTEXT MANAGERS
# =============================================================================

class LogContext:
    """Context manager for request-scoped logging."""
    
    def __init__(self, **kwargs):
        self.context = kwargs
        self.token = None
    
    def __enter__(self):
        current = request_context.get().copy()
        current.update(self.context)
        self.token = request_context.set(current)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            request_context.reset(self.token)
    
    async def __aenter__(self):
        return self.__enter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)


# =============================================================================
# TIMING DECORATOR
# =============================================================================

def log_timing(
    logger: Optional[logging.Logger] = None,
    level: int = logging.DEBUG,
    message: str = "Operation completed"
):
    """Decorator to log function execution time."""
    def decorator(func):
        nonlocal logger
        if logger is None:
            logger = logging.getLogger(func.__module__)
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration = (time.perf_counter() - start) * 1000
                logger.log(level, message, extra={
                    "function": func.__name__,
                    "duration_ms": round(duration, 2),
                    "success": True
                })
                return result
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                logger.log(logging.ERROR, f"{message} (failed)", extra={
                    "function": func.__name__,
                    "duration_ms": round(duration, 2),
                    "success": False,
                    "error": str(e)
                })
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration = (time.perf_counter() - start) * 1000
                logger.log(level, message, extra={
                    "function": func.__name__,
                    "duration_ms": round(duration, 2),
                    "success": True
                })
                return result
            except Exception as e:
                duration = (time.perf_counter() - start) * 1000
                logger.log(logging.ERROR, f"{message} (failed)", extra={
                    "function": func.__name__,
                    "duration_ms": round(duration, 2),
                    "success": False,
                    "error": str(e)
                })
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================================================
# AUDIT LOGGER
# =============================================================================

class AuditLogger:
    """
    Specialized logger for security and compliance auditing.
    
    Records security-relevant events with structured data
    for compliance and forensic analysis.
    """
    
    def __init__(self, logger_name: str = "audit"):
        self.logger = LoggerFactory.get_logger(f"audit.{logger_name}")
    
    def log_authentication(
        self,
        user_id: str,
        action: str,  # "login", "logout", "failed_login", "token_refresh"
        ip: str,
        user_agent: str,
        success: bool,
        reason: Optional[str] = None
    ) -> None:
        """Log authentication event."""
        self.logger.info(
            f"Authentication: {action}",
            extra={
                "event_type": "authentication",
                "user_id": user_id,
                "action": action,
                "ip": ip,
                "user_agent": user_agent,
                "success": success,
                "reason": reason
            }
        )
    
    def log_authorization(
        self,
        user_id: str,
        resource: str,
        action: str,
        allowed: bool,
        reason: Optional[str] = None
    ) -> None:
        """Log authorization decision."""
        self.logger.info(
            f"Authorization: {action} on {resource}",
            extra={
                "event_type": "authorization",
                "user_id": user_id,
                "resource": resource,
                "action": action,
                "allowed": allowed,
                "reason": reason
            }
        )
    
    def log_abuse(
        self,
        ip: str,
        user_id: Optional[str],
        query: str,
        abuse_type: str,
        score: int,
        action_taken: str
    ) -> None:
        """Log abuse detection event."""
        self.logger.warning(
            f"Abuse detected: {abuse_type}",
            extra={
                "event_type": "abuse",
                "ip": ip,
                "user_id": user_id,
                "query": query[:100],  # Truncate
                "abuse_type": abuse_type,
                "score": score,
                "action_taken": action_taken
            }
        )
    
    def log_data_access(
        self,
        user_id: str,
        data_type: str,
        action: str,  # "read", "create", "update", "delete"
        record_ids: list,
        success: bool
    ) -> None:
        """Log data access event."""
        self.logger.info(
            f"Data access: {action} {data_type}",
            extra={
                "event_type": "data_access",
                "user_id": user_id,
                "data_type": data_type,
                "action": action,
                "record_count": len(record_ids),
                "success": success
            }
        )


# =============================================================================
# PERFORMANCE LOGGER
# =============================================================================

class PerformanceLogger:
    """Logger for performance metrics and SLA tracking."""
    
    def __init__(self, logger_name: str = "performance"):
        self.logger = LoggerFactory.get_logger(f"perf.{logger_name}")
    
    def log_request(
        self,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> None:
        """Log request performance."""
        level = logging.INFO if status_code < 400 else logging.WARNING
        
        self.logger.log(
            level,
            f"{method} {path} - {status_code}",
            extra={
                "event_type": "request",
                "request_id": request_id,
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 2),
                "user_id": user_id,
                **(metadata or {})
            }
        )
    
    def log_llm_call(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        duration_ms: float,
        success: bool,
        cached: bool = False
    ) -> None:
        """Log LLM API call."""
        self.logger.info(
            f"LLM call: {model}",
            extra={
                "event_type": "llm_call",
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "total_tokens": tokens_in + tokens_out,
                "duration_ms": round(duration_ms, 2),
                "success": success,
                "cached": cached
            }
        )
    
    def log_vector_search(
        self,
        query_length: int,
        results_count: int,
        top_score: float,
        duration_ms: float
    ) -> None:
        """Log vector search performance."""
        self.logger.debug(
            "Vector search",
            extra={
                "event_type": "vector_search",
                "query_length": query_length,
                "results_count": results_count,
                "top_score": round(top_score, 4),
                "duration_ms": round(duration_ms, 2)
            }
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    return LoggerFactory.get_logger(name)


def set_request_context(**kwargs) -> None:
    """Set request context for logging."""
    current = request_context.get().copy()
    current.update(kwargs)
    request_context.set(current)


def clear_request_context() -> None:
    """Clear request context."""
    request_context.set({})
