# Legal Radar V2 — Security Notes

## Input Validation

All legal inbox items must be validated against the expected schema
before processing. Untrusted input from external sources (email, API)
is sanitized prior to classification.

## Data Provenance

Only public-source data is permitted for automated analysis.
Non-public or privileged data requires explicit operator approval
before any processing pipeline may consume it.
