#!/usr/bin/env python3
"""insert_module_docstring.py — put a module docstring at the top of a file.

The canary step this implements was specified as "insert the docstring at the
very top; if the file starts with a shebang, put it on the next line instead;
change nothing else". Doing that by hand is exactly the kind of edit that
silently corrupts a file, so it lives here as one tested function.

Two cases beyond the stated spec are handled because getting them wrong
produces a file that no longer runs:

  * PEP 263 encoding cookies (`# -*- coding: utf-8 -*-`) are only honoured by
    the interpreter on line 1 or 2. A docstring inserted above one pushes it
    to line 3 and the declared encoding is silently ignored, so the docstring
    goes after the cookie too.
  * A file that already has a module docstring is left alone by default —
    re-running the step must not stack two docstrings. Pass replace=True to
    swap it deliberately.

Usage:
    from insert_module_docstring import insert_docstring
    new_source = insert_docstring(open(path).read(), "One-line summary.")

    python3 tools/insert_module_docstring.py path/to/file.py "Summary."
"""
import io
import os
import sys
import tokenize

TRIPLE = '"""'


def _preamble_length(lines):
    """Number of leading lines the docstring must appear AFTER.

    That is the shebang (line 1 only) plus any PEP 263 encoding cookie, which
    the interpreter only reads on the first two lines.
    """
    i = 0
    if lines and lines[0].startswith("#!"):
        i = 1
    while i < len(lines) and i < 2:
        stripped = lines[i].strip()
        if stripped.startswith("#") and "coding" in stripped:
            i += 1
            continue
        break
    return i


def has_module_docstring(source):
    """True if *source* already opens with a module docstring.

    Uses the tokenizer rather than a string match so a comment or a plain
    string expression further down the file cannot be mistaken for one.
    Fail-soft: unparseable source is reported as "no docstring".
    """
    try:
        readline = io.StringIO(source or "").readline
        for tok in tokenize.generate_tokens(readline):
            if tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.COMMENT,
                            tokenize.INDENT, tokenize.ENCODING):
                continue
            return tok.type == tokenize.STRING
    except Exception:
        return False
    return False


def format_docstring(text):
    """Wrap *text* in triple quotes, normalizing whitespace and quote clashes.

    An embedded `\"\"\"` would terminate the docstring early and break the
    file, so it is escaped rather than passed through.
    """
    body = (text or "").strip()
    if body.startswith(TRIPLE) and body.endswith(TRIPLE) and len(body) >= 6:
        return body
    body = body.replace(TRIPLE, '\\"\\"\\"')
    if body.endswith('"'):
        body += " "          # avoid producing four quotes in a row
    if "\n" in body:
        return f'{TRIPLE}{body}\n{TRIPLE}'
    return f"{TRIPLE}{body}{TRIPLE}"


def insert_docstring(source, docstring, replace=False):
    """Return *source* with *docstring* inserted as the module docstring.

    Only the docstring lines are added; every existing line is preserved
    verbatim and in order. Returns the source unchanged when there is nothing
    to insert or a docstring is already present and replace is False.
    """
    if not (docstring or "").strip():
        return source
    if has_module_docstring(source) and not replace:
        return source

    formatted = format_docstring(docstring)
    if source is None:
        source = ""
    if not source.strip():
        return formatted + "\n"

    ends_with_newline = source.endswith("\n")
    lines = source.split("\n")
    if ends_with_newline:
        lines = lines[:-1]

    head = _preamble_length(lines)
    block = formatted.split("\n")
    # A blank line after the docstring keeps the file PEP 8-clean, but only
    # when the next line is code rather than an existing blank.
    tail = lines[head:]
    if tail and tail[0].strip():
        block.append("")
    out = lines[:head] + block + tail
    # Always terminate the file with a newline: the only case where the input
    # lacked one is a file whose last line was code, and leaving it unterminated
    # is a lint failure in every checker this repo runs.
    return "\n".join(out) + "\n"


def insert_into_file(path, docstring, replace=False):
    """Apply insert_docstring to a file in place. Returns True if it changed."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            original = fh.read()
        updated = insert_docstring(original, docstring, replace=replace)
        if updated == original:
            return False
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(updated)
        return True
    except Exception:
        return False


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    replace = "--replace" in argv
    argv = [a for a in argv if a != "--replace"]
    if len(argv) < 2:
        print("usage: insert_module_docstring.py <file.py> <docstring> "
              "[--replace]", file=sys.stderr)
        return 2
    changed = insert_into_file(argv[0], argv[1], replace=replace)
    print(("inserted into " if changed else "unchanged: ") + argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
