#!/bin/bash
# check-build-tools.sh — verify the toolchain needed to compile native extensions.
#
# Why this exists
# ---------------
# Python wheels that have no prebuilt binary for this platform fall back to
# building from source, which needs a working C toolchain. When that toolchain
# is missing the failure surfaces far downstream as an opaque `pip install`
# error inside a task, not as "you have no compiler". This check names the
# problem at the point it can still be fixed cheaply.
#
# Required vs optional
# --------------------
#   REQUIRED : a C compiler (cc/gcc/clang) and make. Missing -> exit 1.
#   OPTIONAL : cmake. Nothing in this repo's dependency set requests it
#              (verified against requirements.txt / requirements.lock /
#              package.json / Makefile). It is reported but never fatal, so
#              this check does not manufacture a blocker out of a tool the
#              build does not use.
#
# The compiler probe actually COMPILES AND RUNS a program. `gcc --version`
# alone is not proof of a usable toolchain: on macOS the shim can be present
# while the Command Line Tools SDK is absent, in which case the version prints
# fine and every real compile fails on missing headers.
#
# Usage:  scripts/check-build-tools.sh [--verbose]
# Exit :  0 all required tools usable, 1 a required tool missing/broken.
set -uo pipefail

VERBOSE=0
[[ "${1:-}" == "--verbose" ]] && VERBOSE=1

FAILURES=0
WARNINGS=0

say()  { echo "$@"; }
vsay() { [[ $VERBOSE -eq 1 ]] && echo "    $*"; return 0; }

# ── install hint for this platform ──────────────────────────────────────────
install_hint() {
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then echo "brew install $1"
      else echo "xcode-select --install   # or install Homebrew, then: brew install $1"; fi ;;
    Linux)
      if   command -v apt-get >/dev/null 2>&1; then echo "sudo apt-get install -y $1"
      elif command -v dnf     >/dev/null 2>&1; then echo "sudo dnf install -y $1"
      elif command -v yum     >/dev/null 2>&1; then echo "sudo yum install -y $1"
      elif command -v apk     >/dev/null 2>&1; then echo "sudo apk add $1"
      else echo "install '$1' with your system package manager"; fi ;;
    *) echo "install '$1' with your system package manager" ;;
  esac
}

# ── 1. C compiler: probe by compiling and running ───────────────────────────
say "== C compiler =="
CC_BIN=""
for c in "${CC:-}" cc gcc clang; do
  [[ -n "$c" ]] && command -v "$c" >/dev/null 2>&1 && { CC_BIN="$c"; break; }
done

if [[ -z "$CC_BIN" ]]; then
  say "FAIL: no C compiler found (looked for \$CC, cc, gcc, clang)"
  say "      fix: $(install_hint gcc)"
  FAILURES=$((FAILURES + 1))
else
  vsay "$($CC_BIN --version 2>&1 | head -1)"
  TMPD="$(mktemp -d)"
  trap 'rm -rf "$TMPD"' EXIT
  printf '#include <stdio.h>\nint main(void){printf("ok\\n");return 0;}\n' > "$TMPD/probe.c"
  if "$CC_BIN" "$TMPD/probe.c" -o "$TMPD/probe" >"$TMPD/err" 2>&1 && [[ "$("$TMPD/probe" 2>/dev/null)" == "ok" ]]; then
    say "OK  : $CC_BIN compiles and links ($($CC_BIN --version 2>&1 | head -1))"
  else
    say "FAIL: $CC_BIN is on PATH but cannot build a trivial program"
    say "      this usually means the SDK/headers are missing, not the compiler"
    sed 's/^/      /' "$TMPD/err" | head -5
    [[ "$(uname -s)" == "Darwin" ]] && say "      fix: xcode-select --install"
    FAILURES=$((FAILURES + 1))
  fi
fi

# ── 2. make: required ───────────────────────────────────────────────────────
say "== make =="
if command -v make >/dev/null 2>&1; then
  say "OK  : $(make --version 2>&1 | head -1)"
else
  say "FAIL: make not found"
  say "      fix: $(install_hint make)"
  FAILURES=$((FAILURES + 1))
fi

# ── 3. cmake: optional, reported only ───────────────────────────────────────
say "== cmake (optional) =="
if command -v cmake >/dev/null 2>&1; then
  say "OK  : $(cmake --version 2>&1 | head -1)"
else
  say "WARN: cmake not found — not fatal, no dependency in this repo requires it."
  say "      install only if a future dependency needs it: $(install_hint cmake)"
  WARNINGS=$((WARNINGS + 1))
fi

# ── 4. python headers: needed for C extensions ──────────────────────────────
say "== python development headers =="
if python3 -c "import sysconfig,os,sys; p=sysconfig.get_paths().get('include'); sys.exit(0 if p and os.path.exists(os.path.join(p,'Python.h')) else 1)" 2>/dev/null; then
  say "OK  : Python.h present ($(python3 --version 2>&1))"
else
  say "WARN: Python.h not found — building C extensions from source will fail."
  say "      fix: $(install_hint python3-dev)"
  WARNINGS=$((WARNINGS + 1))
fi

say ""
if [[ $FAILURES -gt 0 ]]; then
  say "RESULT: $FAILURES required tool(s) missing or broken, $WARNINGS warning(s)"
  exit 1
fi
say "RESULT: all required build tools usable ($WARNINGS warning(s))"
exit 0
