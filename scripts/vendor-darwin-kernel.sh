#!/usr/bin/env bash
# Copy-vendor @darwin/kernel into a target repo. Usage: vendor-darwin-kernel.sh <repo-path>
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../packages/darwin-kernel" && pwd)"
DEST="${1:?usage: vendor-darwin-kernel.sh <repo-path>}/vendor/darwin-kernel"
mkdir -p "$DEST"
rsync -a --delete --exclude node_modules --exclude .git "$SRC/" "$DEST/"
echo "vendored @darwin/kernel -> $DEST"
echo 'add to package.json deps:  "@darwin/kernel": "file:vendor/darwin-kernel"'
