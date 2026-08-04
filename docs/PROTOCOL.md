# Protocol notes (living document)

Fill this in as captures are analyzed. **Nothing here is final until replay works.**

## Confirmed (measured on real hardware + USBPcap)

- **There is no third “secret” vendor bulk interface on NV Graphics.**  
  `lsusb -v` for `15e4:2033` shows only:
  - Audio Control (0 endpoints)
  - **MIDI Streaming**: bulk OUT `0x03` (64 B) + bulk IN `0x83` (64 B)  
  Screen data in Windows captures is **USB-MIDI event packets** on that bulk
  pipe (CIN 0x4/5/6/7), reassembled to SysEx `F0 47 … F7`.
- **NV Audio** (`15e4:1033`) also has MIDI bulk `0x03` **and** isochronous PCM
  (that is audio, not LCD). Capture shows large isoch OUT (e.g. 384/3456 B) =
  sound samples; display SysEx still rides MIDI bulk.
- SysEx uses manufacturer **`0x47`** (Akai/InMusic family), product IDs
  `10 33` / `20 33` matching USB PIDs.
- VirtualDJ binary contains `CMIDIOutputSysexImage` / display assets — private
  reverse-engineering, **not** open docs (Numark/Serato never published this).
- Under Wine, VDJ mostly emits **CC** on Control/Graphics, **not** the paint
  SysEx stream → LCDs stay on boot **“NV”** logo.
- **amidi SysEx replay** (init + continuous `05 05`/`05 09`) was accepted at
  the wire (Tx counters rise, 0 amidi errors) but **did not change LCDs**.
- **libusb raw bulk replay works (2026-07-22, user-confirmed):** replaying the
  exact bulk OUT payloads from USBPcap via `tools/replay_usb_bulk.py` produces
  **visible screen activity**. Prefer bulk URB replay over amidi for paint.

### Community claims vs our data

| Claim | Our measurement |
|-------|-----------------|
| “Hidden bulk endpoint bypasses MIDI” | **False for this device** — Graphics is class MIDI bulk only |
| “Standard MIDI only for pads” | **True** — Control `15e4:1005` is MIDI for knobs/pads |
| Mixxx can’t drive screens | **Still true** — protocol undocumented; no open painter yet |
| VDJ CreateMidiLog helps | **Useful for host-side log**; still prefer USBPcap for full USB cells |

### VDJ mapping vs display paint (important)

VirtualDJ has **two separate layers**:

| Layer | What it is | Screens? |
|-------|------------|----------|
| **Mapper XML** (`Mappers/Numark NV - Custom Mapping.xml`, device `NMNV`) | VDJScript only: buttons → actions, LEDs → queries | **No pixel paint** |
| **Built-in controller definition** (encrypted `Devices/controllers.dat` + code in `virtualdj.exe`) | MIDI note/CC layout + **SysEx image output** for dual LCDs | **Yes — this paints** |

Official setup docs: Config → Mapping shows **3 devices** — main **Numark NV** plus
**Left** and **Right LCD Displays**, each on factory default mapping.  
User scripts can change `LCD_PAGE` (page button); that does **not** draw waveforms.

So: editing/rewriting the mapping script **cannot** invent a Linux display driver.
A userspace painter must speak the same SysEx the built-in definition emits
(`CMIDIOutputSysexImage`).

Local files of interest:

- `…/VirtualDJ/Mappers/Numark NV - Custom Mapping.xml` — user/custom VDJScript  
- `…/VirtualDJ/Devices/controllers.dat` — encrypted definitions (no plaintext NMNV)  
- `…/VirtualDJ/settings.xml` — `NMNV-*` display prefs, `disableBuiltInDefinitions=no`

### Linux USB capture 2026-07-22 (`linux-vdj-usb-20260722-021045.pcapng`)

| Device | USB addr | OUT (host→dev) | IN (dev→host) | Notes |
|--------|----------|----------------|---------------|--------|
| Control | 5 | 610 | 1808 | Pads/jogs in; LED CCs out |
| Audio | 6 | ~18k | ~90k | Isochronous audio stream |
| Graphics | 7 | **610** | 76 | OUT is **only 4-byte USB-MIDI CC** |

**Graphics bulk OUT ep 0x03** dissects as:

```text
USB Midi Event Packet: Control Change
  Cable: 0
  Code Index: 0xB (Control Change)
  MIDI Event: e.g. b0 4b 01   (CC, not SysEx)
```

- Packet size always **4 bytes** (single short MIDI message per URB).  
- **No** SysEx CIN (0x4/0x5/0x6/0x7), no `F0` image payloads.  
- Kernel MIDI stats: Graphics **Tx ~998 bytes** over 45s ≈ LED-rate traffic only.  

**Conclusion:** With VDJ under Wine, the host **does** talk to Graphics, but only  
with **Control Change** (likely LEDs/meters fanned to that port). It is **not**  
sending LCD paint frames. Wireshark on Linux works; the paint protocol is absent.

## Unknown (to answer with captures)

- [ ] SysEx manufacturer ID / header bytes  
- [ ] Which port is left vs right deck (one port, multiplexed?)  
- [ ] Frame size / resolution (likely related to 4.3″ panel, e.g. 480×272-class)  
- [ ] Color format (RGB565, indexed palette, JPEG/RLE tile, etc.)  
- [ ] Full frame vs dirty rectangles  
- [ ] Refresh rate / pacing  
- [ ] Init / handshake sequence after plug-in  
- [ ] Whether Control MIDI is required for display init  

## Hypotheses

1. **Init**: short SysEx after VDJ opens the Graphics port, then continuous
   image SysEx.  
2. **Dual screen**: either two stream IDs in one SysEx stream, or alternating
   frames with a deck byte.  
3. **Bandwidth**: USB-FS MIDI (~bulk 64 B) implies compression or partial
   updates (tiles / RLE / low bpp).  

## Capture log

| Date | File | Source | Notes |
|------|------|--------|-------|
| | | | |

## Replay experiments

| Date | Tool | Result |
|------|------|--------|
| 2026-07-22 | `send_sysex.py --probe` / identity | Device **replies** identity on G/A/Control |
| 2026-07-22 | Short extract only (`05 05` etc.) | Wire OK · **screens no change** |
| 2026-07-22 | Full reassembly (incl. `05 09` ~2.5 KB×70) | Wire OK large Tx · visual TBD |

**Confirmed framing:** `F0 47 <id> <cmd> … F7` (Akai/InMusic `0x47`).  
**Paint candidates:** cmd `05 09` (large), also `05 07` / `05 0a` / `05 31`.  
**Status stream:** cmd `05 05` (29 B, high rate) — not enough alone to leave logo.  

### Open / dual-screen sequence (capture v2, 2026-07-22)

Reproducible on each VDJ open (Left + Right display):

```text
05 06, 05 08          # short handshake
05 30                 # ~1182 B init
05 01 ×2  (deck 01, 03)
05 02 ×2  (deck 01, 03)
05 07 ×8  deck 01 then ×8 deck 03   # ~602 B strips
… chrome (05 24 / 05 22 / 05 05 …)
05 31 ×2  (deck 01, 03)             # ~2353 B
05 0a … / 05 09 …                   # text / paint tiles
```

**Deck byte** at SysEx offset **10** is a **software deck number** (`01`–`04`), not “cable left/right”.

Standard VDJ dual-screen assignment (4 decks):

| Physical LCD | Automatic decks | SysEx deck byte(s) |
|--------------|-----------------|--------------------|
| **Left** (Display Left) | **1, 3** (user order **3,1**) | `0x01`, `0x03` |
| **Right** (Display Right / screen 2) | **2, 4** | `0x02`, `0x04` |

Paint in our short captures is heavy on `01` (and some `03` for chrome strips). Right-screen work should target **`02`/`04`**, not only `03`.  
Full notes: `captures/NV_Capture.ANALYSIS.md` (v2).

## References

- This repo `docs/HARDWARE.md`  
- VirtualDJ hardware manual (behaviour only): https://virtualdj.com/manuals/hardware/numark/nv.html  
- Mixxx forum history: display protocol undocumented publicly  

## Capture log

| Date | File | Source | Notes |
|------|------|--------|-------|
| 2026-07-22 | `captures/linux-vdj-usb-20260722-021045.pcapng` | Linux usbmon1 + VDJ/Wine | Graphics OUT = CC only, no SysEx paint |
| 2026-07-22 | `captures/linux-vdj-usb-20260722-020614.pcapng` | Linux usbmon1 + VDJ/Wine | Earlier run, same pattern |
| 2026-07-22 | `captures/linux-vdj-startup-20260722-021615.pcapng` | **Startup** (capture before VDJ open) | **SysEx present** — see below |

### Startup capture detail (`linux-vdj-startup-20260722-021615`)

USB capture started **before** VDJ launch (~90s, ~193k packets, 52 MB).

**Graphics OUT Code Index counts:**

| CIN | Meaning | Count |
|-----|---------|------:|
| 0xB | Control Change | 64 |
| 0x4 | SysEx continue | 8 |
| 0x7 | SysEx end (3 bytes) | 4 |
| 0x5 | SysEx end (1 byte) | 2 |

**Unique reassembled SysEx (each seen ×2, likely dual-cable/deck):**

```text
F0 7E 7F 06 01 F7     # MIDI identity request (universal non-realtime)
F0 7E 00 06 01 F7     # identity request, device 0
F0 00 20 7F 03 01 F7  # proprietary (mfr 00 20 7F) — likely Numark/InMusic probe
```

**Not seen:** large multi-kB image SysEx / paint frames (max USB data_len on Graphics OUT still tiny: 4–28 bytes).

**Kernel Tx after startup:** Graphics ~13–14 KB (init + CCs), not continuous paint rate.

So: **startup does send SysEx**, but only **short handshake/identity**, not LCD bitmaps under Wine.
