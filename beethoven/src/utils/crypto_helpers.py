"""Cryptographic helper utilities."""
import os


def generate_secure_random_bytes(length: int) -> bytes:
    """Generate cryptographically secure random bytes of the given length.

    This function utilizes a cryptographically secure pseudo-random
    number generator (CSPRNG) suitable for security-sensitive contexts.
    """
    if length <= 0:
        raise ValueError("length must be positive")
    return os.urandom(length)
