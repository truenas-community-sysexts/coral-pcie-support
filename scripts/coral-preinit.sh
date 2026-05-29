#!/usr/bin/env bash
# TrueNAS PREINIT script: activates coral.raw sysext on every boot.
# Runs before middleware starts, so the Coral TPU device is ready before
# app containers (e.g., Frigate) launch.
#
# Stored on persistent pool; registered via midclt during install.
# Idempotent: safe to run on every boot.

set -euo pipefail

log() {
    echo "[coral-preinit] $*"
    logger -t coral-preinit "$*" 2>/dev/null || true
}

USR_WAS_WRITABLE=0
USR_DATASET=""

restore_usr_readonly() {
    if [ "$USR_WAS_WRITABLE" = "1" ] && [ -n "$USR_DATASET" ]; then
        zfs set readonly=on "$USR_DATASET" 2>/dev/null || true
        USR_WAS_WRITABLE=0
    fi
}
trap restore_usr_readonly EXIT INT TERM

# --- Find persistent config via glob ---
# nullglob: if no pool matches, the loop body never runs (instead of
# iterating once with the literal glob string). Localized via subshell-free
# save/restore so the rest of the script keeps default globbing.
PERSIST_DIR=""
PERSIST_DIRS=()
shopt -s nullglob
for d in /mnt/*/.config/coral; do
    [ -d "$d" ] && PERSIST_DIRS+=("$d")
done
shopt -u nullglob

if [ ${#PERSIST_DIRS[@]} -eq 0 ]; then
    log "No persistent config found at /mnt/*/.config/coral/, nothing to do"
    exit 0
fi
if [ ${#PERSIST_DIRS[@]} -gt 1 ]; then
    log "WARNING: coral config found on ${#PERSIST_DIRS[@]} pools: ${PERSIST_DIRS[*]}"
    log "WARNING: using ${PERSIST_DIRS[0]} (alphabetically first). Remove duplicates to silence this warning."
fi
PERSIST_DIR="${PERSIST_DIRS[0]}"

CORAL_RAW_BACKUP="${PERSIST_DIR}/coral.raw"
SYSEXT_TARGET="/usr/share/truenas/sysext-extensions/coral.raw"

# Read which repo this install came from (written by install.sh)
CORAL_REPO="truenas-community-sysexts/coral-pcie-support"
if [ -f "${PERSIST_DIR}/.coral-repo" ]; then
    CORAL_REPO=$(cat "${PERSIST_DIR}/.coral-repo" 2>/dev/null) || CORAL_REPO="truenas-community-sysexts/coral-pcie-support"
    [ -z "$CORAL_REPO" ] && CORAL_REPO="truenas-community-sysexts/coral-pcie-support"
fi

if [ ! -f "$CORAL_RAW_BACKUP" ]; then
    log "No coral.raw backup at ${CORAL_RAW_BACKUP}, nothing to do"
    exit 0
fi

# --- Compare checksums and reinstall if needed ---
NEED_COPY=true
if [ -f "$SYSEXT_TARGET" ]; then
    INSTALLED_SUM=$(sha256sum "$SYSEXT_TARGET" | awk '{print $1}')
    BACKUP_SUM=$(sha256sum "$CORAL_RAW_BACKUP" | awk '{print $1}')
    if [ -z "$INSTALLED_SUM" ] || [ -z "$BACKUP_SUM" ]; then
        log "WARNING: failed to read sha256 (installed='${INSTALLED_SUM}', backup='${BACKUP_SUM}'); reinstalling defensively"
    elif [ "$INSTALLED_SUM" = "$BACKUP_SUM" ]; then
        log "coral.raw already matches backup, skipping copy"
        NEED_COPY=false
    else
        log "coral.raw differs from backup (update detected), reinstalling..."
    fi
else
    log "coral.raw missing, installing from backup..."
fi

if [ "$NEED_COPY" = true ]; then
    log "Removing old coral sysext..."
    rm -f /run/extensions/coral.raw
    systemd-sysext unmerge 2>/dev/null || true

    log "Making /usr writable..."
    USR_DATASET=$(zfs list -H -o name /usr 2>/dev/null) || true
    if [ -n "$USR_DATASET" ]; then
        zfs set readonly=off "$USR_DATASET"
        USR_WAS_WRITABLE=1
    fi

    log "Copying coral.raw from backup..."
    if ! cp "$CORAL_RAW_BACKUP" "$SYSEXT_TARGET"; then
        log "ERROR: Failed to copy coral.raw from backup"
        exit 1
    fi

    if [ -n "$USR_DATASET" ]; then
        zfs set readonly=on "$USR_DATASET"
        USR_WAS_WRITABLE=0
    fi
fi

# --- Always activate sysext (symlink is on tmpfs, gone after reboot) ---
log "Activating coral sysext..."
mkdir -p /run/extensions
ln -sf "$SYSEXT_TARGET" /run/extensions/coral.raw
systemd-sysext refresh
ldconfig

# --- Check kernel version matches the modules in the sysext ---
# Both gasket.ko and apex.ko must be present for the running kernel.
running_kver=$(uname -r)
GASKET_KO="/usr/lib/modules/${running_kver}/extra/gasket.ko"
APEX_KO="/usr/lib/modules/${running_kver}/extra/apex.ko"
if [ -f "$GASKET_KO" ] && [ -f "$APEX_KO" ]; then
    log "Loading Coral modules..."
    gasket_ok=1
    if [ -e /sys/module/gasket ]; then
        log "gasket module already loaded, skipping insmod"
    else
        insmod_rc=0
        insmod_err=$(insmod "$GASKET_KO" 2>&1) || insmod_rc=$?
        if [ "$insmod_rc" -ne 0 ]; then
            gasket_ok=0
            log "ERROR: insmod gasket failed (rc=${insmod_rc}): ${insmod_err:-no output from insmod}"
            log "ERROR: check 'dmesg | grep -i gasket' for the kernel reason; a TrueNAS update can introduce a driver/kernel ABI mismatch"
            log "ERROR: if so, install a coral.raw release matching ${running_kver} from https://github.com/${CORAL_REPO}/releases"
        fi
    fi

    # apex binds to gasket's symbols, so only attempt it if gasket is present.
    if [ "$gasket_ok" -eq 1 ]; then
        if [ -e /sys/module/apex ]; then
            log "apex module already loaded, skipping insmod"
        else
            insmod_rc=0
            insmod_err=$(insmod "$APEX_KO" 2>&1) || insmod_rc=$?
            if [ "$insmod_rc" -ne 0 ]; then
                log "ERROR: insmod apex failed (rc=${insmod_rc}): ${insmod_err:-no output from insmod}"
                log "ERROR: check 'dmesg | grep -i apex' for the kernel reason"
            fi
        fi
    else
        log "ERROR: skipping apex because gasket is not loaded (apex depends on gasket)"
    fi
else
    SYSEXT_KVER=""
    for d in /usr/lib/modules/*/; do
        [ -d "$d" ] || continue
        name=${d%/}
        name=${name##*/}
        if [ "$name" != "$running_kver" ] && [ -f "${d}extra/gasket.ko" ] && [ -f "${d}extra/apex.ko" ]; then
            SYSEXT_KVER="$name"
            break
        fi
    done
    if [ -n "$SYSEXT_KVER" ]; then
        log "ERROR: Kernel version mismatch: running ${running_kver} but sysext has modules for ${SYSEXT_KVER}"
        log "ERROR: TrueNAS was likely updated. Download a new coral.raw release matching ${running_kver}"
        log "ERROR: Visit https://github.com/${CORAL_REPO}/releases"
    else
        log "WARNING: gasket.ko/apex.ko not found at /usr/lib/modules/${running_kver}/extra/"
    fi
fi

# --- Reload udev rules from sysext so /dev/apex_0 gets correct permissions ---
log "Reloading udev rules..."
udevadm control --reload-rules 2>/dev/null || true
if [ -e /dev/apex_0 ]; then
    udevadm trigger --subsystem-match=apex 2>/dev/null || true
fi

log "Done"
exit 0
