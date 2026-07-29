# Required files only

This pack intentionally excludes reverse-engineering scripts, capture tools,
hybrid paint loops, legacy `nv-midi-connect` loops, and other test utilities.

## Runtime

| Path | Required for |
|------|----------------|
| `bin/start-virtualdj.sh` | Launch + cleanup |
| `bin/vdj-set-nv-audio.py` | Point VDJ at NV Audio PCM when present |
| `tools2/nv_screens.py` | LCD host, facade MIDI, live paint, wake/blank |
| `src2/alsa_patchbay.py` | Virtual MIDI facade + Control bridge |
| `src2/usb_midi_bulk.py` | libusb bulk paint |
| `src2/usb_midi_decode.py` | Product helpers |
| `src2/csv_log.py` | Imported by host (logging optional) |
| `tools/wire_hybrid.sh` | Wine ↔ facade aconnect |
| `tools/graphics_guard.sh` | Keep Wine off kernel LCD MIDI ports |
| `tools/apply-nv-spoof.sh` | Wine `Audio=alsa` + audio XML |
| `tools/clear-vdj-midi-clutter.sh` | Remove bad custom MIDI mappers |
| `tools/rebind-nv-audio-pcm.sh` | Optional: restore PCM if card drops |
| `tools/install-winealsa-nv.sh` | Optional: system-wide winealsa install |
| `wine-patch/x86_64-unix/winealsa.so` | MIDI VID/PID + skip kernel `MIDI 1` |
| `wine-patch/winealsa.drv/*` | Sources to rebuild on other Wine/distros |
| `captures/extracted-v2/bulk-out.bin` | Open/splash wake only (not a paint reel) |
| `vdj-devices/Numark_NV_Audio.xml` | Optional AUDIO-tab helper |
| `udev/99-numark-nv.rules` | USB permissions |

## Docs / install

| Path | Purpose |
|------|---------|
| `install.sh` | Installer |
| `README.md` / `INSTALL.md` | Overview + install |
| `docs/*` | Why, architecture, Wine/system, troubleshooting |

## Not shipped (on purpose)

- Capture/replay tools, probes, hybrid paint loops  
- `nv-midi-connect` autostart loops  
- WinBoat notes dumps, long captures, CSV traffic dumps  
- Snapshot trees, `__pycache__`, `.orig` backups  
- Desktop icons that rewire MIDI every 30s  
