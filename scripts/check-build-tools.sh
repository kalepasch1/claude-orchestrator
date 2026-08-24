#!/usr/bin/env bash
# Report which native build tools this machine has, and name the install command
# for the ones it is missing.
#
# WHY THIS EXISTS
# ---------------
# `scripts/install-language-deps.sh` covers declared manifests — pip, npm. It cannot
# help when the thing that is missing is the *compiler*: a wheel with no prebuilt
# binary for this platform falls back to building from source, and without a working
# toolchain that surfaces as a wall of compiler output ending in "error: command
# 'gcc' failed", several minutes into an agent run, on a task that had nothing to do
# with C. This answers the question up front, in a second.
#
# It deliberately does NOT install anything. A background agent must not mutate the
# operator's system packages; it prints the exact command and lets a human run it.
#
# Usage:
#   bash scripts/check-build-tools.sh            # human-readable report
#   bash scripts/check-build-tools.sh --json     # machine-readable
#   bash scripts/check-build-tools.sh --quiet    # exit code only
#
# Exit codes:
#   0  every REQUIRED tool is present (optional ones may be missing)
#   1  at least one REQUIRED tool is missing
#   2  bad usage
set -uo pipefail

MODE="report"
case "${1:-}" in
  --json)  MODE="json" ;;
  --quiet) MODE="quiet" ;;
  "")      ;;
  *) echo "usage: $0 [--json|--quiet]" >&2; exit 2 ;;
esac

# name:requirement:version-flag:why
# REQUIRED  — a source build of a common dependency cannot succeed without it.
# OPTIONAL  — only some packages need it; a miss is worth reporting, not failing on.
TOOLS=(
  "cc:required:--version:C compiler used by pip when no wheel matches this platform"
  "make:required:--version:driver for setup.py build_ext and most native Makefiles"
  "git:required:--version:worktrees, branches and the merge train"
  "python3:required:--version:the runner itself"
  "cmake:optional:--version:needed by a minority of native wheels (e.g. some ML deps)"
  "pkg-config:optional:--version:locates system libraries during native builds"
  "node:optional:--version:npm workspaces under web/, mcp/ and packages/*"
)

install_hint() {
  # $1 = tool name. Named per platform, because "install a compiler" is not an
  # instruction anyone can act on directly.
  case "$(uname -s)" in
    Darwin)
      case "$1" in
        cc|make|git) echo "xcode-select --install" ;;
        *)           echo "brew install $1" ;;
      esac
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        case "$1" in
          cc|make) echo "sudo apt-get install -y build-essential" ;;
          *)       echo "sudo apt-get install -y $1" ;;
        esac
      elif command -v dnf >/dev/null 2>&1; then
        case "$1" in
          cc|make) echo "sudo dnf groupinstall -y 'Development Tools'" ;;
          *)       echo "sudo dnf install -y $1" ;;
        esac
      else
        echo "install $1 with this system's package manager"
      fi
      ;;
    *) echo "install $1 with this system's package manager" ;;
  esac
}

first_line() { head -n 1 2>/dev/null || true; }

MISSING_REQUIRED=()
MISSING_OPTIONAL=()
JSON_ROWS=()

for entry in "${TOOLS[@]}"; do
  IFS=':' read -r name requirement flag why <<< "$entry"

  if command -v "$name" >/dev/null 2>&1; then
    version="$("$name" "$flag" 2>&1 | first_line)"
    present=true
  else
    version=""
    present=false
    if [ "$requirement" = "required" ]; then
      MISSING_REQUIRED+=("$name")
    else
      MISSING_OPTIONAL+=("$name")
    fi
  fi

  if [ "$MODE" = "json" ]; then
    JSON_ROWS+=("$(printf '{"tool":"%s","required":%s,"present":%s,"version":"%s","install":"%s","why":"%s"}' \
      "$name" \
      "$([ "$requirement" = required ] && echo true || echo false)" \
      "$present" \
      "$(printf '%s' "$version" | tr -d '"' | tr '\n' ' ')" \
      "$(install_hint "$name" | tr -d '"')" \
      "$why")")
  elif [ "$MODE" = "report" ]; then
    if [ "$present" = true ]; then
      printf 'ok    %-11s %s\n' "$name" "$version"
    elif [ "$requirement" = "required" ]; then
      printf 'MISS  %-11s REQUIRED — %s\n      install: %s\n' \
        "$name" "$why" "$(install_hint "$name")"
    else
      printf 'miss  %-11s optional — %s\n      install: %s\n' \
        "$name" "$why" "$(install_hint "$name")"
    fi
  fi
done

if [ "$MODE" = "json" ]; then
  printf '{"missing_required":%d,"missing_optional":%d,"tools":[%s]}\n' \
    "${#MISSING_REQUIRED[@]}" "${#MISSING_OPTIONAL[@]}" \
    "$(IFS=,; echo "${JSON_ROWS[*]}")"
elif [ "$MODE" = "report" ]; then
  echo
  if [ "${#MISSING_REQUIRED[@]}" -gt 0 ]; then
    echo "!!  missing required: ${MISSING_REQUIRED[*]}"
  else
    echo "==> all required build tools present"
  fi
  if [ "${#MISSING_OPTIONAL[@]}" -gt 0 ]; then
    echo "    missing optional: ${MISSING_OPTIONAL[*]} (only some packages need these)"
  fi
fi

[ "${#MISSING_REQUIRED[@]}" -eq 0 ]
