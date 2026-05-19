# Changelog

Changes since the initial project baseline, organized by area.

## Install / Restore Scripts

- **Custom source repository.** `install.sh` accepts `--repo=OWNER/NAME` and the `CORAL_REPO` environment variable, so installs from a fork pull artifacts from the fork's releases instead of upstream. The selected repo is recorded in `${PERSIST_DIR}/.coral-repo`.
- **Branch-aware preinit error messages.** `coral-preinit.sh` reads `.coral-repo` and points kernel-mismatch error output at the source repo's releases page.
- **Bounded curl downloads.** `install.sh` caps every release/install-script download with `--max-time`, so a stalled connection fails fast instead of hanging the install indefinitely.
- **`install.sh --check`.** Read-only probe of an existing install: device node, kernel modules (gasket + apex), sysext file/merge state, persistent config + backup, PREINIT script + middleware registration, kernel-version match, and PREINIT boot result. Each failure includes a one-line hint. Exits 1 if any check fails.
- **`install.sh --dry-run`.** Performs every read/network/validation step (release lookup, sha256 verify, squashfs unpack) but skips every command that mutates the running system. Each skipped mutation is logged as `[dry-run] would: <command>`. Mutually exclusive with `--check`.
- **`/tmp/coral.raw` self-copy guard.** Prevents `install.sh /tmp/coral.raw` from colliding with the installer's staging path.
- **`midclt` lookup refused on transient error.** Distinguishes "not registered" from "lookup error" and aborts on the latter rather than guessing.
- **`scripts/uninstall.sh` wrapper.** Discoverable alias around `restore.sh` for users who search for "uninstall" rather than "restore".
- **Dual-module load order.** gasket.ko is loaded before apex.ko (dependency order). Unload is reversed (apex first).

## Sysext Activation on TrueNAS

- **`systemd-sysext unmerge` before ZFS writes.** `install.sh` and `restore.sh` now `unmerge` the sysext (rather than `refresh`) before unlocking `/usr`, so the overlay does not block the remount. Without this, repeated installs/restores would intermittently fail when another sysext (e.g. NVIDIA) is active.
- **PREINIT script bundled in `coral.raw`.** `scripts/coral-preinit.sh` ships inside the sysext at `/usr/lib/coral/coral-preinit.sh`. `install.sh` extracts it during a dedicated unsquashfs step.
- **`/usr` readonly restored on signal.** All scripts install a `trap restore_usr_readonly EXIT INT TERM` so a SIGINT/SIGTERM between `zfs set readonly=off` and the matching `readonly=on` does not leave `/usr` writable until reboot.
- **Empty-SHA256 defensive reinstall in PREINIT.** If `sha256sum` returns an empty hash for either the installed sysext or the backup, `coral-preinit.sh` reinstalls from backup rather than treating two empty strings as a match.
- **`coral-load.service` idempotent.** The unit guards on `[ -e /sys/module/gasket ]` / `[ -e /sys/module/apex ]` so it no-ops when PREINIT already loaded the modules. Restart limits (`StartLimitBurst=3`, `StartLimitIntervalSec=60`) cap restart loops on permanent failures.

## Automated Workflows

- **Single check workflow + single state file.** One workflow (`.github/workflows/check-releases.yml`) and one CI-state file (`.github/tracked-versions.json`) for all version tracking.
- **Daily schedule.** The check runs daily at 06:00 UTC.
- **TrueNAS ISO availability gate.** Only bumps the tracked TrueNAS version once the matching ISO is published at `download.truenas.com`.
- **Auto-resolved train name.** Picks the highest stable scale-build tag and resolves the train from `download.truenas.com`'s directory listing. New trains are picked up automatically.
- **Gasket driver auto-tracked.** The daily check monitors [feranick/gasket-driver](https://github.com/feranick/gasket-driver) releases for new tags. Feranick maintains kernel compatibility fixes on top of the archived `google/gasket-driver`. No local patches directory needed.
- **`mark_latest` input on `build.yml`.** Auto-built releases publish without claiming "Latest"; a human promotes after hardware verification.
- **Build runner resolved per-build.** `runs-on:` is resolved from TrueNAS's Debian release via `.github/scripts/resolve-runner.sh`, no longer hardcoded.
- **Runtime-resolved `workflow_dispatch` defaults.** `build.yml`'s dispatch inputs default to blank; the build's `resolve` job reads `.github/tracked-versions.json` at runtime when no explicit value is given, so manual dispatches always target the latest tracked combo without requiring `build.yml` rewrites on each bump.
- **Lint workflow.** `shellcheck --severity=warning` on all shell scripts, `actionlint` on workflow YAML, and `tracked-versions.json` shape validation.
- **Build-time smoke test.** Before publishing, `build.yml` asserts required files exist and `gasket.ko`/`apex.ko` vermagic matches the target kernel.
- **Richer release notes.** Includes real kernel version, runner image, build commit SHA, and Frigate compatibility note.
- **Dependabot for `github-actions`.** Weekly PRs to bump action versions.
