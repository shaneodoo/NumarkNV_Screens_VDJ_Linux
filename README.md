# Numark NV + VirtualDJ on Linux

**v1.1.1** — Dual 4.3″ LCDs and factory Controllers under Wine VirtualDJ.

Linux already exposes the NV as class-compliant USB-MIDI and audio. This project
provides the missing **display paint path** (private SysEx → USB-MIDI bulk) so
both screens show waveforms, browser lists, FX chrome, and status — without
Windows.

| USB device | ID | Role |
|------------|-----|------|
| NV Control | `15e4:1005` | Pads, jogs, knobs (ALSA MIDI) |
| NV Audio | `15e4:1033` | Left LCD + PCM |
| NV Graphics | `15e4:2033` | Right LCD |

## Layout

```
bin/                 # User entry points
  nv-screens         # LCD host (live paint + wake/close)
  start-virtualdj.sh # One command: host + wire + Wine VDJ
  vdj-set-nv-audio.py
nv_screens/          # Python package (patchbay, bulk painter, …)
scripts/             # wire_hybrid, usb-reset, wine spoof helpers
config/              # udev rules, optional VDJ device XML
data/wake/           # Wake / empty-deck / close bulk blobs only
wine-patch/          # winealsa.so with NV VID/PID identity
docs/                # Architecture & protocol notes
install.sh           # Optional installer
```

## Quick start

```bash
# From this repo (or after ./install.sh)
~/bin/start-virtualdj.sh          # or: ./bin/start-virtualdj.sh
```

That starts the LCD host, wires Wine ↔ facade MIDI, and launches VirtualDJ.
On exit, bulk is released and a USB re-enum restores stock NV logos.

**Needs:** Numark NV plugged in, VirtualDJ installed under Wine, Python 3 +
`pyusb`, ALSA, optional `bwrap` for the winealsa patch.

```bash
# LCD host only (advanced)
python3 bin/nv-screens --patchbay --live-only --wake-mode open --no-wait
```

## Install

**→ Step-by-step:** **[INSTALL.md](INSTALL.md)** (easy install guide)

```bash
git clone https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux.git
cd NumarkNV_Screens_VDJ_Linux
./install.sh
start-virtualdj.sh
```

`install.sh` copies into `~/src/nv-screens` by default and links `~/bin/start-virtualdj.sh`.

## What’s new

**1.1.1** — Left LCD browser highlight/twitch fix; browse inject off by default.  
**1.1.0** — Clean package layout, dual LCD live paint, Controllers under Wine.

See [CHANGELOG.md](CHANGELOG.md).

## Docs

| Doc | Topic |
|-----|--------|
| [docs/SYSTEM-PICTURE.md](docs/SYSTEM-PICTURE.md) | How the stack fits together |
| [docs/HYBRID-DAILY.md](docs/HYBRID-DAILY.md) | Day-to-day use |
| [docs/ARCHITECTURE-HYBRID.md](docs/ARCHITECTURE-HYBRID.md) | Hybrid host design |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | SysEx / bulk notes |
| [docs/HARDWARE.md](docs/HARDWARE.md) | USB products |

## License

See [LICENSE](LICENSE). Protocol reverse-engineering is for interoperability on
your own hardware; not affiliated with Numark, inMusic, or Atomix/VirtualDJ.

## Privacy of this tree

This repository ships **runtime code and small wake blobs only**. Full USB
captures, session snapshots, and experimental probes stay in a private local
archive and are not published.
