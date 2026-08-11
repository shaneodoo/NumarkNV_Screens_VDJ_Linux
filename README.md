# VirtualDJ on Linux — Numark NV + video

Not an official Atomix product. Community glue that runs on a normal Linux box.

## Why this exists

I run VirtualDJ on Linux under Wine. The **Numark NV** is a great dual-screen
controller on Windows, but on Linux the two LCD decks never woke up properly —
the pads and jogs could work, the audio could work, and the screens stayed
stuck on logos or garbage. VirtualDJ’s own video path under Wine was also a
pain without a working DXVK setup.

So this project is the missing middle layer: a small host that claims the NV’s
screen USB interfaces, wakes the panels, and paints whatever VirtualDJ is
sending (browser, waveforms, titles) onto the real LCDs, while keeping the
Control surface and sound on the normal Linux/ALSA path. One launcher starts
the host, wires MIDI, and opens VirtualDJ. Optional DXVK is included so deck
video and karaoke can show up under Wine as well.

**Who it’s for:** Linux DJs who already use (or want to use) VirtualDJ with a
Numark NV and don’t want to keep a Windows box just for the screens. If you
only care about video under Wine, the DXVK bits help even without the hardware.
If you don’t have an NV, this won’t invent one — it only bridges what the deck
and VirtualDJ already do.

Everything below is the practical stuff: install, run, layout, requirements.

| USB device   | ID          | Role              |
|--------------|-------------|-------------------|
| NV Control   | `15e4:1005` | Pads, jogs, knobs |
| NV Audio     | `15e4:1033` | Left LCD + sound  |
| NV Graphics  | `15e4:2033` | Right LCD         |

## One install

```bash
git clone https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux.git
cd NumarkNV_Screens_VDJ_Linux
./install.sh
```

That will:

1. Install the NV LCD host + launcher  
2. Put **start-virtualdj.sh** in `~/bin` and an app menu entry  
3. Install **DXVK** into your Wine prefix (video under Wine)  
4. Offer USB udev rules  

You still need **Wine** and **VirtualDJ** installed in the prefix first (see [INSTALL.md](INSTALL.md)).

```bash
# NV screens only (skip video DLLs)
NV_INSTALL_DXVK=0 ./install.sh

# Custom paths
NV_INSTALL_ROOT=~/apps/nv-screens WINEPREFIX=~/.wine-vdj ./install.sh
```

## Run

```bash
start-virtualdj.sh
# or: VirtualDJ (Numark NV) in the app menu
```

## What is in the box

| Piece | Purpose |
|-------|---------|
| `bin/nv-screens` + `nv_screens/` | Dual LCD paint host |
| `bin/start-virtualdj.sh` | One-command session |
| `wine-stack/dxvk/` | Prebuilt DXVK with Linux shared textures (VDJ video) |
| `scripts/install-dxvk.sh` | Install DXVK into any `WINEPREFIX` |
| `wine-patch/.../winealsa.so` | Optional MIDI/USB identity for NV under Wine |
| `config/udev/` | USB permissions for bulk LCD |
| `data/wake/` | Wake / empty / close bulk blobs |

## Needs

- Linux + Wine  
- VirtualDJ (desktop installer under Wine)  
- Python 3 + pyusb, alsa-utils  
- **Vulkan** GPU drivers (for VDJ video via DXVK)  
- Numark NV if you want hardware screens (video stack works without the NV)

## Logs

Kept short for long gigs (default max ~1 MiB per file, trimmed while running).
CSV traffic dump is **off** unless `NV_CSV_LOG=1`.

```
~/.local/state/nv-screens/screens-live.log
~/.local/state/nv-screens/midi-connect.log
```

## License

Project glue: see [LICENSE](LICENSE).  
DXVK binaries: zlib license (upstream DXVK); see `wine-stack/dxvk/README.md`.
