# Hand-curated fixture for bandit-python pack rules.
# Tests B105 (hardcoded password) plus nearby unrelated code so we
# measure FP rate too.

import os


def boot_with_secret(api_key: str) -> None:
    """Real flow: read secret from env."""
    secret = os.environ.get("API_TOKEN", "")  # ok: B105-hardcoded-password
    if not secret:
        raise RuntimeError("API_TOKEN missing")


# --- BAD: rule MUST fire ---
api_key = "sk-1234567890abcdef"  # expect: B105-hardcoded-password
DATABASE_PASSWORD = "supersecret123"  # expect: B105-hardcoded-password


# --- GOOD: rule must NOT fire ---
PLACEHOLDER = "EXAMPLE_VALUE"  # ok: B105-hardcoded-password
api_key_var = "API_KEY"  # ok: B105-hardcoded-password — env var name, not value
