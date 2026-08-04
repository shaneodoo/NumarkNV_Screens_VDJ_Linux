# Changelog

## 1.1.0 — 2026-08-04

### Highlights
- Professional layout: `nv_screens/` package, `bin/`, `scripts/`, `config/`, `data/wake/`
- Live dual-LCD paint under Wine VirtualDJ (libusb bulk + facade MIDI)
- Browser list scroll improvements (left/right), deck waveforms protected after LOAD
- **Mouse → library LCD**: software browser focus opens Library View (definition only paints after SEL; host injects net-zero browse pulse)
- Clean startup when NV devices already present (skip forced re-enum)
- Safer shutdown (no SEGV on CSV/patchbay teardown; stock logos via USB re-enum)

### Structure
| Path | Role |
|------|------|
| `bin/nv-screens` | LCD host |
| `bin/start-virtualdj.sh` | One-shot launcher |
| `nv_screens/` | Python library |
| `scripts/` | Wire, USB reset, spoof helpers |
| `config/` | udev + VDJ device XML |
| `data/wake/` | Wake/close bulk payloads only |
| `wine-patch/` | winealsa VID/PID patch |

Private captures, snapshots, and RE dumps are **not** shipped.

## 1.0.0
- Initial production pack (dual LCD + Controllers under Wine)
