# v1.1.0 — Clean layout + better browser / mouse library

Second public release. Keeps everything that worked in **v1.0.0** (factory Controllers + live dual LCD under Wine) and tightens the project for day-to-day use.

## What’s changed since v1.0.0

### Project structure
| Before (1.0) | After (1.1) |
|--------------|-------------|
| `tools2/nv_screens.py` | `bin/nv-screens` |
| `src2/*` | `nv_screens/` package |
| mixed `tools/` | `scripts/` (ops) + thin `tools/` compat wrappers |
| capture dumps in tree | **removed** from public pack |
| — | `config/`, `data/wake/` |

Private USB captures, snapshots, and RE probes are no longer published.

### LCD behaviour
- **Browser lists** scroll more cleanly on left and right (full 0..6 frames + careful strip-0 handling)
- After **LOAD**, waveforms stay on screen (browser tiles don’t wipe the deck)
- **Mouse → library LCD**: click the software **song** list and the LCD can open Library View  
  - Stock VDJ only paints the list after SEL/browse  
  - Host detects song/folders focus and injects a net-zero browse pulse so the list paints with your current selection  
  - Requires the updated mapping (restart VDJ or re-select **Numark NV - Custom Mapping**)

### Startup / shutdown
- Faster restart when NV devices are already present (skips unnecessary USB re-enum)
- Safer quit (no SEGV when closing logs/patchbay)
- Stock **NV logos** still restored on exit via USB re-enum

### Install / paths
```bash
git clone https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux.git
cd NumarkNV_Screens_VDJ_Linux
git checkout v1.1.0   # or stay on main
chmod +x install.sh && ./install.sh
start-virtualdj.sh
```

If you already had 1.0 installed, pull `main` and re-run `./install.sh`.  
Sudoers can keep pointing at `tools/usb-reset-nv.sh` (compat) or switch to `scripts/usb-reset-nv.sh`.

## From v1.0.0 (still included)
- Factory Controllers: Numark NV + Display Left + Display Right  
- Live dual LCD paint from VDJ  
- One launcher + `./install.sh`  

Full detail: [CHANGELOG.md](https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux/blob/main/CHANGELOG.md)
