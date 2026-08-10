# Changelog

## 1.3.0 — 2026-08-10

Cleanup release: centralized USB IDs, killed a disk-filling log bug, and stopped the Wine sandbox from seeing your whole filesystem.

### Added
- **`config/nv-ids.env`** — one source of truth for the NV's USB VID/PID (`15e4` / Control `1005` / Audio `1033` / Graphics `2033`). Was duplicated across 9+ files before this.
- **`nv_screens/ids.py`** — Python loader for the above.
- **`tools/detect-nv.sh`** — lists connected `15e4:*` interfaces, flags anything not in `nv-ids.env`. Read-only, never writes back.
- **`NV_LIVE_BRIDGE_LOG`** — opt-in raw MIDI/bulk capture, off by default (see Fixed).
- **`NV_BWRAP_FULL_HOST`** — escape hatch back to the old unrestricted bwrap bind if the new list is missing something.

### Fixed
- **Log rotation wasn't actually rotating.** `trim_log()` wrote a trimmed copy to a new file and `mv`'d it over the original — but `nv-screens`' stdout and the CSV logger hold that file open for the whole gig. `mv` swaps in a new inode; the running process kept writing into the old, unlinked one. Disk usage never stopped climbing despite trimming running every 2 minutes, and the on-disk file went stale after the first trim (`tail -f` and the crash diagnostic both broke). Now truncates in place instead of swapping files.
- **`live-bridge.txt` had no size cap** and wrote on nearly every MIDI frame, to a path different from the one actually being trimmed. Normal installs silently failed the write; a dev checkout with `captures/` present would grow it forever. Opt-in now, path fixed, self-caps regardless of the shell trimmer.
- LED-toggle dict kept one empty entry per MIDI note/CC ever touched in a session, forever. Bounded by keyspace so never serious, but pruned now.

### Changed
- **bwrap no longer binds the whole host.** `run_wine()` used `--dev-bind / /`, exposing every mounted drive to Wine unconditionally. Now binds only what Wine/Vulkan/ALSA/USB actually need, plus whatever's configured in `winecfg`'s Drives tab — read straight from `$WINEPREFIX/dosdevices/*`, so it stays in sync on its own.
- `config/nv-ids.env` comment rewritten to stop overpromising — it only covers USB identity, not the screen protocol. Notes how to point it at another Numark via `lsusb`; no guarantee it'll paint anything.

### Upgrade
```bash
git pull
./install.sh
```

If VDJ stops seeing a drive after upgrading, check it's actually mapped in `winecfg`'s Drives tab — the sandbox only sees what's there now.

---

## 1.2.0 — 2026-08-06

Full Linux VDJ stack: Numark NV screens **plus** portable DXVK for video.

### Added
- **`wine-stack/dxvk/`** — prebuilt x64/x32 DXVK with Linux **shared texture** support so 64-bit VirtualDJ can show deck video / karaoke under Wine (stock Wine/DXVK often cannot).
- **`scripts/install-dxvk.sh`** — installs DLLs + native overrides into any `WINEPREFIX` (not machine-specific).
- **`install.sh`** step for DXVK (skip with `NV_INSTALL_DXVK=0`).
- Patch source: `wine-stack/dxvk/patches/dxvk-linux-shared-res.patch` for rebuilds.

### Notes
- Needs a working **Vulkan** driver on the host.
- NV hardware is optional if you only want VDJ video under Wine.
- Still community glue — not official Atomix support.

### Upgrade
```bash
git pull
./install.sh
```

---

## 1.1.2 — 2026-08-05

End-user install polish: multi-user safe launcher + reliable desktop icon.

### Fixed
- **Permission denied on launch (shared `/tmp` logs)** — `start-virtualdj.sh` wrote `/tmp/nv-*.log` mode 644 owned by the first user; a second account hit `Permission denied` at the first log line. Logs now live under `~/.local/state/nv-screens/` (per user).
- **App menu / desktop icon pointing at the wrong tree** — installer always installs a thin wrapper with **absolute** `ROOT` and a `.desktop` with absolute `Exec=`, `TryExec=`, and `Path=`.
- **Shane-specific media mount** — removed hardcoded `/mnt/shane1`; optional `NV_DJ_MOUNT` if you want a D: drive.
- **winealsa bind path** — probes common distro paths instead of only Fedora `/usr/lib64/wine-wow64/...`.

### Installer
- Always bakes absolute paths (no “only when DEST ≠ default” sed).
- Clearer PATH warning when `~/bin` is not on `$PATH`.
- `NV_INSTALL_YES=1` for non-interactive install; `NV_INSTALL_ROOT` / `NV_BIN_DIR` still supported.
- Logs path printed at end of install.

### Upgrade
```bash
git pull
./install.sh
# then re-test as any user: ~/bin/start-virtualdj.sh
```

---

## 1.1.1 — 2026-08-04

Patch release: Left LCD browser list stability.

### Fixed
- **Left LCD browser twitch / double-row highlight** — selection “blip” between the grey highlighted track and the row below. Caused by guessing reverse scroll on highlight-only strip updates (Right was usually fine because it gets cleaner full 0..6 frames).
- **MIDI browse inject spam** — false-positive LED blink detection was injecting net-zero browse CCs many times per second (`+1` then `-1`), twitching the list selection on both software and LCD. Inject is **off by default**; set `NV_MOUSE_LIBRARY_INJECT=1` only if you want experimental mouse→library open.
- Browser assembler: confident strip-0 scroll only; mid-list highlight updates that strip without rebuilding a bad full frame.

### Upgrade
```bash
git pull
# restart host / start-virtualdj.sh
```

---

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
- Optional mouse → library open (see 1.1.1: off by default via `NV_MOUSE_LIBRARY_INJECT`) 
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

Full USB captures, session snapshots, reference dumps, and experimental probe scripts stay out of the public repo.

---

## 1.0.0 — 2026-07-29

First **public** release.

- Factory Controllers: Numark NV + Display Left + Display Right under Wine 
- Live dual LCD paint from VDJ (libusb bulk + facade MIDI) 
- Open-only / empty-deck wake; one launcher (`start-virtualdj.sh`) 
- Simple `./install.sh` for other Linux machines
