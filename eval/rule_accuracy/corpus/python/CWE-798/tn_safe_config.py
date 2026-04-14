# Configuration — true negatives (safe patterns)
# no-expect: These should NOT trigger secret detection rules

import os

API_KEY = os.environ.get("API_KEY", "")
AWS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
DB_URL = os.environ["DATABASE_URL"]

# Placeholder / example values in comments and docs
# Example: AKIAIOSFODNN7EXAMPLE (this is AWS's official example key)

def get_config():
    return {
        "api_key": os.environ.get("API_KEY"),
        "debug": True,
    }
