#!/usr/bin/env python3
"""Resolve unresolved `<<<<<<<`/`=======`/`>>>>>>>` blocks by keeping THEIRS.

Written for the hisanta merge that landed conflict markers on master (three files,
every one of them a SyntaxError, which stopped pytest collecting the whole
`tests/` tree). The `theirs` side of all three is the coherent pair — canonical
definitions in `hisanta/hisanta/contracts/family.py`, a re-export shim in
`hisanta/contracts/family.py`, and a mastery engine whose helpers use the module
constants the common preamble already defines.

Usage:  python3 scripts/resolve_conflict_theirs.py FILE [FILE ...]
Prints one line per file and exits non-zero if any file still has markers.
"""

import sys


def resolve(text):
    """Return *text* with every conflict block reduced to its `theirs` side."""
    out, side = [], None
    for line in text.splitlines(keepends=True):
        if line.startswith("<<<<<<< "):
            side = "ours"
            continue
        if side and line.rstrip("\n") == "=======":
            side = "theirs"
            continue
        if line.startswith(">>>>>>> "):
            side = None
            continue
        if side != "ours":
            out.append(line)
    return "".join(out)


def main(argv):
    bad = 0
    for path in argv:
        try:
            with open(path, encoding="utf-8") as fh:
                original = fh.read()
        except OSError as exc:
            print(f"skip {path}: {exc}")
            bad += 1
            continue
        resolved = resolve(original)
        if resolved != original:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(resolved)
        still = [n for n, l in enumerate(resolved.splitlines(), 1)
                 if l.startswith(("<<<<<<< ", ">>>>>>> "))]
        print(f"{path}: {'clean' if not still else f'MARKERS REMAIN at {still}'}")
        bad += bool(still)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
