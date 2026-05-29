# Troubleshooting

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

3. Find the release whose tag matches your TrueNAS version
   (`v<truenas>-gasket<driver>-r<run>`). The release notes record the kernel
   version it was built against.

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
