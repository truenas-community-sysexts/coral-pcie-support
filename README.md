# Google Coral PCIe TPU Sysext for TrueNAS

A systemd-sysext package that adds [Google Coral](https://coral.ai/) PCIe TPU support to TrueNAS. Primarily useful for running [Frigate NVR](https://frigate.video/) with hardware-accelerated AI object detection.

## Documentation

| Doc | Contents |
| --- | --- |
| [Quick Start](#quick-start) | Install, verify, uninstall |
| [docs/install.md](docs/install.md) | Install options, persistence, scripts reference |
| [docs/build.md](docs/build.md) | Build process, custom builds, automated updates |
| [docs/architecture.md](docs/architecture.md) | Deep technical reference: sysext structure, build pipeline, read-only constraints |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Kernel mismatch recovery after TrueNAS updates |

## What's Included

The `coral.raw` sysext contains:

| Component | Description |
| --- | --- |
| `gasket.ko` | Gasket PCIe kernel module |
| `apex.ko` | Apex driver for Coral TPU |
| `coral-load.service` | Systemd service for automatic module loading |
| `51-coral-udev.rules` | Udev rules for `/dev/apex*` permissions |

No firmware is needed. The Coral PCIe TPU works with just the kernel modules.

## Compatibility

| Device | Supported | Notes |
| --- | --- | --- |
| Coral M.2 Accelerator | Yes | PCIe, primary target |
| Coral M.2 Accelerator with Dual Edge TPU | Yes | PCIe, creates /dev/apex_0 and /dev/apex_1 |
| Coral Mini PCIe Accelerator | Yes | PCIe |
| Coral USB Accelerator | No | Uses libusb, no kernel module needed |

## Quick Start

### Prerequisites

- TrueNAS 25.10 or newer (the current target train and version are recorded in [`.github/tracked-versions.json`](.github/tracked-versions.json) and tracked automatically)
- Coral PCIe TPU installed and visible (`lspci | grep 089a`)
- Root/sudo access
- Internet access (to download the release)

### Install

Auto-detects your TrueNAS version, downloads the matching release, and sets up persistence:

```bash
curl -fsSL https://github.com/truenas-community-sysexts/coral-pcie-support/releases/latest/download/install.sh | sudo bash
```

With an explicit pool for persistence:

```bash
curl -fsSL https://github.com/truenas-community-sysexts/coral-pcie-support/releases/latest/download/install.sh -o install.sh
sudo bash install.sh --pool=fast
```

> **Version matching:** Each release is built for a specific TrueNAS kernel. The install script
> auto-detects your version and downloads the correct release.

### Verify

Run the built-in status probe:

```bash
curl -fsSL https://github.com/truenas-community-sysexts/coral-pcie-support/releases/latest/download/install.sh | sudo bash -s -- --check
```

Or check manually:

```bash
ls /dev/apex*                           # Device detected
lsmod | grep -E 'gasket|apex'          # Modules loaded
```

### Uninstall

```bash
curl -fsSL https://github.com/truenas-community-sysexts/coral-pcie-support/releases/latest/download/uninstall.sh | sudo bash
```

## Using with Frigate

### 1. Pass Through the Device

In TrueNAS Apps, edit your Frigate app and add the device mapping:

```text
/dev/apex_0:/dev/apex_0
```

For dual-edge TPU cards, also pass through `/dev/apex_1`.

### 2. Configure Frigate Detectors

In your Frigate `config.yaml`:

```yaml
detectors:
  coral:
    type: edgetpu
    device: pci
```

If you have a coral dual or multiple coral singles in your system then in your Frigate `config.yaml`:

 ```yaml
 coral1:
    type: edgetpu
    device: pci:0
  coral2:
    type: edgetpu
    device: pci:1
```

## Important Notes

- The kernel module must match the exact TrueNAS kernel version. If you update TrueNAS, you need a matching sysext build. See [troubleshooting](docs/troubleshooting.md) for recovery steps.
- The unsigned kernel module may require disabling Secure Boot.
- No firmware download is needed, unlike some other accelerator sysexts. The Coral PCIe TPU operates with just the gasket and apex kernel modules.

## License

**MIT** ([LICENSE](LICENSE)) for all code in this repository (scripts, workflows, systemd units, udev rules).

The compiled kernel modules (gasket.ko, apex.ko) are GPL-2.0 as build artifacts derived from [feranick/gasket-driver](https://github.com/feranick/gasket-driver).

## Credits

- [truenas-community-sysexts/hailo8-support](https://github.com/truenas-community-sysexts/hailo8-support) - project structure, scripts, and CI workflows adapted from scyto's Hailo-8 sysext
- [feranick/gasket-driver](https://github.com/feranick/gasket-driver) - actively maintained gasket-driver fork with kernel compatibility fixes (build source)
- [google/gasket-driver](https://github.com/google/gasket-driver) - original kernel module source (archived)
- [cbetti/truenas-coral-pcie-driver-helper](https://github.com/cbetti/truenas-coral-pcie-driver-helper) - reference implementation
