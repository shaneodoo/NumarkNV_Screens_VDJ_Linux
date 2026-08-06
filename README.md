# Numark NV + VirtualDJ on Linux

Dual LCD screens and factory controllers for the Numark NV, running VirtualDJ under Wine.

| USB device   | ID         | Role              |
|--------------|------------|-------------------|
| NV Control   | `15e4:1005` | Pads, jogs, knobs |
| NV Audio     | `15e4:1033` | Left LCD + sound  |
| NV Graphics  | `15e4:2033` | Right LCD         |

## Install

```bash
git clone https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux.git
cd NumarkNV_Screens_VDJ_Linux
./install.sh
```

Full steps: **[INSTALL.md](INSTALL.md)**

## Run

```bash
start-virtualdj.sh
# or app menu: VirtualDJ (Numark NV)
```

That starts the LCD host, wires MIDI, and launches VirtualDJ. When you quit VDJ, the host stops and stock logos can return (if sudoers is set).

**Needs:** Numark NV plugged in, VirtualDJ installed under Wine, Python 3 + pyusb, alsa-utils. bubblewrap is optional (for the winealsa patch).

## Layout

```
bin/           nv-screens host, start-virtualdj.sh, audio helper
nv_screens/    Python package
scripts/       MIDI wire, USB reset, spoof helpers
config/        udev rules, optional VDJ device XML
data/wake/     wake / empty / close bulk blobs
wine-patch/    winealsa.so for NV USB identity
install.sh     installer
```

## Logs

```
~/.local/state/nv-screens/screens-live.log
~/.local/state/nv-screens/midi-connect.log
```

## License

See [LICENSE](LICENSE).
