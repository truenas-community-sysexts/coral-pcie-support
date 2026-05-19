# TrueNAS Sysext Notes

Practical knowledge about building and shipping systemd-sysext packages on TrueNAS SCALE. Gathered from this project and from other community sysext projects.

## Boot-time unit activation

Sysext-shipped systemd units with `[Install] WantedBy=multi-user.target` are silently skipped at boot on TrueNAS. No journal entries, no errors. The reliable pattern is a `midclt initshutdownscript` entry with `type=COMMAND` and `when=PREINIT`, which runs a script that calls `systemctl start <unit>` explicitly.

## PREINIT vs POSTINIT

PREINIT runs after ZFS pools are mounted but before the middleware starts apps. POSTINIT runs after the middleware is up, by which time app containers may already be starting. For device drivers that apps depend on, PREINIT is the only safe option.

## Read-only filesystem constraints

| Path | Writable? | Notes |
|------|-----------|-------|
| `/usr` | No (ZFS readonly) | Can be temporarily unlocked via `zfs set readonly=off` |
| `/lib` | No (separate ZFS dataset) | Symlink to `/usr/lib` but on its own readonly dataset |
| `/lib/modules` | No | Part of the `/lib` dataset |
| `/lib/firmware` | No | Part of the `/lib` dataset |
| `/run/extensions` | Yes (tmpfs) | Where sysext symlinks go, cleared on reboot |
| `/mnt/<pool>` | Yes | ZFS data pools, persistent across updates |

Because of this:
- `depmod` cannot write to `/lib/modules`, so `modprobe` won't find out-of-tree modules. Use `insmod` with an absolute path instead.
- Install scripts that place files in `/usr` must temporarily unlock the ZFS dataset and re-lock it on exit (use a `trap` for safety).

## Sysext activation path

TrueNAS does not use the standard `systemd-sysext merge` path (`/var/lib/extensions/`). The working pattern is:

1. Place `<name>.raw` at `/usr/share/truenas/sysext-extensions/<name>.raw`
2. Symlink into `/run/extensions/<name>.raw`
3. `systemd-sysext refresh`
4. `ldconfig`

The `/run/extensions/` symlink is on tmpfs and disappears on every reboot, which is why the PREINIT script must recreate it.

## TrueNAS updates wipe /usr

Any sysext placed in `/usr/` is lost when TrueNAS updates (the rootfs is replaced). Persistence requires a backup on a ZFS data pool (`/mnt/<pool>/`) and a PREINIT script that restores it on boot.

## `Type=oneshot RemainAfterExit=yes` gotcha

`systemctl start` on a unit with `Type=oneshot` and `RemainAfterExit=yes` is a no-op once the unit is already active. If the unit needs to re-execute (e.g. after config changes), use `systemctl restart` instead.

## Live driver swap

Replacing a sysext that contains kernel modules at runtime leaves the previous driver's kernel modules in memory. The new modules only load after a reboot. Install scripts should warn the user when a reboot is required.
