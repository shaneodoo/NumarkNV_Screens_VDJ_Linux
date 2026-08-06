# VirtualDJ on Linux — Numark NV + video

Dual LCD screens and factory-style controllers for the **Numark NV**, plus a
**DXVK** stack so 64-bit VirtualDJ can show **deck video / karaoke** under Wine.

Not an official Atomix product. Community glue that runs on a normal Linux box.

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
