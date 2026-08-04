# Hybrid daily driver (desktop icon)

## Your model (correct)

```
Desktop VirtualDJ icon
        │
        ▼
  start-virtualdj.sh
        │
        ├─1─ nv-screens starts FIRST
        │      • claims real NV Graphics (libusb bulk EP 0x03)
        │      • kernel ALSA “NV Graphics” disappears
        │      • virtual ALSA “NV Graphics” facade so VDJ still sees it
        │      • exposes nv-screens:vdj_in / inject_in
        │
        ├─2─ Wine VirtualDJ starts
        │      • sees NV Control + NV Audio only (for pads + sound)
        │      • must NOT talk ALSA to Graphics
        │
        ├─3─ wire_hybrid + graphics_guard
        │      Wine ⟷ Control
        │      Wine ⟷ Audio
        │      Wine outs ──► nv-screens:vdj_in
        │      Wine ─x─ Graphics (severed continuously)
        │
        └─4─ nv-screens bridge
               inbound MIDI → USB-MIDI cells → libusb → Graphics firmware
```

Firmware logo is **built-in** when nothing is painting — not a logo SysEx.

## Why Wine must stay off Graphics

If Wine also sends ALSA MIDI to Graphics while we send libusb bulk, the panel
gets a **dirty mixed stream** and ignores / glitches paint. One clean owner:
**nv-screens libusb only**.

## Start

Double-click **VirtualDJ** desktop icon → runs `~/bin/start-virtualdj.sh`.

## Logs

| File | What |
|------|------|
| `/tmp/nv-screens-live.log` | Painter / bridge |
| `/tmp/nv-midi-connect.log` | Wire + guard |

## Honest note (Wine)

Under Wine, VDJ often only emits **short** MIDI (CC/notes), not full Windows
`0509` paint tiles. The bridge still forwards **everything** as clean USB-MIDI
bulk cells. Hot `0509` capture paint keeps panels alive until a true live encoder
or a Wine path that emits real paint SysEx exists.
