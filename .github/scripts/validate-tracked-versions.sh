#!/usr/bin/env bash
# Validate that .github/tracked-versions.json has the shape the rest of the
# CI machinery (check-releases.yml, build.yml) assumes.
#
# Run locally:
#   .github/scripts/validate-tracked-versions.sh
# Exits non-zero with a `::error::` annotation on any shape violation.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FILE="${REPO_ROOT}/.github/tracked-versions.json"

if [ ! -f "$FILE" ]; then
  echo "::error title=tracked-versions::file not found: ${FILE}" >&2
  exit 1
fi

python3 - "$FILE" <<'PY'
import json
import re
import sys

path = sys.argv[1]

def fail(msg):
    print(f"::error title=tracked-versions::{msg}", file=sys.stderr)
    sys.exit(1)

try:
    with open(path) as f:
        data = json.load(f)
except json.JSONDecodeError as e:
    fail(f"invalid JSON in {path}: {e}")

if not isinstance(data, dict):
    fail("top-level value must be an object")

# Match the shape check-releases.yml's tag parser will accept: 2-or-more
# numeric parts. Today's TrueNAS tags are 3- or 4-part (25.10.3, 25.10.3.1)
# but a future train (e.g. TS-26.0) could legitimately be 2-part. Capping at
# 5 parts so a runaway tag still trips the gate.
ver_re = re.compile(r"^\d+(\.\d+){1,4}$")
# Train names are capitalized words (Goldeye, Fangtooth, etc.)
train_re = re.compile(r"^[A-Z][a-zA-Z]+$")

truenas = data.get("truenas")
if not isinstance(truenas, dict):
    fail("'truenas' key missing or not an object")

tn_version = truenas.get("version")
if not isinstance(tn_version, str) or not ver_re.match(tn_version):
    fail(f"'truenas.version' missing or malformed (got {tn_version!r}); expected X.Y[.Z[.W[.V]]]")

tn_train = truenas.get("train")
if not isinstance(tn_train, str) or not train_re.match(tn_train):
    fail(f"'truenas.train' missing or malformed (got {tn_train!r}); expected capitalized word (e.g. Goldeye)")

gasket = data.get("gasket")
if not isinstance(gasket, dict):
    fail("'gasket' key missing or not an object")

g_driver = gasket.get("driver")
if not isinstance(g_driver, str) or not g_driver.strip():
    fail(f"'gasket.driver' missing or empty (got {g_driver!r})")

g_ref = gasket.get("ref")
if not isinstance(g_ref, str) or not g_ref.strip():
    fail(f"'gasket.ref' missing or empty (got {g_ref!r})")

print(f"tracked-versions OK: TrueNAS {tn_version} ({tn_train}), gasket driver {g_driver} (ref: {g_ref})")
PY
