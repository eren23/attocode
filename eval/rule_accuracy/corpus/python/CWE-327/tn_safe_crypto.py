# Cryptography — true negatives (safe patterns)
# no-expect: These should NOT trigger weak crypto rules
import hashlib

def safe_sha256(data):
    return hashlib.sha256(data).hexdigest()

def safe_sha512(data):
    return hashlib.sha512(data).hexdigest()
