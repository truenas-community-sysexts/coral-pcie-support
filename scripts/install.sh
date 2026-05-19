#!/usr/bin/env bash
# Installs the pre-built coral.raw sysext on a running TrueNAS system.
# All driver compilation happens on GitHub Actions; this script only
# downloads and places the pre-built coral.raw file.
#
# Unlike the Hailo sysext, no firmware download or injection is needed.
# The Coral PCIe TPU works with just the kernel modules (gasket + apex).
#
# Usage: curl -fsSL <release-url>/install.sh | sudo bash
#    or: sudo ./install.sh [path-to-coral.raw]
#    or: sudo ./install.sh --pool=fast
#    or: sudo ./install.sh --check          (probe an existing install)
#    or: sudo ./install.sh --dry-run        (validate without modifying)
# See --help for the full option list.

set -euo pipefail

# do_check: read-only probe of an existing install. Exits 0 if all checks
# pass (warnings allowed), 1 if any check fails. Used by --check.
do_check() {
    local pass=0 warn=0 fail=0
    local mark_ok="✓" mark_warn="⚠" mark_fail="✗"
    local -a status_lines=()
    local -a hint_lines=()

    record_pass() { status_lines+=("  ${mark_ok} $1"); pass=$((pass+1)); }
    record_warn() {
        status_lines+=("  ${mark_warn} $1"); warn=$((warn+1))
        [ -n "${2:-}" ] && hint_lines+=("    → $2")
    }
    record_fail() {
        status_lines+=("  ${mark_fail} $1"); fail=$((fail+1))
        [ -n "${2:-}" ] && hint_lines+=("    → $2")
    }

    echo "=== Coral TPU install status ==="
    echo ""

    # 1. PCIe device node
    if [ -e /dev/apex_0 ]; then
        record_pass "Device /dev/apex_0 present"
    else
        record_fail "Device /dev/apex_0 not present" \
            "is the Coral PCIe TPU seated, and was the system rebooted after install?"
    fi

    # 2. Kernel modules loaded (both gasket and apex required)
    local gasket_loaded=0 apex_loaded=0
    if lsmod 2>/dev/null | awk '{print $1}' | grep -qx gasket; then
        gasket_loaded=1
    fi
    if lsmod 2>/dev/null | awk '{print $1}' | grep -qx apex; then
        apex_loaded=1
    fi
    if [ "$gasket_loaded" = "1" ] && [ "$apex_loaded" = "1" ]; then
        record_pass "Kernel modules gasket and apex loaded"
    else
        local missing=""
        [ "$gasket_loaded" = "0" ] && missing="gasket"
        [ "$apex_loaded" = "0" ] && missing="${missing:+${missing}, }apex"
        record_fail "Kernel module(s) not loaded: ${missing}" \
            "re-run install.sh or manually insmod the modules under /usr/lib/modules/\$(uname -r)/extra/"
    fi

    # 3. Sysext file present on disk
    if [ -f "$CORAL_RAW" ]; then
        record_pass "Sysext present at ${CORAL_RAW}"
    else
        record_fail "Sysext missing at ${CORAL_RAW}" "re-run install.sh"
    fi

    # 4. Sysext merged into /usr
    if systemd-sysext list 2>/dev/null | awk '{print $1}' | grep -qx coral; then
        record_pass "Sysext merged into /usr"
    else
        record_warn "Sysext not currently merged" \
            "the PREINIT script merges it on boot; check 'systemctl status systemd-sysext'"
    fi

    # 5. Persistent config dir (same resolver as install path)
    local persist_dir=""
    if resolve_persist_dir; then
        persist_dir="$PERSIST_DIR"
        record_pass "Persistent config at ${persist_dir}"
    else
        record_fail "No persistent config resolved" \
            "re-run install.sh with --pool=NAME or --persist-path=PATH"
    fi

    # 6. Backup coral.raw on persistent pool
    if [ -n "$persist_dir" ] && [ -f "${persist_dir}/coral.raw" ]; then
        record_pass "Backup ${persist_dir}/coral.raw present"
    elif [ -n "$persist_dir" ]; then
        record_fail "Backup coral.raw missing in ${persist_dir}" "re-run install.sh"
    fi

    # 7. PREINIT script on disk
    if [ -n "$persist_dir" ] && [ -x "${persist_dir}/coral-preinit.sh" ]; then
        record_pass "PREINIT script ${persist_dir}/coral-preinit.sh present and executable"
    elif [ -n "$persist_dir" ]; then
        record_fail "PREINIT script missing or not executable in ${persist_dir}" "re-run install.sh"
    fi

    # 8. PREINIT registered with TrueNAS middleware (read-only midclt query)
    if command -v midclt >/dev/null 2>&1; then
        local lookup script_when script_enabled
        lookup=$(coral_init_script_lookup)
        case "$lookup" in
            error)
                record_warn "Could not query TrueNAS middleware" \
                    "run with sudo on TrueNAS SCALE"
                ;;
            "")
                record_fail "No init script registered for coral" "re-run install.sh"
                ;;
            *)
                IFS='|' read -r _ script_when script_enabled <<<"$lookup"
                if [ "$script_when" = "PREINIT" ] && [ "$script_enabled" = "True" ]; then
                    record_pass "PREINIT script registered with TrueNAS middleware (PREINIT, enabled)"
                else
                    record_warn "Init script registered but not as enabled PREINIT" \
                        "re-run install.sh to fix"
                fi
                ;;
        esac
    else
        record_warn "midclt not available, skipping middleware check" \
            "this script must run on TrueNAS SCALE"
    fi

    # 9. Kernel module paths match running kernel (check both gasket.ko and apex.ko)
    local running_kver gasket_ko apex_ko
    running_kver=$(uname -r)
    gasket_ko="/usr/lib/modules/${running_kver}/extra/gasket.ko"
    apex_ko="/usr/lib/modules/${running_kver}/extra/apex.ko"
    if [ -f "$gasket_ko" ] && [ -f "$apex_ko" ]; then
        record_pass "Kernel module paths match running kernel ${running_kver}"
    else
        local missing_ko=""
        [ ! -f "$gasket_ko" ] && missing_ko="gasket.ko"
        [ ! -f "$apex_ko" ] && missing_ko="${missing_ko:+${missing_ko}, }apex.ko"
        record_fail "Missing ${missing_ko} for running kernel ${running_kver}" \
            "download a new coral.raw release matching this kernel"
    fi

    # 10. PREINIT script result on last boot.
    # coral-preinit.sh logs via `logger -t coral-preinit`, so journalctl can
    # filter by tag. The script ends with a "Done" sentinel on success; any
    # ERROR: line in the same boot indicates a failure path was hit.
    if ! command -v journalctl >/dev/null 2>&1; then
        record_fail "journalctl not available, cannot read PREINIT result" \
            "this script must run on TrueNAS SCALE"
    else
        local preinit_log preinit_last
        preinit_log=$(journalctl -b -t coral-preinit --no-pager -o cat 2>/dev/null || true)
        if [ -z "$preinit_log" ]; then
            record_warn "No coral-preinit entries this boot" \
                "PREINIT may not be registered yet; reboot after install, or re-run install.sh"
        elif printf '%s' "$preinit_log" | grep -q '^ERROR:'; then
            preinit_last=$(printf '%s' "$preinit_log" | grep '^ERROR:' | head -1)
            record_fail "PREINIT logged an error this boot: ${preinit_last}" \
                "see full log: journalctl -b -t coral-preinit"
        else
            preinit_last=$(printf '%s' "$preinit_log" | tail -1)
            if [ "$preinit_last" = "Done" ]; then
                record_pass "PREINIT completed successfully this boot"
            else
                record_warn "PREINIT ran but did not log the Done sentinel (last: ${preinit_last})" \
                    "review full log: journalctl -b -t coral-preinit"
            fi
        fi
    fi

    printf '%s\n' "${status_lines[@]}"
    echo ""
    if [ "${#hint_lines[@]}" -gt 0 ]; then
        printf '%s\n' "${hint_lines[@]}"
        echo ""
    fi
    printf 'Summary: %d ok, %d warn, %d fail\n' "$pass" "$warn" "$fail"

    [ "$fail" -gt 0 ] && return 1
    return 0
}

# if_real: run a command unless --dry-run is set, in which case print what
# would have been run. For redirections and heredocs, gate the entire block
# manually with `if [ "$DRY_RUN" = "1" ]; then ... else ... fi` since the
# shell evaluates redirections before the command runs.
if_real() {
    if [ "$DRY_RUN" = "1" ]; then
        printf '[dry-run] would: %s\n' "$*"
    else
        "$@"
    fi
}

# resolve_persist_dir: determine where persistent config lives.
# Priority: --persist-path > --pool > existing config dir > only-data-pool
#         > interactive prompt (multi-pool) > error (no tty + ambiguous)
# Sets PERSIST_DIR on success; prints to stderr and returns 1 on failure.
resolve_persist_dir() {
    PERSIST_DIR=""
    local d p
    local -a existing=() pools=() choices=()
    local header n i

    if [ -n "${PERSIST_PATH:-}" ]; then
        PERSIST_DIR="$PERSIST_PATH"
        return 0
    fi
    if [ -n "${POOL_NAME:-}" ]; then
        PERSIST_DIR="/mnt/${POOL_NAME}/.config/coral"
        return 0
    fi

    shopt -s nullglob
    for d in /mnt/*/.config/coral; do
        [ -d "$d" ] && existing+=("$d")
    done
    shopt -u nullglob

    if [ "${#existing[@]}" -eq 1 ]; then
        PERSIST_DIR="${existing[0]}"
        echo "Re-using existing config: $PERSIST_DIR"
        return 0
    fi

    while IFS= read -r p; do
        [ -n "$p" ] && [ "$p" != "boot-pool" ] && pools+=("$p")
    done < <(zpool list -H -o name 2>/dev/null)

    if [ "${#existing[@]}" -eq 0 ] && [ "${#pools[@]}" -eq 0 ]; then
        echo "ERROR: No ZFS pool found (excluding boot-pool). Cannot set up persistence." >&2
        echo "  Re-run with --pool=<name> or --persist-path=/mnt/<pool>/<path>" >&2
        return 1
    fi

    if [ "${#existing[@]}" -eq 0 ] && [ "${#pools[@]}" -eq 1 ]; then
        PERSIST_DIR="/mnt/${pools[0]}/.config/coral"
        echo "Auto-selected pool: ${pools[0]} → $PERSIST_DIR"
        return 0
    fi

    if [ "${#existing[@]}" -gt 1 ]; then
        header="Found existing coral configs on multiple pools:"
        choices=("${existing[@]}")
    else
        header="Multiple data pools available (no existing config):"
        for p in "${pools[@]}"; do
            choices+=("/mnt/${p}/.config/coral")
        done
    fi

    if ! { : </dev/tty; } 2>/dev/null; then
        echo "ERROR: $header" >&2
        echo "  No controlling terminal. Pass --pool=<name> or --persist-path=<path>." >&2
        return 1
    fi

    echo "$header"
    for i in "${!choices[@]}"; do
        echo "  [$((i+1))] ${choices[$i]}"
    done
    while true; do
        printf 'Pick one (1-%d): ' "${#choices[@]}"
        read -r n </dev/tty || return 1
        if [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le "${#choices[@]}" ]; then
            PERSIST_DIR="${choices[$((n-1))]}"
            echo "Selected: $PERSIST_DIR"
            return 0
        fi
        echo "  Invalid. Enter 1-${#choices[@]}."
    done
}

# REPO can be overridden via --repo=OWNER/NAME or CORAL_REPO env var.
REPO="${CORAL_REPO:-truenas-community-sysexts/coral-pcie-support}"
SYSEXT_DIR="/usr/share/truenas/sysext-extensions"
CORAL_RAW="${SYSEXT_DIR}/coral.raw"

# --- Parse CLI arguments ---
LOCAL_RAW=""
POOL_NAME=""
PERSIST_PATH=""
CHECK_MODE=0
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --repo=*)
            REPO="${arg#*=}"
            [ -n "$REPO" ] || { echo "ERROR: --repo= requires a non-empty value (e.g., --repo=owner/name)" >&2; exit 2; }
            ;;
        --pool=*)
            POOL_NAME="${arg#*=}"
            [ -n "$POOL_NAME" ] || { echo "ERROR: --pool= requires a non-empty value" >&2; exit 2; }
            ;;
        --persist-path=*)
            PERSIST_PATH="${arg#*=}"
            [ -n "$PERSIST_PATH" ] || { echo "ERROR: --persist-path= requires a non-empty value" >&2; exit 2; }
            ;;
        --check) CHECK_MODE=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --help)
            echo "Usage: sudo ./install.sh [OPTIONS] [path-to-coral.raw]"
            echo ""
            echo "Options:"
            echo "  --repo=OWNER/NAME             GitHub repo to download release from (default: truenas-community-sysexts/coral-pcie-support)"
            echo "                                Can also be set via CORAL_REPO env var."
            echo "  --pool=NAME                   ZFS pool for persistent config (e.g., fast)"
            echo "  --persist-path=PATH           Exact path for persistent config"
            echo "  --check                       Probe an existing install (read-only) and report status"
            echo "  --dry-run                     Validate everything (downloads, checksums, network) without modifying the system"
            echo "  --help                        Show this help"
            echo ""
            echo "Examples:"
            echo "  sudo ./install.sh --pool=fast"
            echo "  sudo ./install.sh --check"
            echo "  sudo ./install.sh --dry-run"
            echo "  sudo ./install.sh /tmp/coral-input.raw"
            echo "  curl -fsSL <url>/install.sh | sudo bash"
            exit 0
            ;;
        *)
            # A `curl | sudo bash` user who typos `--pol=fast` or `/tmp/typ.raw`
            # silently gets auto-detect / a release download. They think their
            # flag took effect when it didn't. Refuse rather than guess.
            if [ -f "$arg" ]; then
                LOCAL_RAW="$arg"
            elif [[ "$arg" == -* ]]; then
                echo "ERROR: unknown option: $arg (see --help)" >&2
                exit 2
            else
                echo "ERROR: positional argument is not an existing file: $arg" >&2
                echo "  Pass --help for usage." >&2
                exit 2
            fi
            ;;
    esac
done

if [ "$CHECK_MODE" = "1" ] && [ "$DRY_RUN" = "1" ]; then
    echo "ERROR: --check and --dry-run are mutually exclusive" >&2
    exit 2
fi

# Source shared library (provides coral_init_script_lookup).
# Try the sibling file first (checkout or extracted release); fall back to
# downloading from the release for the curl|bash case.
_source_coral_lib() {
    local dir
    dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || dir=""
    if [ -n "$dir" ] && [ -f "${dir}/coral-lib.sh" ]; then
        # shellcheck source=scripts/coral-lib.sh
        source "${dir}/coral-lib.sh"
        return 0
    fi
    local tmp
    tmp=$(mktemp /tmp/coral-lib.XXXXXXXXXX)
    if curl -fsSL --max-time 30 \
           "https://github.com/${REPO}/releases/latest/download/coral-lib.sh" \
           -o "$tmp" 2>/dev/null && [ -s "$tmp" ]; then
        # shellcheck source=scripts/coral-lib.sh
        source "$tmp"
        rm -f "$tmp"
        return 0
    fi
    rm -f "$tmp"
    return 1
}
_source_coral_lib || {
    echo "ERROR: Could not load coral-lib.sh (not found locally, download failed)." >&2
    echo "  Run from the release directory, or ensure network access to GitHub." >&2
    exit 1
}

if [ "$CHECK_MODE" = "1" ]; then
    do_check
    exit $?
fi

# USR_WAS_WRITABLE: 1 while we have ${USR_DATASET}'s readonly=off and
# haven't restored it yet. The cleanup trap re-asserts readonly=on so
# any failure path between off and on (cp errors, SIGINT/SIGTERM) does
# not leave /usr writable until reboot.
USR_WAS_WRITABLE=0

WORK_DIR=$(mktemp -d /tmp/coral-install.XXXXXXXXXX)

cleanup() {
    if [ "$USR_WAS_WRITABLE" = "1" ] && [ -n "${USR_DATASET:-}" ] && [ "$DRY_RUN" != "1" ]; then
        zfs set readonly=on "${USR_DATASET}" 2>/dev/null || true
        USR_WAS_WRITABLE=0
    fi
    [ -n "${WORK_DIR:-}" ] && rm -rf "$WORK_DIR"
}
trap cleanup EXIT INT TERM

# If a local path is provided, use it; otherwise download from GitHub releases
if [ -n "$LOCAL_RAW" ]; then
    # Reject input path == staging path: cp would refuse with "are the same
    # file" and the EXIT trap would then rm -rf the work dir, deleting the
    # user's input. Detect and refuse rather than risk data loss.
    LOCAL_REAL=$(realpath "$LOCAL_RAW" 2>/dev/null || echo "$LOCAL_RAW")
    STAGE_REAL=$(realpath -m "${WORK_DIR}/coral.raw" 2>/dev/null || echo "${WORK_DIR}/coral.raw")
    if [ "$LOCAL_REAL" = "$STAGE_REAL" ]; then
        echo "ERROR: input file collides with the installer's staging path." >&2
        echo "  Move or copy it to a different path and re-run." >&2
        exit 2
    fi
    echo "Using local coral.raw: $LOCAL_RAW"
    cp "$LOCAL_RAW" "${WORK_DIR}/coral.raw"
else
    # Detect TrueNAS version
    VERSION=$(midclt call system.info | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin)['version'])
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
") || { echo "ERROR: Failed to detect TrueNAS version"; exit 1; }
    [ -z "$VERSION" ] && { echo "ERROR: TrueNAS version is empty"; exit 1; }
    echo "Detected TrueNAS version: ${VERSION}"

    # Find matching release
    echo "Searching for matching release..."
    export VERSION
    RELEASE_TAG=$(curl -sS --max-time 30 "https://api.github.com/repos/${REPO}/releases?per_page=100" \
        | python3 -c "
import sys, json, os
try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    print('Failed to parse GitHub API response', file=sys.stderr)
    sys.exit(1)
if isinstance(data, dict) and 'message' in data:
    msg = data['message']
    if 'rate limit' in msg.lower():
        print('GitHub API rate limit exceeded (60 requests/hour for unauthenticated calls).', file=sys.stderr)
        print('Wait a few minutes and try again.', file=sys.stderr)
    else:
        print(f'GitHub API error: {msg}', file=sys.stderr)
    sys.exit(1)
version = os.environ['VERSION']
prefix = f'v{version}-'
matches = [r for r in data if r.get('tag_name', '').startswith(prefix)]
if not matches:
    print(f'No release found for TrueNAS version {version}', file=sys.stderr)
    tags = [r.get('tag_name', '?') for r in data]
    if tags:
        print('Available releases:', file=sys.stderr)
        for t in tags:
            print(f'  {t}', file=sys.stderr)
    sys.exit(1)
matches.sort(key=lambda r: r.get('published_at') or r.get('created_at') or '', reverse=True)
print(matches[0]['tag_name'], end='')
") || { echo "ERROR: Failed to query GitHub releases"; exit 1; }

    echo "Found release: ${RELEASE_TAG}"

    # Extract gasket driver version from the tag for informational purposes.
    # Tags look like: v25.10.3.1-gasket1.0-18.4-r1
    GASKET_VERSION=$(echo "$RELEASE_TAG" | sed -n 's/.*gasket\([0-9][0-9._-]*[0-9]\).*/\1/p')
    if [ -z "$GASKET_VERSION" ]; then
        echo "ERROR: Could not parse gasket driver version from release tag '${RELEASE_TAG}'." >&2
        echo "  Expected format: v<truenas>-gasket<driver>-r<run>" >&2
        exit 1
    fi
    echo "Gasket driver version: ${GASKET_VERSION}"

    # Download coral.raw and checksum
    BASE_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}"
    echo "Downloading coral.raw..."
    curl -fSL --max-time 600 "${BASE_URL}/coral.raw" -o "${WORK_DIR}/coral.raw" || { echo "ERROR: Failed to download coral.raw"; exit 1; }
    curl -fSL --max-time 600 "${BASE_URL}/coral.raw.sha256" -o "${WORK_DIR}/coral.raw.sha256" || { echo "ERROR: Failed to download checksum"; exit 1; }

    # Validate downloads are non-empty
    [ -s "${WORK_DIR}/coral.raw" ] || { echo "ERROR: coral.raw is empty"; exit 1; }
    [ -s "${WORK_DIR}/coral.raw.sha256" ] || { echo "ERROR: checksum file is empty"; exit 1; }

    # Verify checksum
    echo "Verifying checksum..."
    if ! (cd "$WORK_DIR" && sha256sum -c coral.raw.sha256); then
        echo "ERROR: Checksum verification failed!"
        exit 1
    fi
    echo "Checksum OK"
fi

# --- Extract PREINIT script from sysext ---
# The sysext bundles coral-preinit.sh at usr/lib/coral/coral-preinit.sh.
# Extract it via unsquashfs (read-only). No repacking is needed since the
# Coral sysext has no firmware to inject.
echo ""
echo "=== Extracting PREINIT script from coral.raw ==="

if ! command -v unsquashfs &>/dev/null; then
    echo "ERROR: unsquashfs not found, cannot extract PREINIT script from sysext"
    echo "  Install squashfs-tools: apt-get install squashfs-tools"
    exit 1
fi

unsquashfs -q -d "${WORK_DIR}/coral-sysext-unpack" "${WORK_DIR}/coral.raw" usr/lib/coral/coral-preinit.sh

BUNDLED_PREINIT="${WORK_DIR}/coral-sysext-unpack/usr/lib/coral/coral-preinit.sh"
if [ ! -f "$BUNDLED_PREINIT" ]; then
    echo "ERROR: coral-preinit.sh not found in sysext at /usr/lib/coral/coral-preinit.sh" >&2
    echo "  This coral.raw was built before the preinit script was bundled in." >&2
    echo "  Re-fetch a current release: https://github.com/${REPO}/releases/latest" >&2
    exit 1
fi
cp "$BUNDLED_PREINIT" "${WORK_DIR}/coral-preinit.sh"
chmod +x "${WORK_DIR}/coral-preinit.sh"
rm -rf "${WORK_DIR}/coral-sysext-unpack"
echo "PREINIT script extracted"

echo ""
echo "=== Installing coral.raw ==="

# Remove coral from sysext before modifying. If nothing is currently merged,
# unmerge exits non-zero with "No extensions found" on stderr, which is fine.
# A real failure (overlay held open by another process) must not be swallowed.
echo "Removing old coral sysext symlink..."
if_real rm -f /run/extensions/coral.raw
if [ "$DRY_RUN" != "1" ]; then
    UNMERGE_ERR=$(systemd-sysext unmerge 2>&1) || {
        if printf '%s' "$UNMERGE_ERR" | grep -qi "no extensions"; then
            true  # nothing was merged, harmless
        else
            echo "ERROR: systemd-sysext unmerge failed: ${UNMERGE_ERR}" >&2
            echo "  Another process may be holding the overlay open." >&2
            exit 1
        fi
    }
else
    echo "[dry-run] would: systemd-sysext unmerge"
fi

# Make /usr writable
USR_DATASET=$(zfs list -H -o name /usr 2>/dev/null) || { echo "ERROR: Failed to find ZFS dataset for /usr"; exit 1; }
[ -z "$USR_DATASET" ] && { echo "ERROR: ZFS dataset for /usr is empty"; exit 1; }
echo "Setting ${USR_DATASET} to writable..."
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] would: zfs set readonly=off ${USR_DATASET}"
else
    zfs set readonly=off "${USR_DATASET}" || { echo "ERROR: Failed to make ${USR_DATASET} writable"; exit 1; }
    USR_WAS_WRITABLE=1
fi

# Install new coral.raw (backup is on persistent pool, no need for .bak).
# If cp fails, the cleanup trap re-asserts readonly=on so we never
# leave /usr writable on the failure path.
echo "Installing new coral.raw..."
if_real cp "${WORK_DIR}/coral.raw" "${CORAL_RAW}"

# Restore read-only
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] would: zfs set readonly=on ${USR_DATASET}"
else
    zfs set readonly=on "${USR_DATASET}"
    USR_WAS_WRITABLE=0
fi

# Activate sysext via symlink + refresh (TrueNAS middleware pattern)
echo "Activating coral sysext..."
if_real mkdir -p /run/extensions
if_real ln -sf "${CORAL_RAW}" /run/extensions/coral.raw
if_real systemd-sysext refresh
if_real ldconfig

# Load the kernel modules (use insmod directly, /lib/modules is read-only on
# TrueNAS so depmod can't update module deps, and modprobe can't find modules
# without it). gasket must be loaded before apex (apex depends on gasket).
echo "Loading Coral kernel modules..."
GASKET_KO="/usr/lib/modules/$(uname -r)/extra/gasket.ko"
APEX_KO="/usr/lib/modules/$(uname -r)/extra/apex.ko"
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] would: insmod ${GASKET_KO} (if present)"
    echo "[dry-run] would: insmod ${APEX_KO} (if present)"
elif [ -f "$GASKET_KO" ] && [ -f "$APEX_KO" ]; then
    insmod "$GASKET_KO" || echo "WARNING: insmod gasket failed"
    insmod "$APEX_KO" || echo "WARNING: insmod apex failed (device may not be present)"
else
    [ ! -f "$GASKET_KO" ] && echo "WARNING: gasket.ko not found at ${GASKET_KO}"
    [ ! -f "$APEX_KO" ] && echo "WARNING: apex.ko not found at ${APEX_KO}"
fi

# Reload udev rules from sysext so /dev/apex_0 gets correct permissions
echo "Reloading udev rules..."
if_real udevadm control --reload-rules 2>/dev/null || true
if [ -e /dev/apex_0 ]; then
    if_real udevadm trigger --subsystem-match=apex 2>/dev/null || true
fi

echo ""
echo "=== Installation complete ==="
echo ""

# Verify
if [ -e /dev/apex_0 ]; then
    echo "Device /dev/apex_0 detected!"
else
    echo "Device /dev/apex_0 not found."
    echo "  - Ensure a Coral PCIe TPU is installed"
    echo "  - Try rebooting the system"
fi

# ==========================================================================
# Persistence setup: survives reboots and TrueNAS updates
# ==========================================================================

echo ""
echo "=== Setting up persistence ==="

# --- Detect persistent storage pool ---
if ! resolve_persist_dir; then
    echo "  The sysext is loaded for this session but will NOT survive a reboot." >&2
    exit 1
fi

echo "Persistent config directory: ${PERSIST_DIR}"
if_real mkdir -p "$PERSIST_DIR"

# --- Backup coral.raw to persistent storage ---
echo "Backing up coral.raw to persistent storage..."
if_real cp "${WORK_DIR}/coral.raw" "${PERSIST_DIR}/coral.raw"

# Save gasket driver version for reference
if [ -n "${GASKET_VERSION:-}" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        echo "[dry-run] would: write \$GASKET_VERSION (${GASKET_VERSION}) to ${PERSIST_DIR}/.coral-driver-version"
    else
        printf '%s' "$GASKET_VERSION" > "${PERSIST_DIR}/.coral-driver-version"
    fi
fi

# Save source repo so the boot-time PREINIT script can point users at the right
# releases page when a kernel mismatch is detected.
if [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] would: write \$REPO (${REPO}) to ${PERSIST_DIR}/.coral-repo"
else
    printf '%s' "$REPO" > "${PERSIST_DIR}/.coral-repo"
fi

# --- Install PREINIT script to persistent storage ---
# Source is ${WORK_DIR}/coral-preinit.sh, extracted from the unsquashed
# sysext earlier. Bundling the script in the sysext means the coral.raw
# release artifact is self-contained.
echo "Installing PREINIT script..."

# Clean up old postinit script if present
if_real rm -f "${PERSIST_DIR}/coral-postinit.sh"

if_real cp "${WORK_DIR}/coral-preinit.sh" "${PERSIST_DIR}/coral-preinit.sh"
if_real chmod +x "${PERSIST_DIR}/coral-preinit.sh"

# --- Register PREINIT script via midclt ---
PREINIT_SCRIPT="${PERSIST_DIR}/coral-preinit.sh"
echo "Registering PREINIT script..."

# Find any existing coral init script (postinit or preinit). A midclt
# lookup error is NOT the same as not-found: midclt records aren't keyed
# by command, so falling through to create on a transient query failure
# can produce a duplicate registration that restore.sh's first-match
# cleanup won't fully undo. Refuse rather than guess.
EXISTING_LOOKUP=$(coral_init_script_lookup)
if [ "$EXISTING_LOOKUP" = "error" ]; then
    echo "ERROR: Could not query TrueNAS middleware to check for existing init scripts." >&2
    echo "  Refusing to register without a clean lookup, risks duplicate PREINIT entries." >&2
    echo "  Run 'midclt call initshutdownscript.query' to confirm middleware health, then re-run." >&2
    exit 1
fi
EXISTING_ID="${EXISTING_LOOKUP%%|*}"

# Build the payload via python3 -> json.dumps so PREINIT_SCRIPT is escaped
# correctly even if the path ever grows characters that are special to JSON.
PREINIT_PAYLOAD=$(PREINIT_SCRIPT="$PREINIT_SCRIPT" python3 -c '
import json, os
print(json.dumps({
    "type": "COMMAND",
    "command": os.environ["PREINIT_SCRIPT"],
    "when": "PREINIT",
    "enabled": True,
    "timeout": 30,
    "comment": "Activate Coral TPU sysext before apps start",
}))
')

if [ -n "$EXISTING_ID" ]; then
    echo "Coral init script already registered (id: ${EXISTING_ID}), updating to PREINIT..."
    if ! if_real midclt call initshutdownscript.update "$EXISTING_ID" "$PREINIT_PAYLOAD"; then
        echo "ERROR: Failed to update init script (id: ${EXISTING_ID})." >&2
        echo "ERROR: Without a registered PREINIT script the sysext will NOT survive a reboot." >&2
        echo "ERROR: Check 'midclt call initshutdownscript.query' and re-run the installer." >&2
        exit 1
    fi
else
    if ! if_real midclt call initshutdownscript.create "$PREINIT_PAYLOAD"; then
        echo "ERROR: Failed to register PREINIT script via midclt." >&2
        echo "ERROR: Without a registered PREINIT script the sysext will NOT survive a reboot." >&2
        echo "ERROR: Check that the TrueNAS middleware is reachable (midclt call core.ping) and re-run." >&2
        exit 1
    fi
    echo "PREINIT script registered"
fi

echo ""
echo "=== Persistence setup complete ==="
echo ""
echo "Persistent config: ${PERSIST_DIR}/"
echo "  coral.raw                - sysext backup"
echo "  .coral-driver-version    - gasket driver version (informational)"
echo "  coral-preinit.sh         - runs before apps start (registered as PREINIT)"
echo ""
echo "The Coral TPU driver will survive TrueNAS updates and reboots."

if [ "$DRY_RUN" = "1" ]; then
    echo ""
    echo "=== Dry-run complete ==="
    echo "No changes were made to the system."
    echo ""
    echo "Would have installed:"
    echo "  Sysext target:     ${CORAL_RAW}"
    echo "  Persistent dir:    ${PERSIST_DIR}"
    [ -n "${GASKET_VERSION:-}" ] && echo "  Gasket version:    ${GASKET_VERSION}"
    [ -n "${RELEASE_TAG:-}" ] && echo "  Release tag:       ${RELEASE_TAG}"
fi
