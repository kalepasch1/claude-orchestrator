#!/usr/bin/env bash
# Discover every language-specific dependency manifest in the repo and install
# the declared dependencies with the matching package manager.
#
# Before this script, `make install-deps` covered requirements.lock only, so a
# fresh runner/worktree came up with Python deps but with node_modules missing
# in web/, runner/, mcp/ and every packages/* workspace. Agents then failed
# mid-task on "Cannot find module", which is the failure this repairs.
#
# Usage:
#   bash scripts/install-language-deps.sh            # install everything
#   bash scripts/install-language-deps.sh --verify   # only check, install nothing
#   bash scripts/install-language-deps.sh --dry-run  # print the plan
#
# Idempotent. Exits non-zero if any manifest fails to install or verify.
set -uo pipefail

REPO="$(git rev-parse --show-toplevel 2>/dev/null)"
[ -z "${REPO:-}" ] && REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "!! cannot cd to repo root"; exit 1; }

MODE="install"
case "${1:-}" in
  --verify)  MODE="verify" ;;
  --dry-run) MODE="dry-run" ;;
  "")        ;;
  *) echo "usage: $0 [--verify|--dry-run]"; exit 2 ;;
esac

FAILED=()
INSTALLED=()
SKIPPED=()

note() { printf '==> %s\n' "$*"; }
warn() { printf '!!  %s\n' "$*" >&2; }

# Directories we never descend into when hunting for manifests.
PRUNE=( -name node_modules -o -name .git -o -name .venv -o -name venv
        -o -name __pycache__ -o -name dist -o -name build -o -name .next
        -o -name _to_delete -o -name '*-wt' )

find_manifests() {
  # $1 = filename to match
  find . \( "${PRUNE[@]}" \) -prune -o -type f -name "$1" -print 2>/dev/null | sed 's|^\./||' | sort
}

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- Python ----
install_python() {
  local manifest="$1" dir
  dir="$(dirname "$manifest")"
  # Prefer the pinned lockfile when the manifest sits at the repo root.
  local target="$manifest"
  if [ "$manifest" = "requirements.txt" ] && [ -f "requirements.lock" ]; then
    target="requirements.lock"
  fi

  if ! have python3; then
    warn "python3 not on PATH; cannot install $target"
    FAILED+=("$target (no python3)")
    return
  fi

  case "$MODE" in
    dry-run) note "would: python3 -m pip install --break-system-packages -r $target"; return ;;
    verify)
      # A manifest is satisfied when every non-comment requirement resolves.
      if python3 - "$target" <<'PY'
import sys, re
from importlib import metadata
path = sys.argv[1]
missing = []
for raw in open(path, encoding="utf-8", errors="replace"):
    line = raw.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        continue
    name = re.split(r"[<>=!~\[; ]", line, 1)[0].strip()
    if not name:
        continue
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        missing.append(name)
if missing:
    print("missing: " + ", ".join(sorted(set(missing))))
    sys.exit(1)
PY
      then
        INSTALLED+=("$target (python, satisfied)")
      else
        FAILED+=("$target (python, unsatisfied)")
      fi
      return ;;
  esac

  note "pip install -r $target"
  if (cd "$dir" 2>/dev/null || cd "$REPO"; python3 -m pip install --break-system-packages -r "$REPO/$target" >/dev/null 2>&1) \
     || python3 -m pip install -r "$REPO/$target" >/dev/null 2>&1; then
    INSTALLED+=("$target (python)")
  else
    warn "pip install failed for $target"
    FAILED+=("$target (python)")
  fi
}

# ------------------------------------------------------------------ Node ----
install_node() {
  local manifest="$1" dir
  dir="$(dirname "$manifest")"

  if ! have npm; then
    warn "npm not on PATH; cannot install $manifest"
    FAILED+=("$manifest (no npm)")
    return
  fi

  # Nothing declared -> nothing to install.
  if ! node -e '
    const p=require("./'"$manifest"'");
    const n=Object.keys(p.dependencies||{}).length+Object.keys(p.devDependencies||{}).length;
    process.exit(n>0?0:1);
  ' 2>/dev/null; then
    SKIPPED+=("$manifest (no declared deps)")
    return
  fi

  case "$MODE" in
    dry-run) note "would: npm --prefix $dir install"; return ;;
    verify)
      # `npm ls` exit status is NOT a "dependencies are satisfied" signal. It also
      # goes non-zero for `extraneous` — a package present in node_modules that no
      # manifest declares — which is what optional native transitive deps leave
      # behind on every install (@emnapi/*, @napi-rs/*, @tybys/*). web/ had all
      # nine of its declared deps installed and still reported "unsatisfied" on
      # every run because of four extraneous packages nobody had asked for.
      #
      # What actually matters is `missing` and `invalid`: declared but absent, or
      # present at a version the range does not allow. Those are read explicitly
      # from the JSON so the gate fails on real gaps and stays quiet about noise.
      if [ ! -d "$dir/node_modules" ]; then
        FAILED+=("$manifest (node, unsatisfied)")
        return
      fi
      local problems
      problems="$( (cd "$dir" && npm ls --depth=0 --json 2>/dev/null) | node -e '
        const fs = require("fs"), path = require("path");
        const dir = process.argv[1];
        // Local `file:` workspace links (@darwin/kernel -> ../packages/darwin-kernel)
        // are reported `invalid` whenever node_modules is a link farm shared with
        // another checkout, because the resolved path is not the one this tree
        // would have produced. The package is the same source in the same repo, so
        // that is a path artifact, not a missing dependency — accept it as long as
        // the target actually exists on disk.
        let declared = {};
        try {
          const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
          declared = Object.assign({}, pkg.dependencies, pkg.devDependencies);
        } catch {}
        const isLocalLink = name => String(declared[name] || "").startsWith("file:");
        let raw = "";
        process.stdin.on("data", d => raw += d);
        process.stdin.on("end", () => {
          let tree;
          try { tree = JSON.parse(raw || "{}"); }
          catch { console.log("unreadable-npm-ls-output"); return; }
          const bad = [];
          for (const [name, info] of Object.entries(tree.dependencies || {})) {
            if (!info || typeof info !== "object") continue;
            if (info.missing) { bad.push(name + " (missing)"); continue; }
            if (!info.invalid) continue;
            if (isLocalLink(name)) {
              const target = path.resolve(dir, String(declared[name]).slice(5));
              if (fs.existsSync(target)) continue;
            }
            bad.push(name + " (invalid)");
          }
          console.log(bad.join(", "));
        });
      ' "$dir" 2>/dev/null)"
      if [ -z "$problems" ]; then
        INSTALLED+=("$manifest (node, satisfied)")
      else
        warn "$manifest: $problems"
        FAILED+=("$manifest (node, unsatisfied)")
      fi
      return ;;
  esac

  note "npm install in $dir"
  local cmd=(npm --prefix "$dir" install --no-audit --no-fund)
  [ -f "$dir/package-lock.json" ] && cmd=(npm --prefix "$dir" ci --no-audit --no-fund)
  if "${cmd[@]}" >/dev/null 2>&1 || npm --prefix "$dir" install --no-audit --no-fund >/dev/null 2>&1; then
    INSTALLED+=("$manifest (node)")
  else
    warn "npm install failed for $manifest"
    FAILED+=("$manifest (node)")
  fi
}

# ------------------------------------------------------------------ Ruby ----
install_ruby() {
  local manifest="$1" dir; dir="$(dirname "$manifest")"
  if ! have bundle; then SKIPPED+=("$manifest (bundler not installed)"); return; fi
  case "$MODE" in
    dry-run) note "would: bundle install in $dir"; return ;;
    verify)
      if (cd "$dir" && bundle check >/dev/null 2>&1); then INSTALLED+=("$manifest (ruby, satisfied)")
      else FAILED+=("$manifest (ruby, unsatisfied)"); fi
      return ;;
  esac
  note "bundle install in $dir"
  if (cd "$dir" && bundle install >/dev/null 2>&1); then INSTALLED+=("$manifest (ruby)")
  else FAILED+=("$manifest (ruby)"); fi
}

# --------------------------------------------------------------------- Go ---
install_go() {
  local manifest="$1" dir; dir="$(dirname "$manifest")"
  if ! have go; then SKIPPED+=("$manifest (go not installed)"); return; fi
  case "$MODE" in
    dry-run) note "would: go mod download in $dir"; return ;;
    verify)
      if (cd "$dir" && go mod verify >/dev/null 2>&1); then INSTALLED+=("$manifest (go, satisfied)")
      else FAILED+=("$manifest (go, unsatisfied)"); fi
      return ;;
  esac
  note "go mod download in $dir"
  if (cd "$dir" && go mod download >/dev/null 2>&1); then INSTALLED+=("$manifest (go)")
  else FAILED+=("$manifest (go)"); fi
}

# ------------------------------------------------------------------ main ----
note "repo: $REPO"
note "mode: $MODE"

while IFS= read -r m; do [ -n "$m" ] && install_python "$m"; done < <(find_manifests 'requirements*.txt')
while IFS= read -r m; do [ -n "$m" ] && install_node   "$m"; done < <(find_manifests 'package.json')
while IFS= read -r m; do [ -n "$m" ] && install_ruby   "$m"; done < <(find_manifests 'Gemfile')
while IFS= read -r m; do [ -n "$m" ] && install_go     "$m"; done < <(find_manifests 'go.mod')

echo
note "summary"
for x in "${INSTALLED[@]:-}"; do [ -n "$x" ] && echo "   ok      $x"; done
for x in "${SKIPPED[@]:-}";   do [ -n "$x" ] && echo "   skip    $x"; done
for x in "${FAILED[@]:-}";    do [ -n "$x" ] && echo "   FAILED  $x"; done

if [ "${#FAILED[@]}" -gt 0 ] && [ -n "${FAILED[0]:-}" ]; then
  warn "${#FAILED[@]} manifest(s) failed"
  exit 1
fi
note "all manifests satisfied"
