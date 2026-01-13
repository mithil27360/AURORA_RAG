"""
Aurora RAG Chatbot - Encryption Service

Security utilities for:
- PII encryption at rest
- Query anonymization
- Secure key rotation
- HMAC signature verification
"""

import base64
import hashlib
import hmac
import os
import secrets
import logging
from typing import Optional, Tuple
from datetime import datetime, timedelta
from functools import lru_cache
import json

logger = logging.getLogger(__name__)


# =============================================================================
# KEY MANAGEMENT
# =============================================================================

class KeyManager:
    """
    Manages encryption keys with rotation support.
    
    Keys are derived from a master secret using HKDF.
    Supports key versioning for smooth rotation.
    """
    
    def __init__(self, master_secret: str = None):
        # Use provided secret or generate from environment
        self._master_secret = master_secret or os.getenv("SECRET_KEY", "")
        
        if not self._master_secret or len(self._master_secret) < 32:
            logger.warning("Weak or missing SECRET_KEY - using generated key (not persistent!)")
            self._master_secret = secrets.token_hex(32)
        
        self._master_bytes = self._master_secret.encode()
        self._key_cache: dict = {}
        self._current_version = 1
    
    def derive_key(self, purpose: str, version: int = None) -> bytes:
        """
        Derive a purpose-specific key.
        
        Uses HKDF-like derivation for key separation.
        """
        version = version or self._current_version
        cache_key = f"{purpose}:{version}"
        
        if cache_key in self._key_cache:
            return self._key_cache[cache_key]
        
        # Simple key derivation using HMAC
        info = f"{purpose}:v{version}".encode()
        derived = hmac.new(self._master_bytes, info, hashlib.sha256).digest()
        
        self._key_cache[cache_key] = derived
        return derived
    
    def get_encryption_key(self, version: int = None) -> bytes:
        """Get key for data encryption."""
        return self.derive_key("encryption", version)
    
    def get_signing_key(self, version: int = None) -> bytes:
        """Get key for HMAC signing."""
        return self.derive_key("signing", version)
    
    def get_hash_key(self, version: int = None) -> bytes:
        """Get key for hashing (anonymization)."""
        return self.derive_key("hashing", version)
    
    def rotate_keys(self) -> int:
        """Rotate to new key version."""
        self._current_version += 1
        logger.info(f"Rotated to key version {self._current_version}")
        return self._current_version
    
    @property
    def current_version(self) -> int:
        return self._current_version


# =============================================================================
# ENCRYPTION / DECRYPTION
# =============================================================================

class DataEncryptor:
    """
    Simple symmetric encryption for sensitive data.
    
    Uses Fernet-like approach:
    - AES-256-CBC encryption
    - HMAC-SHA256 authentication
    - IV per message
    """
    
    def __init__(self, key_manager: KeyManager = None):
        self.key_manager = key_manager or KeyManager()
    
    def encrypt(self, plaintext: str, associated_data: str = None) -> str:
        """
        Encrypt plaintext and return base64 encoded ciphertext.
        
        Format: version:iv:ciphertext:tag
        """
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend
            
            # Get current key
            version = self.key_manager.current_version
            key = self.key_manager.get_encryption_key(version)
            
            # Generate IV
            iv = os.urandom(16)
            
            # Encrypt
            cipher = Cipher(
                algorithms.AES(key[:32]),
                modes.CBC(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            
            # Pad plaintext to block size
            plaintext_bytes = plaintext.encode()
            padding_len = 16 - (len(plaintext_bytes) % 16)
            padded = plaintext_bytes + bytes([padding_len] * padding_len)
            
            ciphertext = encryptor.update(padded) + encryptor.finalize()
            
            # Generate authentication tag
            sign_key = self.key_manager.get_signing_key(version)
            tag_data = iv + ciphertext
            if associated_data:
                tag_data += associated_data.encode()
            tag = hmac.new(sign_key, tag_data, hashlib.sha256).digest()[:16]
            
            # Encode result
            result = f"{version}:{base64.b64encode(iv).decode()}:{base64.b64encode(ciphertext).decode()}:{base64.b64encode(tag).decode()}"
            return result
            
        except ImportError:
            # Fallback: just base64 encode (not secure, for dev only)
            logger.warning("cryptography not installed - using base64 only (NOT SECURE)")
            return f"0:{base64.b64encode(plaintext.encode()).decode()}"
    
    def decrypt(self, encrypted: str, associated_data: str = None) -> Optional[str]:
        """
        Decrypt and verify ciphertext.
        
        Returns None if decryption fails.
        """
        try:
            parts = encrypted.split(":")
            version = int(parts[0])
            
            # Handle fallback encoding
            if version == 0:
                return base64.b64decode(parts[1]).decode()
            
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend
            
            iv = base64.b64decode(parts[1])
            ciphertext = base64.b64decode(parts[2])
            tag = base64.b64decode(parts[3])
            
            # Get keys
            key = self.key_manager.get_encryption_key(version)
            sign_key = self.key_manager.get_signing_key(version)
            
            # Verify tag
            tag_data = iv + ciphertext
            if associated_data:
                tag_data += associated_data.encode()
            expected_tag = hmac.new(sign_key, tag_data, hashlib.sha256).digest()[:16]
            
            if not hmac.compare_digest(tag, expected_tag):
                logger.warning("Authentication tag mismatch")
                return None
            
            # Decrypt
            cipher = Cipher(
                algorithms.AES(key[:32]),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            
            # Remove padding
            padding_len = padded[-1]
            plaintext = padded[:-padding_len]
            
            return plaintext.decode()
            
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return None


# =============================================================================
# HASHING / ANONYMIZATION
# =============================================================================

class DataAnonymizer:
    """
    Anonymize PII for analytics while preserving utility.
    
    Uses:
    - Keyed hashing for identifiers
    - Generalization for values
    - K-anonymity support
    """
    
    def __init__(self, key_manager: KeyManager = None):
        self.key_manager = key_manager or KeyManager()
    
    def hash_identifier(self, value: str, salt: str = "") -> str:
        """
        Create a consistent but irreversible hash of an identifier.
        
        Same value always produces same hash (with same key).
        """
        key = self.key_manager.get_hash_key()
        data = f"{salt}:{value}".encode()
        hash_val = hmac.new(key, data, hashlib.sha256).hexdigest()
        return hash_val[:16]  # Truncate for practical use
    
    def hash_ip(self, ip: str) -> str:
        """Hash IP address."""
        return self.hash_identifier(ip, "ip")
    
    def hash_user_id(self, user_id: str) -> str:
        """Hash user ID."""
        return self.hash_identifier(user_id, "user")
    
    def hash_session(self, session_id: str) -> str:
        """Hash session ID."""
        return self.hash_identifier(session_id, "session")
    
    def mask_ip(self, ip: str) -> str:
        """
        Mask IP address (last octet).
        
        192.168.1.100 -> 192.168.1.***
        """
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.***"
        return "***"
    
    def mask_email(self, email: str) -> str:
        """
        Mask email address.
        
        user@example.com -> u***@example.com
        """
        if "@" not in email:
            return "***"
        
        local, domain = email.rsplit("@", 1)
        if len(local) <= 1:
            return f"***@{domain}"
        return f"{local[0]}***@{domain}"
    
    def generalize_timestamp(self, timestamp: datetime, level: str = "hour") -> str:
        """
        Generalize timestamp to reduce precision.
        
        Levels: minute, hour, day, week, month
        """
        if level == "minute":
            return timestamp.strftime("%Y-%m-%d %H:%M")
        elif level == "hour":
            return timestamp.strftime("%Y-%m-%d %H:00")
        elif level == "day":
            return timestamp.strftime("%Y-%m-%d")
        elif level == "week":
            # ISO week
            return f"{timestamp.year}-W{timestamp.isocalendar()[1]:02d}"
        elif level == "month":
            return timestamp.strftime("%Y-%m")
        else:
            return timestamp.isoformat()
    
    def anonymize_record(self, record: dict, fields_to_hash: list = None, fields_to_mask: list = None) -> dict:
        """
        Anonymize a record by hashing/masking specified fields.
        """
        result = record.copy()
        fields_to_hash = fields_to_hash or []
        fields_to_mask = fields_to_mask or []
        
        for field in fields_to_hash:
            if field in result and result[field]:
                result[field] = self.hash_identifier(str(result[field]), field)
        
        for field in fields_to_mask:
            if field in result and result[field]:
                value = result[field]
                if "@" in str(value):
                    result[field] = self.mask_email(value)
                elif "." in str(value) and all(p.isdigit() for p in str(value).split(".")):
                    result[field] = self.mask_ip(value)
                else:
                    # Generic masking
                    result[field] = value[:2] + "***" if len(value) > 2 else "***"
        
        return result


# =============================================================================
# SIGNATURE VERIFICATION
# =============================================================================

class SignatureVerifier:
    """
    HMAC signature generation and verification.
    
    Used for:
    - API request signing
    - Webhook verification
    - Token validation
    """
    
    def __init__(self, key_manager: KeyManager = None):
        self.key_manager = key_manager or KeyManager()
    
    def sign(self, data: str, timestamp: int = None) -> Tuple[str, int]:
        """
        Sign data and return (signature, timestamp).
        """
        timestamp = timestamp or int(datetime.now().timestamp())
        key = self.key_manager.get_signing_key()
        
        message = f"{timestamp}:{data}".encode()
        signature = hmac.new(key, message, hashlib.sha256).hexdigest()
        
        return signature, timestamp
    
    def verify(self, data: str, signature: str, timestamp: int, max_age_seconds: int = 300) -> bool:
        """
        Verify signature and check timestamp freshness.
        """
        # Check timestamp freshness
        now = int(datetime.now().timestamp())
        if abs(now - timestamp) > max_age_seconds:
            logger.debug("Signature timestamp expired")
            return False
        
        # Recompute signature
        expected_sig, _ = self.sign(data, timestamp)
        
        # Constant-time comparison
        return hmac.compare_digest(signature, expected_sig)
    
    def sign_request(self, method: str, path: str, body: str = "") -> dict:
        """
        Generate signature headers for API request.
        """
        timestamp = int(datetime.now().timestamp())
        data = f"{method}:{path}:{body}"
        signature, _ = self.sign(data, timestamp)
        
        return {
            "X-Signature": signature,
            "X-Timestamp": str(timestamp)
        }
    
    def verify_request(self, method: str, path: str, body: str, signature: str, timestamp: str) -> bool:
        """
        Verify API request signature.
        """
        try:
            ts = int(timestamp)
            data = f"{method}:{path}:{body}"
            return self.verify(data, signature, ts)
        except:
            return False


# =============================================================================
# SECURE TOKEN GENERATION
# =============================================================================

class SecureTokenGenerator:
    """Generate secure tokens for various purposes."""
    
    @staticmethod
    def generate_session_id(length: int = 32) -> str:
        """Generate cryptographically secure session ID."""
        return secrets.token_urlsafe(length)
    
    @staticmethod
    def generate_api_key(prefix: str = "aurora") -> str:
        """Generate API key with prefix."""
        token = secrets.token_hex(24)
        return f"{prefix}_{token}"
    
    @staticmethod
    def generate_interaction_id() -> str:
        """Generate unique interaction ID."""
        import uuid
        return str(uuid.uuid4())
    
    @staticmethod
    def generate_password(length: int = 16, include_special: bool = True) -> str:
        """Generate secure random password."""
        import string
        
        chars = string.ascii_letters + string.digits
        if include_special:
            chars += "!@#$%^&*"
        
        # Ensure at least one of each type
        password = [
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.digits),
        ]
        
        if include_special:
            password.append(secrets.choice("!@#$%^&*"))
        
        # Fill rest
        password.extend(secrets.choice(chars) for _ in range(length - len(password)))
        
        # Shuffle
        import random
        random.shuffle(password)
        
        return ''.join(password)


# =============================================================================
# SINGLETON INSTANCES
# =============================================================================

@lru_cache()
def get_key_manager() -> KeyManager:
    """Get singleton key manager."""
    return KeyManager()


def get_encryptor() -> DataEncryptor:
    """Get encryptor instance."""
    return DataEncryptor(get_key_manager())


def get_anonymizer() -> DataAnonymizer:
    """Get anonymizer instance."""
    return DataAnonymizer(get_key_manager())


def get_verifier() -> SignatureVerifier:
    """Get signature verifier instance."""
    return SignatureVerifier(get_key_manager())
