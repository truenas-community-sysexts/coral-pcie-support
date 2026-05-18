# Build Pipeline Architecture

## Overview

This project builds a systemd-sysext package (`coral.raw`) containing the Google Coral PCIe TPU driver for TrueNAS SCALE. The sysext is a squashfs image that overlays `/usr/` via overlayfs when activated with `systemd-sysext refresh`.

The Coral PCIe TPU requires two kernel modules (`gasket.ko` and `apex.ko`) and nothing else: no firmware download, no userspace library, no CLI tool. This makes the build and install simpler than other accelerator sysexts.

## Why Not scale-build?

The gasket/apex driver is a standard out-of-tree kernel module that only needs:
- Kernel headers matching the target TrueNAS kernel
- Standard build toolchain (gcc, make)
- gasket-driver source code

This means we can skip scale-build entirely, reducing build time from hours to minutes.

## Build Pipeline

```
┌──────────────────────────────────────────────────────────────┐
│  Single GitHub Actions Job (runner resolved per-build)       │
│                                                              │
│  1. Download TrueNAS ISO (cached)                            │
│  2. Extract kernel headers from nested squashfs (cached)     │
│  3. Detect real kernel version from headers                  │
│  4. Clone google/gasket-driver, apply kernel compat patches  │
│  5. Build gasket.ko + apex.ko (gcc matching kernel)          │
│  6. Assemble sysext tree (NO firmware, NO depmod)            │
│  7. mksquashfs -> coral.raw (zstd compressed)                │
│  8. Create GitHub release                                    │
└──────────────────────────────────────────────────────────────┘
```

### Build Environment

The runner image is resolved per-build so it stays compatible with whatever Debian release TrueNAS is on (the runner's GLIBC must be <= the TrueNAS rootfs's). For example, Debian Bookworm (GLIBC 2.36) maps to **ubuntu-22.04** (GLIBC 2.35); Ubuntu 24.04 (GLIBC 2.39) would produce binaries that won't run on a Bookworm-based rootfs. The current mapping table lives in [`.github/scripts/resolve-runner.sh`](../.github/scripts/resolve-runner.sh).

The kernel modules are compiled with **gcc-12** because the TrueNAS kernel was built with GCC 12, which uses `-ftrivial-auto-var-init=zero`, a flag not supported by GCC 11 (ubuntu-22.04's default).

#### Build runner resolution

Both auto-bump check workflows resolve the runner before dispatching `build.yml`, then pass it as an input. The lookup is two cheap fetches against TrueNAS's own published build metadata (no ISO download needed):

1. `download.truenas.com/TrueNAS-SCALE-<train>/<version>/GITMANIFEST` (~2 KB) pins the `truenas-build` commit that produced the ISO.
2. `raw.githubusercontent.com/truenas/truenas-build/<sha>/conf/build.manifest` declares `debian_release:` (e.g. `"bookworm"`).
3. A `case` statement in `.github/scripts/resolve-runner.sh` maps the Debian release to an Ubuntu runner image with a compatible GLIBC.

When TrueNAS rebases onto a new Debian release, the auto-bump checks fail loud (`::error::unknown debian_release '<codename>'`) on the first scheduled run after the rebase. The fix is a one-line addition to the `case` statement. Detection is automated; the actual mapping decision stays human.

### Caching Strategy

Two levels of caching minimize build times:

| Cache | Key | Contents | Saves |
| --- | --- | --- | --- |
| TrueNAS ISO | `truenas-iso-{version}` | The ~1.3 GB ISO download | ~2-3 min |
| Kernel headers | `kernel-headers-v3-{version}` | Extracted headers + `.real-kver` | ~3-5 min |

No userspace build cache is needed (unlike the Hailo sysext, there is no HailoRT library or CLI tool to compile).

Cache keys include version prefixes (e.g., `v3-`) to allow invalidation when the extraction logic changes.

### Step Detail: Kernel Header Extraction

TrueNAS ISOs have a nested squashfs structure:

```
TrueNAS-SCALE-25.10.2.1.iso
├── live/filesystem.squashfs      <- installer-only (NO kernel headers)
└── TrueNAS-SCALE.update          <- outer squashfs containing:
    └── rootfs.squashfs           <- full rootfs with headers at:
        └── usr/src/linux-headers-truenas-production-amd64/
```

The extraction step:

1. Mounts the ISO
2. Extracts `rootfs.squashfs` from `TrueNAS-SCALE.update`
3. Extracts `usr/src/linux-headers-*` and `lib/modules/*` from the rootfs
4. Selects the production headers (prefers `production` keyword, avoids `debug`)

### Step Detail: Kernel Version Detection

TrueNAS uses non-standard kernel header directory names. The header package is named `linux-headers-truenas-production-amd64`, but the actual kernel version (what `uname -r` returns) is something like `6.12.33-production+truenas`. These must match for the kernel module to load.

The build detects the real kernel version via:

1. **`include/config/kernel.release`** in the headers directory (most reliable)
2. **`/lib/modules/` directory names** from the rootfs (fallback)
3. **Header directory name** (last resort, may not work)

Both `KVER` (header dir name, used for compilation) and `REAL_KVER` (actual kernel version, used for module install path) are tracked separately.

### Step Detail: Kernel Module Build

```bash
cd gasket-driver/src
make CC=gcc-12 KDIR=/path/to/linux-headers-<KVER> modules
```

This produces `gasket.ko` and `apex.ko`. The `CC=gcc-12` is critical: without it, GCC 11 fails on the `-ftrivial-auto-var-init=zero` flag baked into the kernel's build config.

#### Kernel compatibility patches

The upstream `google/gasket-driver` repository is archived and has not been updated for newer kernel APIs. The `patches/` directory contains compatibility patches adapted from [feranick/gasket-driver](https://github.com/feranick/gasket-driver) that fix build failures against modern kernels (6.x+):

- `0001-gasket-remove-llseek-assignment.patch` - removed `llseek` field (kernel API change)
- `0002-gasket-class-create-single-arg.patch` - `class_create()` signature change
- `0003-gasket-eventfd-signal-single-arg.patch` - `eventfd_signal()` signature change
- `0004-gasket-module-import-ns-quoting.patch` - `MODULE_IMPORT_NS()` quoting change

The `patches/apply-patches.sh` script applies each patch conditionally, skipping any that are already applied or not applicable to the target kernel.

### Step Detail: Sysext Assembly

The assembly step explicitly does **NOT**:

- Include firmware (none needed for Coral)
- Run `depmod` (would overwrite the base system's `modules.dep` via overlayfs, breaking all other kernel modules)
- Include any userspace library or CLI tool (the Coral TPU needs only kernel modules)

## Sysext Structure

```text
coral.raw (squashfs, zstd compressed)
└── usr/
    ├── lib/
    │   ├── extension-release.d/
    │   │   └── extension-release.coral    # ID=_any
    │   ├── modules/<REAL_KVER>/
    │   │   └── extra/
    │   │       ├── gasket.ko
    │   │       └── apex.ko
    │   ├── coral/
    │   │   └── coral-preinit.sh           # PREINIT script (extracted by install.sh)
    │   ├── systemd/system/
    │   │   ├── coral-load.service
    │   │   └── multi-user.target.wants/coral-load.service
    │   └── udev/rules.d/
    │       └── 51-coral-udev.rules
    └── (no usr/bin/ - no CLI tool needed)
```

### extension-release

The file `usr/lib/extension-release.d/extension-release.coral` contains `ID=_any`, matching the pattern used by TrueNAS's own NVIDIA sysext. This makes the extension compatible regardless of the OS ID string.

### Module Path

The kernel modules are placed at `usr/lib/modules/<REAL_KVER>/extra/gasket.ko` and `usr/lib/modules/<REAL_KVER>/extra/apex.ko` where `<REAL_KVER>` is the actual kernel version string (e.g., `6.12.33-production+truenas`), **not** the header package name. On TrueNAS, `/lib` is a symlink to `/usr/lib`, so after sysext merge the modules appear at `/lib/modules/<REAL_KVER>/extra/`.

### Module Loading

The `coral-load.service` uses `insmod` with absolute paths instead of `modprobe`:

```ini
ExecStart=/bin/bash -c '[ -e /sys/module/gasket ] || /sbin/insmod /usr/lib/modules/$(uname -r)/extra/gasket.ko'
ExecStart=/bin/bash -c '[ -e /sys/module/apex ] || /sbin/insmod /usr/lib/modules/$(uname -r)/extra/apex.ko'
```

This is necessary because `/lib/modules/` is on a read-only ZFS dataset on TrueNAS. `depmod` cannot write module dependency files, so `modprobe` cannot find the module. `insmod` bypasses module dependency resolution entirely, loading the `.ko` directly by path.

The load order matters: `gasket.ko` must be loaded first because `apex.ko` depends on the gasket framework. The `[ -e /sys/module/... ]` guards make each line idempotent. The PREINIT script normally loads the modules before `multi-user.target`, so by the time this service runs they are already in the kernel and the insmod calls are skipped. The service still acts as a backup if PREINIT registration is broken.

## TrueNAS Sysext Activation

TrueNAS does **not** use the standard `systemd-sysext merge` path (`/var/lib/extensions/`). Instead, the TrueNAS middleware uses a symlink pattern:

```
/usr/share/truenas/sysext-extensions/coral.raw  <- the actual file
           | symlink
/run/extensions/coral.raw                       <- where systemd-sysext looks
           | systemd-sysext refresh
/usr/ overlayfs merge                           <- files appear in /usr/
```

The activation sequence:

1. Place `coral.raw` at `/usr/share/truenas/sysext-extensions/coral.raw`
2. Create symlink: `ln -sf /usr/share/truenas/sysext-extensions/coral.raw /run/extensions/coral.raw`
3. `systemd-sysext refresh` - merges the sysext via overlayfs
4. `ldconfig` - updates shared library cache

The deactivation sequence:

1. `rm -f /run/extensions/coral.raw`
2. `systemd-sysext refresh` - unmerges

**Note:** Raw `systemd-sysext merge` does not work on TrueNAS because `/var/lib/extensions/` does not exist.

## Persistence Mechanism

TrueNAS updates replace the rootfs, wiping any sysext placed in `/usr/`. The persistence mechanism has two layers:

### Layer 1: Persistent Storage

Config stored on a ZFS data pool (survives OS updates):

```text
/mnt/<pool>/.config/coral/
├── coral.raw                - Backup of the sysext
├── .coral-driver-version    - Gasket driver version (informational)
├── .coral-repo              - Source repo for error output (informational)
└── coral-preinit.sh         - The PREINIT script itself
```

### Layer 2: PREINIT Script

A script registered with TrueNAS via `midclt call initshutdownscript.create` with `"when": "PREINIT"`. Runs on every boot **before the middleware starts**, which means the Coral TPU device is ready before app containers (e.g., Frigate) launch.

Why PREINIT and not POSTINIT:

- PREINIT runs after ZFS pools are mounted but before the middleware starts apps
- POSTINIT runs after the middleware is up, by which time app containers may already be starting
- The script only uses `zfs`, `cp`, `systemd-sysext`, and `insmod`, all available at PREINIT time
- The timeout is set to 30 seconds (default is 10, which is too tight for the copy + sysext refresh)

The script:

1. Finds backup at `/mnt/<pool>/.config/coral/coral.raw` (scans `/mnt/*/.config/coral/`)
2. Compares SHA256 checksum with installed sysext
3. If different (TrueNAS updated) or missing: copies from backup to `/usr/` (temporarily unlocks ZFS readonly)
4. **Always** activates sysext via symlink + refresh (the `/run/extensions/` symlink is on tmpfs and gone after every reboot)
5. Loads kernel modules via `insmod` (gasket first, then apex)

The script is idempotent. On a normal reboot where checksums match, it skips the copy but still activates the sysext and loads the modules.

### Pool Selection

The install script selects a persistent storage pool in this order:

1. `--persist-path=PATH` - exact path (highest priority)
2. `--pool=NAME` - specific pool name, resolves to `/mnt/<NAME>/.config/coral`
3. **Auto-detect** - first ZFS pool that is not `boot-pool`, resolves to `/mnt/<pool>/.config/coral`

## Read-Only Filesystem Constraints

TrueNAS has multiple read-only ZFS datasets:

| Path | Writable? | Notes |
| --- | --- | --- |
| `/usr` | No (ZFS readonly) | Can be temporarily unlocked via `zfs set readonly=off` |
| `/lib` | No (separate ZFS dataset) | Symlink to `/usr/lib` but on its own readonly dataset |
| `/lib/modules` | No | Part of the `/lib` dataset |
| `/run/extensions` | Yes (tmpfs) | Where sysext symlinks go |
| `/mnt/<pool>` | Yes | ZFS data pools, persistent |

This is why:

- `insmod` is used instead of `modprobe` (can't run `depmod` on read-only `/lib/modules`)
- The install script temporarily unlocks `/usr` to place `coral.raw`

## Automated Version Monitoring

A daily workflow (`check-releases.yml`, 06:00 UTC) monitors TrueNAS releases and updates `.github/tracked-versions.json`.

### TrueNAS half

Queries `truenas/scale-build` GitHub tags for the highest stable `TS-*` release. When found:

- Resolves the train name from `download.truenas.com`'s directory listing
- Gates on the matching ISO actually being published (tags can land hours before the ISO)
- Updates `truenas.version` and `truenas.train` in `tracked-versions.json`

This is critical because a new TrueNAS release may ship a different kernel, requiring recompiled kernel modules.

### Gasket driver

The gasket-driver version is manually pinned in `tracked-versions.json`. The upstream repository ([google/gasket-driver](https://github.com/google/gasket-driver)) is archived and receives no new releases, so there is no automated bump to track. If the driver version ever needs to change, it is updated by hand.

### Consolidated commit and dispatch

If the TrueNAS version moved, the workflow writes the state file in one commit and dispatches a single build with `mark_latest='false'`. Auto-builds publish releases without the "Latest" badge. A human verifies the build on Coral hardware and promotes it via the GitHub UI.
