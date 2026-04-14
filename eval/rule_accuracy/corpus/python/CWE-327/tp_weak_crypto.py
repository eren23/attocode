# Weak cryptography — true positives for rule accuracy testing
import hashlib

def bad_md5(data):
    return hashlib.md5(data).hexdigest()  # expect: security/python_weak_hash

def bad_sha1(data):
    return hashlib.sha1(data).hexdigest()  # expect: security/python_weak_hash
