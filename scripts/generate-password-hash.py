#!/usr/bin/env python3
"""Generate bcrypt hash for Prometheus basic auth"""
from passlib.hash import bcrypt

password = "change_me_to_your_password"
hashed = bcrypt.hash(password)
print(f"Password: {password}")
print(f"Bcrypt hash: {hashed}")
