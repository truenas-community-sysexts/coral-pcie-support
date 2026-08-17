# Troubleshooting

## Is the TPU detected at all?

Before debugging the driver, confirm the card is visible on the PCI bus:

```bash
lspci -nnk -d 1ac1:
```

A detected TPU prints something like:

```
01:00.0 System peripheral [0880]: Global Unichip Corp. Coral Edge TPU [1ac1:089a]
	Kernel driver in use: apex
	Kernel modules: apex
```

The `-nn` flag matters: without it, lspci prints only the device name from
the host's pci.ids database, so grepping for the numeric ID `089a` finds
nothing even when the TPU is present (issue #23). `-d 1ac1:` filters by the
Global Unichip vendor ID and works even when pci.ids does not know the
device name. `-k` shows whether the apex driver is bound.

- **No output at all**: the card is not on the PCI bus. Check seating and
  power; this is a hardware problem, not a driver problem.
- **Output but no "Kernel driver in use" line**: the card is detected but
  the driver did not bind. Check `dmesg | grep -iE 'gasket|apex'` and the
  sections below.

`install.sh --check` runs the same bus probe (via `/sys/bus/pci`) as its
first check.

## Kernel version mismatch after a TrueNAS update

After TrueNAS updates the underlying kernel, the boot-time PREINIT script
logs the following and `/dev/apex_0` will not initialize:

```
[coral-preinit] ERROR: Kernel version mismatch: running <new-kver> but sysext has modules for <old-kver>
[coral-preinit] ERROR: TrueNAS was likely updated. Download a new coral.raw release matching <new-kver>
[coral-preinit] ERROR: Visit https://github.com/<repo>/releases
```

This is **expected** behavior on a TrueNAS upgrade, not a bug. The gasket and
apex kernel modules are compiled against an exact kernel version, so the
previous sysext is no longer compatible.

### Recovery

1. Check the running kernel:

   ```bash
   uname -r
   ```

2. Visit the releases page printed in the error message.

3. Find the release whose tag matches your running kernel
   (`k<kernel>-gasket<driver>-r<run>`, e.g. `k6.12.91-...` for kernel
   `6.12.91-production+truenas`). Older releases use `v<truenas>-...` tags;
   either way the release notes record the exact kernel the build targets.

4. If a matching release exists, re-run the installer:

   ```bash
   curl -fsSL https://github.com/truenas-community-sysexts/coral-pcie-support/releases/latest/download/install.sh \
     | sudo bash
   ```

   The installer downloads the matching `coral.raw` and replaces the
   stale sysext on the persistent pool. The next boot succeeds.

5. If no matching release exists yet, the daily auto-build workflow
   picks up new TrueNAS versions within ~24 hours of the ISO being
   published at `download.truenas.com`. Wait for the build to land,
   then repeat step 4. If a build is overdue, open an issue.

### Why this can't be fixed automatically

The PREINIT script can detect the mismatch but cannot fix it on its own:
downloading a new `coral.raw` requires network access, and PREINIT runs
before the network stack is reliably up. Recovery is intentionally a
human step.
