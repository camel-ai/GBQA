"""Lightweight symmetric encryption for sandbox-internal env passing.

Uses only the Python standard library (HMAC-SHA256 keystream + XOR).
The key is stored in a separate file with 0o600 permissions.
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import json
import os
import secrets
from pathlib import Path


def _derive_key(password: bytes, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password, salt, 100_000, dklen=32)


def _make_keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Generate a keystream using HMAC-SHA256 in counter mode."""
    keystream = bytearray()
    counter = 0
    while len(keystream) < length:
        block = hmac.new(
            key, nonce + counter.to_bytes(4, "big"), hashlib.sha256
        ).digest()
        keystream.extend(block)
        counter += 1
    return bytes(keystream[:length])


def encrypt(data: dict[str, str], password: bytes) -> str:
    """Encrypt a dict to a url-safe base64 token."""
    plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = _derive_key(password, salt)
    keystream = _make_keystream(key, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream))
    return base64.urlsafe_b64encode(salt + nonce + ciphertext).decode("ascii")


def decrypt(token: str, password: bytes) -> dict[str, str]:
    """Decrypt a url-safe base64 token back to a dict."""
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    salt = raw[:16]
    nonce = raw[16:32]
    ciphertext = raw[32:]
    key = _derive_key(password, salt)
    keystream = _make_keystream(key, nonce, len(ciphertext))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream))
    return json.loads(plaintext.decode("utf-8"))


def generate_key() -> bytes:
    """Generate a random 32-byte key and return it."""
    return secrets.token_bytes(32)
