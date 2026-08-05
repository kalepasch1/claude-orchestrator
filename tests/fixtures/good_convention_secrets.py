"""
Good convention example: Secrets handled via environment variables.

This module follows the convention: "DO NOT introduce hardcoded secrets or
credentials. Use environment variables instead."
"""
import os


# OK: Environment variable reference with default
api_token = os.environ.get("API_TOKEN", "")

# OK: Environment variable reference with .env pattern
database_password = os.getenv("DATABASE_PASSWORD", "")

# OK: Placeholder for env var
temp_secret = "${API_KEY}"

# OK: Config from environment
config = {
    "db_host": os.environ.get("DB_HOST", "localhost"),
    "db_user": os.environ.get("DB_USER", "admin"),
    # Note: Actual password loaded from env, not hardcoded
    "db_password": os.environ.get("DB_PASSWORD"),
}

# OK: Non-sensitive data
app_name = "MyApp"
version = "1.0.0"
api_endpoint = "https://api.example.com"
timeout_seconds = 30
max_retries = 3

# OK: Constants for public data
DEFAULT_BATCH_SIZE = 100
SUPPORTED_FORMATS = ["json", "yaml", "xml"]
