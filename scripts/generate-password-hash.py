#!/usr/bin/env python3
"""Generate bcrypt hash for Prometheus basic auth"""
from passlib.hash import bcrypt

password = "aurora_prometheus_2025"
hashed = bcrypt.hash(password)
print(f"Password: {password}")
print(f"Bcrypt hash: {hashed}")
