# Architecture (production path)

```
Numark NV USB
  Control 1005 ── ALSA MIDI ──► facade Control ◄──► Wine (pads/jogs)
  Audio   1033 ── MIDI bulk ──► libusb ── left LCD
           └── PCM 4ch ──────► Wine alsa (when card present)
  Graphics 2033 ─ MIDI bulk ──► libusb ── right LCD

Wine VDJ
  MIDI outs ──1:1──► facade Display Left / Right / Control
  SysEx ──► nv-screens ──► USB-MIDI cells ──► correct product EP
```

## Launch (`start-virtualdj.sh`)

1. Optional bwrap + patched winealsa  
2. Start `nv_screens.py --live-only --wake-mode open`  
3. Wire + guard  
4. `wine virtualdj.exe`  
5. On exit: splash blank, tear down facade  

## Wake

Open only: CC + `0506` / `0508` / `0530` per product (~12 actions).  
No capture track UI. Live titles come from VDJ after you load tracks.

## Shutdown

VDJ process ends → blank splash → nv-screens exits → launcher SIGTERM if needed → USB interfaces released.
