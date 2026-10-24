"""Password hashing for console users: scrypt from the standard library, one string to store."""

import hashlib
import hmac
import os


def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(plain.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(plain.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate.hex(), digest)
