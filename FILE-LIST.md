# Public tree (v1.1.0)

Runtime only — no capture dumps, snapshots, or RE probes.

| Path | Purpose |
|------|---------|
| `bin/nv-screens` | LCD host |
| `bin/start-virtualdj.sh` | Launcher |
| `bin/vdj-set-nv-audio.py` | Point VDJ at NV Audio PCM |
| `nv_screens/` | Python package |
| `scripts/` | wire, usb-reset, spoof, graphics guard |
| `tools/usb-reset-nv.sh` | Compat wrapper for old sudoers |
| `config/udev/` | USB permissions |
| `config/vdj-devices/` | Optional VDJ device XML |
| `data/wake/` | Wake / empty / close bulk only |
| `wine-patch/` | winealsa NV identity patch |
| `docs/` | Public docs |
| `install.sh` | Installer |
| `VERSION` / `CHANGELOG.md` | Release metadata |
