# Install Reference

> **Runs as root.** `install.sh` performs privileged operations (writes to a data pool, manages sysexts via `systemd-sysext`, calls `midclt`, loads kernel modules), so it must run as root. Use `sudo` as shown in every example below. `--check` and `--dry-run` also require root; only `--help` runs without it.

## The one-liner: get.sh

```bash
curl -fsSL https://raw.githubusercontent.com/truenas-community-sysexts/coral-pcie-support/main/get.sh | sudo bash
```

`get.sh` lives on `main` and is the entry point for install, check and uninstall. It:

1. reads the TrueNAS version (`midclt call system.info`) and derives the **train**: the major version from 26 on (every 26.x release, betas included, is train `26`), major.minor before that (`25.10`), and reads the running kernel (`uname -r`);
2. lists this repo's releases and picks the newest one **approved for that train** and **built for that kernel** (see [How a release is chosen](#how-a-release-is-chosen));
3. downloads that release's `install.sh`, `coral-lib.sh`, `coral.raw` and `coral.raw.sha256`, checks the image against the checksum, and runs that release's installer with your arguments and the local image, so the image and the scripts always come from the same release.

| `get.sh` option | Description |
| --- | --- |
| `--release=TAG` | Use that release as given, with no selection (for example to test a build before it is approved) |
| `--uninstall` | Run the approved release's `uninstall.sh` (with its `restore.sh` and `coral-lib.sh`) instead of installing |
| `--repo=OWNER/NAME` | Use a fork's releases (also `CORAL_REPO`) |
| anything else | Passed to `install.sh` (or, with `--uninstall`, to `restore.sh`), e.g. `--pool=fast`, `--check`, `--dry-run`, `--force` |

Options go after `bash -s --`:

```bash
curl -fsSL https://raw.githubusercontent.com/truenas-community-sysexts/coral-pcie-support/main/get.sh | sudo bash -s -- --pool=fast
curl -fsSL https://raw.githubusercontent.com/truenas-community-sysexts/coral-pcie-support/main/get.sh | sudo bash -s -- --check
curl -fsSL https://raw.githubusercontent.com/truenas-community-sysexts/coral-pcie-support/main/get.sh | sudo bash -s -- --uninstall
```

`--check`, `--help`, `--uninstall` and a path to your own image only use the release's scripts, so on a box whose kernel has no approved build yet they take the newest approved release **built for the box's own train** (by the TrueNAS version in its release notes). A release built for another train never serves them, grandfathered or not: an older train's `--check` inspects another install layout, and its `restore.sh` runs another removal flow. With none, they stop and name the waiting hardware test; `--release=TAG` uses a release anyway.

## How a release is chosen

The same selection runs in `get.sh`, `install.sh` (when it is not given an image or `--release`) and `uninstall.sh` (when it has no `restore.sh` beside it). A release is a candidate when:

- it is **approved for this box's train**: its release notes carry `<!-- verified-train: <train> -->` for the train, written by `promote.yml` when the build's hardware-test issue is closed as completed, or it is a full release with no such marker at all (promoted before per-train sign-off, approved for every train);
- it is on this box's **channel**: a stable box never takes a preview (BETA/RC) build, and only takes full (promoted) releases;
- it was **built for this kernel**: its `Target kernel` notes row equals `uname -r` (or, for a release whose notes lost the row, its `k<kernel>-...` tag names the kernel; releases older than the row match by exact TrueNAS version).

The newest candidate wins. **Nothing unapproved is ever installed**, on stable or preview boxes: with no candidate, the installer stops, lists the builds for this kernel that are waiting for a hardware test, and names the open hardware-test issue for them, or says that none exists yet.

## Installing a Specific Version

Release tags encode the kernel the build targets: `k<kernel>-gasket<driver>-r<run>` (e.g., `k6.12.91-gasket1.0-18.4-r41`). Releases published before the kernel-keyed migration keep their older `v<truenas>-gasket<driver>-r<run>` tags (e.g., `v25.10.3.1-gasket1.0-18-r23`); both install the same way. The README supported versions table maps TrueNAS versions to the release serving them.

To install a specific release, approved or not, pin it with `--release`:

```bash
curl -fsSL https://raw.githubusercontent.com/truenas-community-sysexts/coral-pcie-support/main/get.sh | sudo bash -s -- --release=k6.12.91-gasket1.0-18.4-r41
```

Or install that exact release's `coral.raw` from a local directory. `install.sh` loads `coral-lib.sh` from beside itself, so download both next to the image:

```bash
TAG=k6.12.91-gasket1.0-18.4-r41   # replace with the release tag you want
mkdir -p /tmp/coral-install && cd /tmp/coral-install
for f in coral.raw coral.raw.sha256 install.sh coral-lib.sh; do
  curl -fsSL -o "$f" "https://github.com/truenas-community-sysexts/coral-pcie-support/releases/download/${TAG}/$f"
done
sha256sum -c coral.raw.sha256   # must print: coral.raw: OK
sudo bash install.sh coral.raw
```

> **Warning:** Using a `coral.raw` built for a different kernel will fail to load
> the kernel module. The module is compiled against exact kernel headers, so a kernel mismatch
> means `insmod` will refuse to load it. Always use the release matching your running kernel
> (`uname -r`); the installer checks this before touching the system.

## Install Options

| Option | Description |
| --- | --- |
| `--repo=OWNER/NAME` | GitHub repo for releases (default: `truenas-community-sysexts/coral-pcie-support`). Also settable via `CORAL_REPO` env var. |
| `--pool=NAME` | ZFS pool for persistent config (e.g., `fast`) |
| `--persist-path=PATH` | Persistent config directory. Must be `/mnt/<pool>/.config/coral` (the exact location the boot-time PREINIT script scans). Prefer `--pool`, which builds this path for you. |
| `--release=TAG` | Install that release, with no selection. With a path to `coral.raw` as well (what `get.sh` passes), the image is used and recorded as that release's |
| `--check` | Probe an existing install (read-only) and report status |
| `--dry-run` | Validate everything (downloads, checksums, network) without modifying the system |
| `--help` | Show usage help |

## Probing and Validating

**`--check`** performs a read-only probe of an existing install: device node, kernel modules (gasket + apex), sysext file/merge state, persistent config + backup, PREINIT script + middleware registration, kernel-version match, and PREINIT boot result. Each failure includes a one-line hint. Exits 1 if any check fails.

```bash
# Probe an existing install
sudo ./install.sh --check
# Or via curl
curl -fsSL https://raw.githubusercontent.com/truenas-community-sysexts/coral-pcie-support/main/get.sh | sudo bash -s -- --check
```

**`--dry-run`** performs every read/network/validation step (release lookup, sha256 verify, squashfs unpack) but skips every command that mutates the running system. Each skipped mutation is logged as `[dry-run] would: <command>`.

`--check` and `--dry-run` are mutually exclusive.

## What the Install Script Does

1. **Downloads `coral.raw`** from the newest release approved for your TrueNAS train and built for your running kernel (or uses a local file, which is how `get.sh` hands it the image)
2. **Verifies the checksum** (SHA256)
3. **Extracts the PREINIT script** from inside the sysext squashfs
4. **Installs the sysext** to `/mnt/<pool>/.config/coral/coral.raw` on a data pool
5. **Activates the sysext** in place via TrueNAS's symlink + refresh pattern
6. **Loads the kernel modules** via `insmod` (gasket first, then apex)
7. **Sets up persistence** (see below)

## Persistence

TrueNAS updates replace the rootfs, which wipes `/usr/` and any installed sysext. The install script sets up automatic recovery:

### Recovery Process

1. **Image on the data pool**: The sysext is written to a persistent ZFS pool, and that is the copy `/run/extensions/` activates
2. **PREINIT script**: Registered with TrueNAS middleware, runs on every boot before apps start
3. On boot, the script re-points `/run/extensions/coral.raw` at the data-pool image and runs `systemd-sysext refresh`. Because the image lives on the data pool (not `/usr`), a TrueNAS update cannot wipe it, so the same path works on every boot
4. No network access is needed at boot

### Persistent Storage Layout

```text
/mnt/<pool>/.config/coral/
├── coral.raw                ← Sysext image, activated in place
├── .coral-driver-version    ← Gasket driver version (informational)
├── .coral-repo              ← Source GitHub repo (used by preinit for error messages)
└── coral-preinit.sh         ← Boot script (extracted from coral.raw, registered as PREINIT)
```

### Pool Selection

The install script selects a pool in this order:

1. `--persist-path=PATH` (use this exact path, highest priority)
2. `--pool=NAME` (use `/mnt/<NAME>/.config/coral`)
3. **Auto-detect** (first ZFS pool that isn't `boot-pool`)

The PREINIT script finds the config at boot by scanning `/mnt/*/.config/coral/`, so it works even if the pool name changes.

## Device Permissions

The sysext ships a udev rule (`51-coral-udev.rules`) that sets `/dev/apex*` to mode `0666` (world read/write). This is intentional: Docker containers typically run as non-root and need direct device access without extra group configuration. On a single-user TrueNAS box this is fine.

If you want tighter permissions, edit the rule in the sysext to use `GROUP="video"` with `MODE="0660"` and add your container user to the `video` group. Note that the sysext is a squashfs image, so you'd need to unpack, edit, and repack it (or patch the rule in the build workflow for a permanent change).

## Scripts Reference

| Script | Purpose |
| --- | --- |
| `get.sh` | Bootstrap on `main`: picks the approved release for this box and runs that release's `install.sh` (or `uninstall.sh`) |
| `scripts/install.sh` | Downloads release, installs sysext, sets up persistence |
| `scripts/uninstall.sh` | Discoverable alias: runs `restore.sh`, fetching it from the approved release when there is none beside it |
| `scripts/restore.sh` | Uninstalls sysext, deregisters init script, cleans up persistent storage |
| `scripts/coral-preinit.sh` | Boot-time script: activates sysext before apps start (bundled inside coral.raw at `/usr/lib/coral/`) |
