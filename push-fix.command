#!/bin/bash
cd "$(dirname "$0")"
# Remove stale lock files from sandbox mount
rm -f .git/index.lock .git/HEAD.lock .git/objects/*/tmp_obj_* 2>/dev/null
echo "Pushing resource_governor + fleet fix..."
git push origin master
echo ""
echo "Done. Press any key to close."
read -n 1
