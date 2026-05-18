#!/usr/bin/env bash
set -euo pipefail

GASKET_DIR="$1"
PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$GASKET_DIR/src" ]; then
    echo "ERROR: $GASKET_DIR does not contain a src/ directory" >&2
    exit 1
fi

for patch in "$PATCH_DIR"/0*.patch; do
    [ -f "$patch" ] || continue
    name=$(basename "$patch")
    if git -C "$GASKET_DIR" apply --check "$patch" 2>/dev/null; then
        echo "Applying: $name"
        git -C "$GASKET_DIR" apply "$patch"
    else
        echo "Skipping (already applied or N/A): $name"
    fi
done
