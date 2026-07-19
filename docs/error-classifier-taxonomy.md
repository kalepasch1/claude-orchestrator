# Error Classifier Taxonomy

## Overview

`runner/error_classifier.py` provides structured error classification so
that downstream consumers (auto-remediation, QA panels, daily brief) can
act on failure categories rather than parsing raw stderr.

## Usage

Modules that catch task failures should call `classify(stderr_text)` to
get a category string. Known categories include transient network errors,
build failures, test failures, and permission issues. Unrecognised errors
return `"unknown"` — the classifier never raises.

## Adding New Categories

1. Add the regex pattern and category name to the `_PATTERNS` list in
   `error_classifier.py`.
2. Order matters: more specific patterns should appear before general
   catch-alls.
3. Add a corresponding test case in `runner/tests/` to prevent regression.
