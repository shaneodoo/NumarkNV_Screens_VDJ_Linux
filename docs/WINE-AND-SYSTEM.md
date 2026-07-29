# Wine / system files vs userspace

## Short answer

| Change | Permanent system edit? | Required? |
|--------|------------------------|-----------|
| Python `nv-screens` + shell tools | No — install under `~/src/nv-screens` | **Yes** |
| Patched `winealsa.so` | **No** by default (`bwrap` bind-mount at launch) | **Yes** (for factory Display bind) |
| Optional copy of `winealsa.so` over system Wine | Yes (with backup) | Only if no bubblewrap |
| `udev` rule for `15e4` | Yes, one rules file | Strongly recommended |
| Kernel / VirtualDJ.exe | Unchanged | — |

**Almost everything is userspace in this pack.** The only “core Wine” piece is **`winealsa.so`**, and the recommended path never overwrites the package file on disk.

## Patched winealsa (what / why)

Stock Wine MIDI:

- No real USB VID/PID on MIDI devices  
- Exposes kernel `… MIDI 1` ports  

Patch (`wine-patch/`):

- Skip PipeWire, Midi Through, `MIDI 1` ports  
- Apply Numark `wMid`/`wPid` for Control / Display Left / Display Right names  
- Audio path: use `/proc/asound/cardN/usbid` when publishing USB device IDs  

**Launch (default):**

```text
bwrap --bind $ROOT/wine-patch/x86_64-unix/winealsa.so \
      /usr/lib64/wine-wow64/wine/x86_64-unix/winealsa.so \
      … start-virtualdj …
```

Prebuilt `.so` targets **Wine 11 / Fedora wow64 layout**. Other distros: rebuild from `wine-patch/winealsa.drv/` against your Wine tree.

## Optional permanent install

```bash
./install.sh --system-winealsa
# or
tools/install-winealsa-nv.sh
```

Creates a timestamped backup of the original system `winealsa.so`.

## udev

`udev/99-numark-nv.rules` — MODE/`uaccess` for Numark USB so libusb and ALSA work without root.
