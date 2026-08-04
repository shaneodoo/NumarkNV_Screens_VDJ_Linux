# Where VirtualDJ keeps controller mappings

## Built-in (all major controllers including Numark NV)

| Location | What |
|----------|------|
| `…/VirtualDJ/Devices/controllers.dat` | **Encrypted** pack of factory MIDI/HID definitions (buttons, LEDs, **imagesysex** LCDs, audio wizard). Not human XML. |
| `virtualdj.exe` | Runtime + assets (`Numark NV Display Left.png`, `get_numark_waveform`, `CMIDIOutputSysexImage`, …) |
| Live update | `https://live.virtualdj.com/live/update.php` may refresh `controllers.dat` |

On Windows, **Numark NV** is one definition that covers Control + Graphics displays + optional NV audio button. That whole package is inside `controllers.dat`, not the empty “custom mapping” you see on Display Left/Right under Wine.

## User-editable (VDJPedia)

| Path | Role |
|------|------|
| `Documents/VirtualDJ/Devices/*.xml` | Custom **definitions** (`<device>…</device>`) matched by `drivername` / `sysexid` / `vid`/`pid` |
| `Documents/VirtualDJ/Mappers/*.xml` | Custom **mappers** (`<mapper device="NAME">`) — note/CC → VDJScript only |

Docs: [ControllerDefinitionMIDI](https://virtualdj.com/wiki/ControllerDefinitionMIDI.html)

Note from binary: **“Custom definitions require a Pro license”**.

## What we added for Wine Display ports

Windows-style names (what factory defs usually match):

- `drivername="NV Display Left"`
- `drivername="NV Display Right"`

Under Wine, winealsa formats `"client - port"` unless that exceeds 32 chars, then
**port name only**. Our ALSA client is `nv-screens-facade` so Wine exposes
exactly `NV Display Left` / `NV Display Right`.

## Important: custom XML shadows factory

Do **not** leave custom `Devices/NMNV_*.xml` in the VDJ profile if you want
**factory default** mappers. Those files win over encrypted `controllers.dat`.

Backups: `~/src/nv-screens/vdj-custom-backup/`

Factory binding (intended):

| Wine MIDI name | Identity reply | Factory device |
|----------------|----------------|----------------|
| `NV Display Left` | Graphics `…020620…` | Numark NV Display Left |
| `NV Display Right` | Audio `…020610…` | Numark NV Display Right |
| `NV Control - …` | Control serial | Numark NV |

See `FOOL-FACTORY-NV.md`.

## How to test

1. Fully quit VirtualDJ.
2. Relaunch from desktop icon (so Devices/*.xml are re-read).
3. Controllers tab: Display Left/Right should show description **Numark NV Display Left/Right** (not blank custom).
4. Check `Log Report.txt` for definition errors / no longer “Identified by general midi”.
5. Watch bridge: `tail -f ~/src/nv-screens/captures/live-bridge.txt` for `sysex_forwarded` / large `F0 47`.

## Expectations

| Outcome | Meaning |
|---------|---------|
| Definition loads, still only short MIDI | `imagesysex` needs different attrs or is hard-tied to factory NMNV |
| Definition error in log | Fix XML / Pro license / attribute names |
| Large `F0 47` appears | Success — bridge/libusb path already proven |

Factory dual-LCD paint under Windows is almost certainly **only** in encrypted `controllers.dat`, not something the public mapper UI can recreate with empty “custom mapping”.
