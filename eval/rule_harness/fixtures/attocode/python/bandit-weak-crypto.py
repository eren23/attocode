# Hand-curated fixture for bandit weak-crypto rules (B303, B324, B304).

import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def hash_user(user_id: str) -> str:
    """Modern hashing — SHA-256."""
    return hashlib.sha256(user_id.encode()).hexdigest()  # ok: B303-weak-md5


def hash_user_md5(user_id: str) -> str:
    return hashlib.md5(user_id.encode()).hexdigest()  # expect: B303-weak-md5


def hash_user_sha1(user_id: str) -> str:
    return hashlib.sha1(user_id.encode()).hexdigest()  # expect: B324-weak-sha1


def encrypt_aes(key: bytes, iv: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))  # ok: B304-weak-des
    encryptor = cipher.encryptor()
    return encryptor.update(data) + encryptor.finalize()
