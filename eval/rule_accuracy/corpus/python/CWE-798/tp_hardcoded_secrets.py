# Hardcoded secrets — true positives for rule accuracy testing
# nosec — INTENTIONALLY insecure test corpus

API_KEY = "sk-proj-abc123def456ghi789jkl012"  # expect: security/openai_key
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # expect: security/aws_access_key
GITHUB_TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"  # expect: security/github_token
SLACK_WEBHOOK = "https://hooks.slack.com/services/T0123456/B0123456/xxxxxxxxxxx"  # expect: security/slack_webhook
JWT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"  # expect: security/jwt_token

def get_db():
    conn = "postgresql://admin:supersecret@db.example.com:5432/prod"  # expect: security/password_assignment
    return conn
