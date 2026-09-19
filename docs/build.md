# How It Works

## Build Process

This project compiles the Coral gasket/apex driver standalone (~10-20 minutes):

1. Downloads the TrueNAS ISO for the target version
2. Extracts kernel headers from the nested rootfs squashfs
3. Detects the real kernel version (e.g., `6.12.33-production+truenas`)
4. Clones [feranick/gasket-driver](https://github.com/feranick/gasket-driver) at the tracked ref
5. Compiles `gasket.ko` and `apex.ko` with the kernel-matching GCC against those exact headers
6. Packages everything as a squashfs sysext image

The runner image is resolved per-build from TrueNAS's published Debian release (`bookworm` -> `ubuntu-22.04`), so binaries link against a GLIBC that's no newer than the TrueNAS rootfs's. See [Build runner resolution](architecture.md#build-runner-resolution) for the lookup path.

## TrueNAS-Specific Details

- **Sysext activation** uses TrueNAS's middleware pattern (symlink in `/run/extensions/` + `systemd-sysext refresh`), not the standard `systemd-sysext merge`
- **Module loading** uses `insmod` instead of `modprobe` because `/lib/modules` is on a read-only ZFS dataset where `depmod` cannot write

## Automated Updates

A single daily GitHub Actions workflow (`check-releases.yml`, 06:00 UTC) monitors TrueNAS releases and updates `.github/tracked-versions.json`:

- **TrueNAS stable half**: looks for new TrueNAS releases (highest stable `TS-*` tag in `truenas/scale-build`). When the matching ISO is live at `download.truenas.com`, it stages a bump of `truenas.version` (and `truenas.train` on a train rollover).
- **TrueNAS preview half**: tracks the latest TrueNAS 26 beta (`truenas_preview.version`, e.g. `26.0.0-BETA.2`). TrueNAS 26 betas are not tagged in `scale-build` and ship no GITMANIFEST, so this half scrapes the browsable channel listing in `truenas_preview.channel_url` (`iso.sys.truenas.net/TrueNAS-26-BETA/`), picks the highest `X.Y.Z-BETA.N` / `-RC.N`, and gates on the ISO being uploaded. The runner is pinned (`truenas_preview.runner`, `ubuntu-24.04`) since there is no GITMANIFEST to auto-resolve from, and the build downloads the ISO via an `iso_url` override.
- **Gasket half**: monitors [feranick/gasket-driver](https://github.com/feranick/gasket-driver) releases for new tags. Feranick actively maintains kernel compatibility fixes on top of the archived `google/gasket-driver`. When a new release appears, it bumps `gasket.driver` and `gasket.ref`.

If anything moved, the workflow writes the file in one commit and dispatches builds. A **gasket bump builds both** the stable (25.x) and preview (26-beta) targets, so each driver release ships both; a TrueNAS-only bump on one channel builds just that channel. Every build publishes as a pre-release with a hardware-test issue, and no install receives it until that test signs it off (see [Per-train approval](#per-train-approval)). Stable builds: verify on Coral PCIe hardware, then close the `hardware-test` issue as completed to promote the build and approve it for its train. **Preview (26-beta) builds stay pre-releases permanently and are never promoted to Latest**: closing their `preview-hardware-test` issue as completed approves them for train 26 only.

## Per-train approval

A hardware test approves a build for the TrueNAS **train** it was built for, and nothing unapproved is installed on any box, stable or preview. The train is the major version from 26 on (every 26.x release, betas included, is train `26`) and major.minor before that (`25.10`).

- `build.yml` publishes **every** build as a pre-release and opens one issue for it: `hardware-test` for a stable target, `preview-hardware-test` for a preview (BETA/RC) one. There is no way to publish a build straight to Latest: a full release with no approval marker counts as approved for every train (the grandfather rule below), so it would reach every box untested. The old `mark_latest` dispatch input is gone.
- `promote.yml` runs when either issue is closed as **completed**. It reads the TrueNAS version from the release notes header (`for TrueNAS SCALE <version>`), derives its train, and appends `<!-- verified-train: <train> -->` to the release notes, once.
  - A stable build is also promoted as before: it becomes a full release, takes **Latest** only if it ranks highest (newest target kernel first, the existing `cmpRank`), and gets its changelog. Marker, promotion and changelog go in one release update.
  - A preview build gets the marker only: it stays a pre-release and is never promoted.
  - Closing as **not planned** changes nothing.
- `get.sh`, `install.sh` and `uninstall.sh` select, among the releases built for the running kernel, the newest one whose notes carry the box's train marker, or that is a full release with no marker at all (**grandfathered**: promoted before per-train sign-off). GitHub's Latest flag is cosmetic for them: they never select by it.
- Preview builds that were signed off before per-train approval (2026-09-19) are pre-releases, so the grandfather rule does not cover them; they get a one-time `verified-train: 26` marker, added to their release notes by hand.

## Kernel-keyed builds

A sysext's kernel modules bind to the exact kernel string (vermagic must
equal `uname -r`), and TrueNAS point releases usually reuse the previous
release's kernel. The pipeline is keyed accordingly:

- check-releases.yml resolves a new stable version's kernel from its
  rootfs.mtree manifest. If a promoted release for that kernel (with the
  current driver) already exists and is approved for the new version's
  train (the installer's rule: its train marker, or no marker at all), no
  build is dispatched;
  tracked-versions.json still updates and the installer serves the new
  version by kernel match. If the only coverage is an unpromoted build
  awaiting hardware test, no duplicate build is dispatched either, but the
  tracked version holds until that build is promoted (so the kernel keeps a
  rebuild path if the build is deleted). Preview (BETA/RC) builds never
  count as coverage.
- Transition guard: coverage only counts while the current **Latest**
  release is kernel-tagged (`k...`). The one line installer runs the
  `install.sh` attached to Latest, and only k-tag builds ship the
  kernel-matching installer; a `v<version>` Latest still matches exact
  TrueNAS versions, so skipping the build would leave the new version with
  no installable release. While Latest is a v-tag, or when the Latest
  lookup fails, every new version builds. The first k-tag build promoted
  to Latest ends the transition.
- A new kernel, a driver bump, or an unresolvable kernel always builds.
- install.sh selects releases by matching `uname -r` against the release's
  `Target kernel` row, falling back to the short kernel encoded in a k-tag
  when a body lost its row (the same rule check-releases' coverage gate
  uses), then verifies the downloaded image's own `usr/lib/modules/<kernel>`
  directory before installing. The `coral.kver`
  asset carries the same kernel string in machine-readable form for
  external tooling; install.sh does not read it (the notes row is the one
  key every release has, since older immutable releases predate the asset).
- New releases are tagged `k<kernel>-gasket<driver>-r<run>` (short kernel,
  e.g. `k6.12.91`). Releases published before the migration keep their
  `v<version>` tags; both install the same way.
- Hardware-test promotion is per build, which now means per kernel: one
  verification covers every TrueNAS version of the build's train sharing
  that kernel. A build approved for one train only never counts as
  coverage for another train's version; that version gets its own build
  and its own hardware test.

## Custom Builds

If you need a build for a TrueNAS version that doesn't have a pre-built release, you can build your own using GitHub Actions, no local build environment needed.

### Fork and Build

1. **Fork** this repository on GitHub
2. Go to **Actions** > **Build Coral Sysext** > **Run workflow**
3. Fill in the parameters:
   - **TrueNAS version**, e.g., `25.10.3.1` (must match an existing TrueNAS ISO on the download server)
   - **Gasket driver version**, e.g., `1.0-18` (used in the release tag and for tracking)
   - **Gasket ref**, e.g., `1.0-18.4` (git ref/tag to check out in `feranick/gasket-driver`)
   - **Train name**, e.g., `Goldeye` (must match the train iXsystems publishes the ISO under at `download.truenas.com/TrueNAS-SCALE-<train>/<version>/`). The current tracked train lives in [`.github/tracked-versions.json`](../.github/tracked-versions.json).
4. The workflow builds `coral.raw` and creates a GitHub release in your fork (~10-20 min, ~5 min cached). Like every build, it is a pre-release with a hardware-test issue.
5. Install it pinned to its tag: `curl -fsSL https://raw.githubusercontent.com/truenas-community-sysexts/coral-pcie-support/main/get.sh | sudo bash -s -- --repo=YOU/coral-pcie-support --release=<tag>`. Or close its hardware-test issue in your fork as completed (with Actions enabled there, `promote.yml` approves it), after which `get.sh --repo=YOU/coral-pcie-support` selects it like any approved build.

### When to Build Custom

- **New TrueNAS release** not yet covered by a pre-built release (the daily check workflow usually catches these within 24 hours of the ISO going live)
- **Different gasket ref** (e.g., a specific `feranick/gasket-driver` tag or a different fork entirely)
- **Modified build** (you've forked the repo to change build options, add patches, etc.)

### Version Defaults

The `workflow_dispatch` inputs default to blank. When left blank, the build's `resolve` job reads `.github/tracked-versions.json` at runtime and uses the latest tracked combination (plus auto-resolving the runner from TrueNAS's Debian release). A manual "Run workflow" therefore always targets the latest known-good combo without any extra sync step. You can override any field at dispatch time if you want a different target.
