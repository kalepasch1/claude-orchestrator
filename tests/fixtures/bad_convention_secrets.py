"""
Bad convention example: Hardcoded secrets without environment variable indirection.

This module violates the hardcoded secrets convention.
CLAUDE.md states: "DO NOT introduce hardcoded secrets or credentials in
the configuration keys. Use environment variables instead."
"""
import os


# VIOLATION: Hardcoded API token
api_token = "sk-1234567890abcdef"

# VIOLATION: Hardcoded database password
db_password = "mysql-root-password-123"

# VIOLATION: Hardcoded secret in config dict
config = {
    "DB_HOST": "localhost",
    "DATABASE_PASSWORD": "secret123",  # VIOLATION
    "API_SECRET": "hidden-value",      # VIOLATION
}

# VIOLATION: Private key assignment
private_key = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQE..."

# OK: Environment variable reference
user_token = os.environ.get("USER_TOKEN")

# OK: Placeholder
temp_secret = "$API_KEY"

# OK: Non-secret data
database_host = "localhost"
api_endpoint = "https://api.example.com"
