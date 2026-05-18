# Google Coral PCIe TPU Sysext for TrueNAS SCALE

A systemd-sysext package that adds [Google Coral](https://coral.ai/) PCIe TPU support to TrueNAS SCALE. Primarily useful for running [Frigate NVR](https://frigate.video/) with hardware-accelerated AI object detection.

## Documentation

| Doc | Contents |
| --- | --- |
| [Quick Start](#quick-start) | Install, verify, uninstall |
| [docs/architecture.md](docs/architecture.md) | Deep technical reference: sysext structure, build pipeline, read-only constraints |

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

- TrueNAS SCALE 25.10 or newer (the current target train and version are recorded in [`.github/tracked-versions.json`](.github/tracked-versions.json) and tracked automatically)
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

## Important Notes

- The kernel module must match the exact TrueNAS kernel version. If you update TrueNAS, you need a matching sysext build.
- The unsigned kernel module may require disabling Secure Boot.
- No firmware download is needed, unlike some other accelerator sysexts. The Coral PCIe TPU operates with just the gasket and apex kernel modules.

## License

GPL-2.0 - see [LICENSE](LICENSE).

The gasket-driver source ([google/gasket-driver](https://github.com/google/gasket-driver)) is licensed under GPL-2.0.

## Credits

- [google/gasket-driver](https://github.com/google/gasket-driver) - upstream kernel module source
- [feranick/gasket-driver](https://github.com/feranick/gasket-driver) - kernel compatibility patches reference
- [cbetti/truenas-coral-pcie-driver-helper](https://github.com/cbetti/truenas-coral-pcie-driver-helper) - reference implementation

## About This Project

This project was developed with the assistance of AI (Claude by Anthropic) via Claude Code. A human provided direction, reviewed outputs, and made decisions, but the implementation was AI-assisted.
