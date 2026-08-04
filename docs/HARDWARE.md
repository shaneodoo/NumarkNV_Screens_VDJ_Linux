# Numark NV — hardware map (Linux)

Observed on Fedora with NV connected:

## USB

```
15e4:1005  Numark NV Control   (full-speed)
15e4:2033  Numark NV Graphics  (full-speed)  ← screens
15e4:1033  Numark NV Audio     (full-speed)
```

Parent is typically an onboard hub (NEC/etc.) under xHCI.

All three present as **USB Audio class** with **MIDI Streaming** interfaces
(not classic HID). Kernel driver: `snd-usb-audio`.

## ALSA cards (names, not numbers — numbers change)

| Card id    | Product      | MIDI device example   | Notes                |
|------------|--------------|------------------------|----------------------|
| `Control`  | NV Control   | `hw:Control,0`         | Buttons / jogs       |
| `Graphics` | NV Graphics  | `hw:Graphics,0`        | **Display SysEx**    |
| `Audio`    | NV Audio     | `hw:Audio,0` + PCM     | 4 ch @ 48 kHz S16    |

Resolve card number:

```bash
cat /proc/asound/cards
# or
python3 -c "import pathlib;print([p.read_text().strip() for p in pathlib.Path('/proc/asound').glob('card*/id')])"
```

## MIDI endpoints (Graphics)

From `lsusb -v` (typical):

- Bulk OUT 64 bytes (MIDI)  
- Bulk IN 64 bytes  

USB full-speed limits throughput; display updates are likely **compressed,
partial, or tiled** rather than full uncompressed RGB frames every vsync.

## Audio

NV Audio playback: **4 channels**, 48000 Hz, S16_LE  
Channel map often: FL FR RL RR → master L/R + phones L/R.

## VirtualDJ (Windows)

Binary references include:

- `CMIDIOutputSysexImage` / `imagesysex`  
- `get_numark_waveform`, `get_numark_beatgrid`, `get_numark_songpos`  
- Assets like `Numark NV Display Left.png`  

So display path is **SysEx image-oriented**, sent via `midiOutLongMsg` on
Windows, targeting the Graphics MIDI port.

## Wine under Linux (current)

- Control / Graphics / Audio appear as separate ALSA cards.  
- VDJ often sends **Control Change** (LEDs/meters) but not full image SysEx.  
- That is why LCDs stay on the boot **“NV”** logo under Wine.

This project aims to paint screens **without** relying on VDJ-on-Wine.
