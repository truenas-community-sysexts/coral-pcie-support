# Changelog

Changes since the initial project baseline, organized by area.

## Per-Train Approval and get.sh

- **Nothing untested is installed.** A build installs only once a hardware test on the TrueNAS train it was built for signs it off: `promote.yml` appends `<!-- verified-train: <train> -->` to the release notes when the build's `hardware-test` or `preview-hardware-test` issue is closed as completed. The train is the major version from 26 on (every 26.x release, betas included, is `26`) and major.minor before that (`25.10`), taken from the release notes header. A full release with no marker (promoted before per-train sign-off) stays approved for every train.
- **Preview boxes no longer install unverified beta builds.** A preview build installs only after its preview hardware test; there is no fallback to an unverified build on stable or preview boxes. Preview builds signed off before the change get a one-time `verified-train: 26` marker.
- **Selection: one extra check on the kernel-keyed code.** `install.sh`'s release selection keeps its kernel match (`Target kernel` row, k-tag fallback, legacy version fallback), channel gate, pagination and image-kernel guard, and adds the approved-for-train check to its candidate filter. With nothing approved for the kernel it names the open hardware-test issue waiting for a tester, or says none exists yet.
- **`get.sh` bootstrap on `main`.** The new README one-liner (`curl -fsSL https://raw.githubusercontent.com/truenas-community-sysexts/coral-pcie-support/main/get.sh | sudo bash`) selects the release with the same code, downloads that release's `install.sh`, `coral-lib.sh`, `coral.raw` and `coral.raw.sha256`, checks the image, and runs that release's installer with the local image (every release's installer accepts one). `--check`, `--help`, `--uninstall` and a user's own image use only the release's scripts: on a kernel with no approved build they take the newest approved release built for the box's own train, never one built for another train (grandfathered or not). `--uninstall` runs its `uninstall.sh`. `--release=TAG` pins a release, `--repo=` a fork. The selection functions are one block kept verbatim in `get.sh`, `install.sh` and `uninstall.sh`, and CI fails when the copies differ.
- **No more `releases/latest` downloads.** `install.sh` loads `coral-lib.sh` from beside itself or from the release it installs (or, for `--check`, an approved one), and `uninstall.sh` fetches `restore.sh` and `coral-lib.sh` from the approved release. `install.sh --release=TAG` installs that release without selection; with a local image it records the image as that release's.
- **No untested publish path.** `build.yml`'s `mark_latest` input is removed: every build publishes as a pre-release and opens its hardware-test issue, which names the train it approves the build for. `check-releases.yml` no longer passes the input.
- **Coverage gate counts approved releases.** `check-kernel-coverage.py` counts a promoted release as coverage only when it is approved for the new version's train (its marker, or no marker at all); a stable sign-off promotes and marks in one update, so promoted builds stay covered. The Latest-is-a-k-tag guard is unchanged.

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

- **Data-pool-only activation (no boot-pool copy).** `install.sh`, `restore.sh`, and `coral-preinit.sh` now point `/run/extensions/coral.raw` straight at the image on the data pool (`${PERSIST_DIR}/coral.raw`) instead of copying it onto the boot pool under `/usr/share/truenas/sysext-extensions/`. `systemd-sysext` loop-mounts the symlink target regardless of the backing filesystem, so the ZFS data-pool path activates the same way. This removes every `zfs set readonly=off/on` toggle on `/usr` and the boot-pool copy. The boot-pool copy never survived a TrueNAS update anyway (`/usr` is recloned fresh), so the data-pool image plus the PREINIT symlink was already the only thing carrying activation across updates. Supersedes the `/usr` readonly-restore trap and the boot-pool install/copy entries below.
- **`systemd-sysext unmerge` before ZFS writes.** `install.sh` and `restore.sh` now `unmerge` the sysext (rather than `refresh`) before unlocking `/usr`, so the overlay does not block the remount. Without this, repeated installs/restores would intermittently fail when another sysext (e.g. NVIDIA) is active.
- **PREINIT script bundled in `coral.raw`.** `scripts/coral-preinit.sh` ships inside the sysext at `/usr/lib/coral/coral-preinit.sh`. `install.sh` extracts it during a dedicated unsquashfs step.
- **`/usr` readonly restored on signal.** All scripts install a `trap restore_usr_readonly EXIT INT TERM` so a SIGINT/SIGTERM between `zfs set readonly=off` and the matching `readonly=on` does not leave `/usr` writable until reboot.
- **Empty-SHA256 defensive reinstall in PREINIT.** If `sha256sum` returns an empty hash for either the installed sysext or the backup, `coral-preinit.sh` reinstalls from backup rather than treating two empty strings as a match.
- **`coral-load.service` idempotent.** The unit guards on `[ -e /sys/module/gasket ]` / `[ -e /sys/module/apex ]` so it no-ops when PREINIT already loaded the modules. Restart limits (`StartLimitBurst=3`, `StartLimitIntervalSec=60`) cap restart loops on permanent failures.

## Automated Workflows

- **Single check workflow + single state file.** One workflow (`.github/workflows/check-releases.yml`) and one CI-state file (`.github/tracked-versions.json`) for all version tracking.
- **Daily schedule.** The check runs daily at 06:00 UTC.
- **TrueNAS ISO availability gate.** Only bumps the tracked TrueNAS version once the matching ISO is published at `download.truenas.com`.
- **TrueNAS 26 beta preview channel.** A `truenas_preview` block tracks the latest TrueNAS 26 beta (e.g. `26.0.0-BETA.2`). Because 26 betas are not in `scale-build` tags and ship no GITMANIFEST, the check scrapes the browsable channel listing (`iso.sys.truenas.net/TrueNAS-26-BETA/`) for the highest `X.Y.Z-BETA.N`/`-RC.N`, ISO-gates it, and `build.yml` fetches the ISO via an `iso_url` override against a pinned runner. A gasket bump now dispatches **both** a stable (25.x) and a preview (26-beta) build; a TrueNAS-only bump on one channel builds just that channel. Preview builds publish as permanent pre-releases (label `preview-hardware-test`) and are never promoted to Latest, so stable installs are unaffected; `promote.yml` additionally refuses any `BETA`/`RC` tag.
- **Auto-resolved train name.** Picks the highest stable scale-build tag and resolves the train from `download.truenas.com`'s directory listing. New trains are picked up automatically.
- **Gasket driver auto-tracked.** The daily check monitors [feranick/gasket-driver](https://github.com/feranick/gasket-driver) releases for new tags. Feranick maintains kernel compatibility fixes on top of the archived `google/gasket-driver`. No local patches directory needed.
- **`mark_latest` input on `build.yml`.** Auto-built releases publish without claiming "Latest"; a human promotes after hardware verification. (Removed with per-train approval: every build is now a pre-release until its hardware test.)
- **Build runner resolved per-build.** `runs-on:` is resolved from TrueNAS's Debian release via `.github/scripts/resolve-runner.sh`, no longer hardcoded.
- **Runtime-resolved `workflow_dispatch` defaults.** `build.yml`'s dispatch inputs default to blank; the build's `resolve` job reads `.github/tracked-versions.json` at runtime when no explicit value is given, so manual dispatches always target the latest tracked combo without requiring `build.yml` rewrites on each bump.
- **Lint workflow.** `shellcheck --severity=warning` on all shell scripts, `actionlint` on workflow YAML, and `tracked-versions.json` shape validation.
- **Build-time smoke test.** Before publishing, `build.yml` asserts required files exist and `gasket.ko`/`apex.ko` vermagic matches the target kernel.
- **Richer release notes.** Includes real kernel version, runner image, build commit SHA, and Frigate compatibility note.
- **Dependabot for `github-actions`.** Weekly PRs to bump action versions.
