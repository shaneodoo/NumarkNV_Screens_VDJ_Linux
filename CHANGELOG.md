# Changelog

## 1.1.0 — 2026-08-04

Second public release. Builds on **v1.0.0** (factory Controllers + live dual LCD under Wine).

### What’s new since 1.0.0

**Layout (breaking paths for packagers)**  
- Replaced `tools2/` + `src2/` sprawl with a clear tree:
  - `bin/` — `nv-screens`, `start-virtualdj.sh`, `vdj-set-nv-audio.py`
  - `nv_screens/` — Python package (patchbay, bulk paint, wake/close)
  - `scripts/` — wire, USB reset, Wine spoof, graphics guard
  - `config/` — udev rules + optional VDJ device XML
  - `data/wake/` — wake / empty-deck / close bulk only
- Public pack no longer ships captures, snapshots, or RE probes  
- Compat wrappers: `tools/usb-reset-nv.sh` still works for old sudoers lines

**LCD / browser**  
- Cleaner browser list scrolling on both LCDs (full 0..6 frames + careful strip-0 scroll)  
- After LOAD, waveforms stay protected; residual browser paint doesn’t blank the deck  
- **Mouse → library on the LCD**: focusing the software track list (song pane) can open Library View. Stock VDJ only paints the list after SEL/browse; the host detects song/folders focus and injects a net-zero browse pulse so the definition paints the current selection  
- Pane title / list chrome (`0521`–`0524`) prioritised in the live queue  

**Startup / shutdown**  
- Skip full USB re-enum on start when NV Audio/Graphics are already present (much faster relaunch)  
- Safer close: stop patchbay before CSV teardown (no SEGV on quit)  
- Stock logos still restored via authorized USB re-enum after exit  

**Docs**  
- Public docs only: system picture, hybrid daily use, protocol, Wine notes  
- `README.md` + `FILE-LIST.md` match the new tree  

### Upgrade notes

```bash
git fetch origin
git checkout main
git pull
# if you installed with install.sh:
./install.sh
```

Update sudoers if you want the canonical path (optional; old `tools/` wrapper still works):

```text
youruser ALL=(root) NOPASSWD: /path/to/NumarkNV_Screens_VDJ_Linux/scripts/usb-reset-nv.sh
```

Re-select **Numark NV - Custom Mapping** in VDJ (or restart VDJ) so the song/folders LED blink mapping for mouse→library is loaded.

### Not in this release (private / local only)

Full USB captures, session snapshots, WinBoat dumps, and experimental probe scripts stay out of the public repo.

---

## 1.0.0 — 2026-07-29

First **public** release.

- Factory Controllers: Numark NV + Display Left + Display Right under Wine  
- Live dual LCD paint from VDJ (libusb bulk + facade MIDI)  
- Open-only / empty-deck wake; one launcher (`start-virtualdj.sh`)  
- Simple `./install.sh` for other Linux machines  
