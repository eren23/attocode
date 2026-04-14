# Random — true negatives (safe patterns)
# no-expect: These should NOT trigger weak random rules
import secrets

def safe_token():
    return secrets.token_hex(32)

def safe_otp():
    return secrets.randbelow(900000) + 100000
