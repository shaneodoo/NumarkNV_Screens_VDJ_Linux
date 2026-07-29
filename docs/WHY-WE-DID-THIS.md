# Why this exists

## Goal

Use a **Numark NV** with **VirtualDJ on Linux (Wine)** the way Windows does:

- Pads / jogs / LEDs  
- **Both LCDs** with live VDJ UI  
- Prefer **NV Audio** (4ch) when the ALSA card is available  

Numark does not ship a Linux LCD stack. The paint protocol is undocumented.

## What Windows does (measured)

Three USB IDs:

| ID | Role |
|----|------|
| `15e4:1005` | Control → **Numark NV** (MIDI) |
| `15e4:1033` | Audio → MIDI paints **Display Left**; PCM is 4ch sound |
| `15e4:2033` | Graphics → MIDI paints **Display Right** |

VDJ binds displays mainly by **USB VID/PID** on the MIDI device, then runs factory `imagesysex` paint from encrypted `controllers.dat`. User mapping XML **cannot** invent LCD paint.

LCD data is **USB-MIDI bulk** cells on EP `0x03` (`F0 47 …`), not a separate video class. **`amidi` reassembly does not paint** the panels; only exact USB-MIDI framing via **libusb bulk** does.

## What breaks on stock Linux + Wine

1. Kernel port names are `… MIDI 1`, not Windows `NV Graphics` / `NV Audio`.  
2. Stock **winealsa** reports fake MIDI IDs (`wMid=0xFF`, `wPid=1`) — no PID/VID identify → displays fall to general midi / empty custom maps → **no factory paint**.  
3. Even when SysEx appears on ALSA, firmware ignores it without bulk cell framing.  
4. Claiming Audio MIDI for the left LCD can drop the **PCM** ALSA card (sound).

## What we ship (required stack only)

1. **`nv-screens`** — claims Graphics + Audio MIDI bulk, virtual ALSA facade (`NV Control` / `NV Display Left` / `NV Display Right`), open-only wake, live VDJ SysEx → libusb, blank on quit.  
2. **Patched `winealsa.so`** — skip junk/`MIDI 1`, set Numark VID/PID on facade names; normally loaded via **bwrap** without replacing the system file.  
3. **Wire + guard** — 1:1 Wine↔facade; keep Wine off kernel LCD MIDI ports.  
4. **udev** — user access to VID `15e4`.  
5. **Short wake corpus** (`bulk-out.bin`) — open/splash only, not a track replay.

No capture reels, no probe tools, no 30s MIDI rewire autostart.
