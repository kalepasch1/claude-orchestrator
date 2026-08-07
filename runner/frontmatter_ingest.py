#!/usr/bin/env python3
"""
frontmatter_ingest.py - YAML frontmatter parsing + directory ingestion for the
merged-diff memory system (dropbox spec group-13, consolidated 63cf995).

parse_frontmatter_and_body(content) splits `---`-delimited YAML frontmatter
from the body and parses both as YAML; process_directory_of_files(directory)
walks a tree, ingests whitelisted files, and returns per-file results plus a
metadata summary. File access errors are logged and counted, never raised.
"""
import logging
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".md", ".yaml", ".yml", ".txt"}


def parse_frontmatter_and_body(content):
    """Split and parse `---`-delimited YAML frontmatter and YAML body.

    Returns {"frontmatter": dict|None, "body": <any YAML type>}.
    - no leading `---` (or no closing `---`): whole content is body
    - YAML errors in either section raise ValueError (caller decides policy)
    """
    if not isinstance(content, str):
        raise ValueError("parse_frontmatter_and_body: content must be a string")

    frontmatter_text = None
    body_text = content
    if content.startswith("---"):
        first_newline = content.find("\n")
        rest = content[first_newline + 1:] if first_newline != -1 else ""
        closing = rest.find("\n---")
        if rest.startswith("---"):
            frontmatter_text, body_text = "", rest[3:]
        elif closing != -1:
            frontmatter_text = rest[:closing]
            after = rest[closing + len("\n---"):]
            body_text = after[after.find("\n") + 1:] if "\n" in after else ""

    try:
        frontmatter = yaml.safe_load(frontmatter_text) if frontmatter_text is not None else None
        if frontmatter is not None and not isinstance(frontmatter, dict):
            raise ValueError(f"frontmatter is not a mapping: {type(frontmatter).__name__}")
        body = yaml.safe_load(body_text) if body_text.strip() else None
    except yaml.YAMLError as e:
        raise ValueError(f"YAML parse failure: {e}") from e

    return {"frontmatter": frontmatter, "body": body}


def process_directory_of_files(directory):
    """Recursively ingest whitelisted files under `directory`.

    Returns {relative_path: {"frontmatter":..., "body":...} | {"error": str},
    plus "metadata": {"succeeded": n, "failed": n, "skipped": n}}.
    Access/decode/parse errors are logged as warnings and recorded per-file;
    nothing is silently dropped and nothing raises.
    """
    directory = Path(directory)
    results = {}
    succeeded = failed = skipped = 0

    if not directory.is_dir():
        log.warning("process_directory_of_files: %s is not a directory", directory)
        results["metadata"] = {"succeeded": 0, "failed": 0, "skipped": 0}
        return results

    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            skipped += 1
            continue
        rel = str(path.relative_to(directory))
        try:
            content = path.read_text(encoding="utf-8")
            results[rel] = parse_frontmatter_and_body(content)
            succeeded += 1
        except (OSError, UnicodeDecodeError, ValueError) as e:
            log.warning("frontmatter ingest failed for %s: %s", rel, e)
            results[rel] = {"error": str(e)}
            failed += 1

    results["metadata"] = {"succeeded": succeeded, "failed": failed, "skipped": skipped}
    return results
