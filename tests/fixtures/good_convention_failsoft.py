"""
Good convention example: Fail-soft error handling.

This module follows the fail-soft convention: "Return empty string "" or
sensible defaults on any error; never raise on bad input"
"""


def read_file(path):
    """OK: Returns empty string on FileNotFoundError."""
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def load_json_config(path):
    """OK: Returns empty dict on parse error."""
    try:
        import json
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def get_items_list():
    """OK: Returns empty list on error."""
    try:
        return load_items()
    except Exception:
        return []


def parse_number(text):
    """OK: Returns None on parse failure."""
    try:
        return int(text)
    except (ValueError, TypeError):
        return None


def fetch_data_from_api(url):
    """OK: Returns empty string on network error."""
    try:
        import requests
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.text
    except Exception:
        return ""
