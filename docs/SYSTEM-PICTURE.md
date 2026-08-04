# How the system works (pictorial)

High-level picture of the Numark NV dual-LCD stack under Linux + Wine VirtualDJ.

**We make VDJ believe it has three Windows-style MIDI devices; we steal the two display bulk pipes with libusb to paint; we leave Control and Audio PCM to the kernel; we wake with captured bulk cells and live-stream with VDJ SysEx; we quit by releasing the bus and soft-replugging USB so firmware can logo again.**

---

## 1. Hardware: three USB gadgets, one controller

```text
                    ┌─────────────────────────────────────┐
                    │         Numark NV hardware          │
                    └─────────────────────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
              ▼                       ▼                       ▼
     ┌────────────────┐     ┌─────────────────┐     ┌─────────────────┐
     │ 15e4:1005      │     │ 15e4:1033       │     │ 15e4:2033       │
     │ NV Control     │     │ NV Audio        │     │ NV Graphics     │
     │ pads / jogs    │     │ Display LEFT    │     │ Display RIGHT   │
     │                │     │ + PCM audio     │     │ LCD only        │
     └───────┬────────┘     └────────┬────────┘     └────────┬────────┘
             │                       │                       │
             │ MIDI INT/bulk         │ EP 0x03 bulk MIDI     │ EP 0x03 bulk MIDI
             │                       │ EP 0x01 ISO  PCM      │
             │                       │                       │
        decks 1–4 pads          decks 1,3 on LCD          decks 2,4 on LCD
```

| USB product | Role | Who owns it while VDJ runs |
|-------------|------|----------------------------|
| **Control** `1005` | Pads, jogs, buttons | **Kernel ALSA** (always) |
| **Audio** `1033` | Left LCD MIDI + master/phones PCM | **libusb** claims MIDI only; **kernel keeps PCM** |
| **Graphics** `2033` | Right LCD MIDI | **libusb exclusive** (kernel MIDI card hidden) |

---

## 2. Software cast of characters

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  Desktop icon →  ~/bin/start-virtualdj.sh                                │
│                                                                          │
│   • starts nv-screens  (outside bwrap — so sudo USB reset can work)      │
│   • starts Wine VDJ    (inside bwrap only to bind patched winealsa.so)   │
│   • wires MIDI once                                                      │
│   • on exit: stop host → usb-reset-nv.sh (authorized 0→1) → logos        │
└──────────────────────────────────────────────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌─────────────────────┐            ┌─────────────────────────┐
│ tools2/nv_screens.py│            │ Wine + VirtualDJ.exe    │
│  • claim bulk       │            │  + winealsa.so (VID/PID)│
│  • wake LCDs        │            │                         │
│  • facade ALSA      │            │ Sees factory names:     │
│  • live paint loop  │            │  Numark NV              │
│  • light clear quit │            │  NV Display Left/Right  │
└──────────┬──────────┘            └────────────┬────────────┘
           │                                    │
           │              ALSA seq              │
           ▼                                    ▼
┌─────────────────────┐            ┌─────────────────────────┐
│ src2/alsa_patchbay  │◄───────────│ WINE midi driver        │
│ facade:             │            │  OUT → facade ports     │
│  NV Control         │            │  IN  ← Control bridge   │
│  NV Display Left    │            └─────────────────────────┘
│  NV Display Right   │
│  + bridge to kernel │
│    NV Control       │
└──────────┬──────────┘
           │ SysEx for LCDs only
           ▼
┌─────────────────────┐            ┌─────────────────────────┐
│ src2/usb_midi_bulk  │───────────►│ Real USB EP 0x03 bulk   │
│  write_record/sysex │            │  Left  = 1033           │
│  claim / release    │            │  Right = 2033           │
└─────────────────────┘            └─────────────────────────┘
```

---

## 3. What VDJ “sees” vs what the wire does

```text
                    VIRTUALDJ'S WORLD                    REAL HARDWARE
                    ─────────────────                    ─────────────

                 ┌──────────────────┐
                 │   Numark NV      │──── ALSA ────► kernel NV Control
                 │   (Control)      │                pads/jogs/LEDs
                 └──────────────────┘

                 ┌──────────────────┐         ┌────────────────────┐
                 │ NV Display Left  │──SysEx──►│ facade "Left"      │
                 │ (thinks Windows  │         │   ↓ libusb bulk    │
                 │  driver name)    │         │ 15e4:1033 EP 0x03  │──► LEFT LCD
                 └──────────────────┘         └────────────────────┘

                 ┌──────────────────┐         ┌────────────────────┐
                 │ NV Display Right │──SysEx──►│ facade "Right"     │
                 │                  │         │   ↓ libusb bulk    │
                 └──────────────────┘         │ 15e4:2033 EP 0x03  │──► RIGHT LCD
                                              └────────────────────┘

                 ┌──────────────────┐
                 │ Audio: NV Audio  │──── PCM ────► kernel 1033 ISO EP 0x01
                 │ (WASAPI/ALSA)    │               master / headphones
                 └──────────────────┘
```

**Why the facade exists:** stock Wine never exposes real USB VID/PID on MIDI the way Windows does. We present ports named like Windows (`NV Display Left` / `Right` or factory titles) plus patched `winealsa.so` so VDJ binds factory Controllers mappings—not custom XML hacks for the displays.

---

## 4. Lifecycle: open → live → close

```text
 TIME ──────────────────────────────────────────────────────────────────►

 ① START HOST                    ② START VDJ                 ③ PLAY
 ┌────────────────────┐         ┌──────────────────┐      ┌──────────────┐
 │ claim Graphics     │         │ VDJ identifies   │      │ continuous   │
 │ claim Audio MIDI   │         │ Control+L+R      │      │ 0509 paint   │
 │ (PCM stays kernel) │         │ opens MIDI outs  │      │ waveforms    │
 │                    │         │                  │      │ titles etc.  │
 │ WAKE (raw bulk):   │         │ wire_once:       │      │              │
 │  wake-open-plus-   │         │  Wine ↔ facade   │      │ port-routed  │
 │  empty.bin (~963   │         │  1:1             │      │ L→1033       │
 │  write_record URBs)│         └──────────────────┘      │ R→2033       │
 └────────────────────┘                                    └──────────────┘

 ④ FILE → EXIT / Wine dies
 ┌──────────────────────────────────────────────────────────────────────┐
 │ nv_screens:                                                          │
 │   light clear (zeroed 0505/0504/0520)  ← no empty-deck re-paint     │
 │   close facade (patchbay quiet)                                      │
 │   release bulk / reattach kernel                                     │
 │   exit quickly                                                       │
 │                                                                      │
 │ start-virtualdj.sh (after host dead):                                │
 │   sudo -n tools/usb-reset-nv.sh                                      │
 │     Graphics + Audio: authorized 0 → 1  (soft re-plug)               │
 │     → firmware cold start → NV logos (goal; still flaky sometimes)   │
 └──────────────────────────────────────────────────────────────────────┘
```

---

## 5. Live paint path (the hot path)

```text
  VirtualDJ draws deck UI
           │
           │  F0 47 … 05 09 … F7   (and friends)
           ▼
  WINE ALSA Output  #1 / #2
           │
           │  aconnect (wire once)
           ▼
  facade port "NV Display Left" or "… Right"
           │
           │  alsa_patchbay on_midi(port, raw)
           │  • ignore non-SysEx for LCD
           │  • route by PORT NAME only
           │    (not F0 47 product bytes — VDJ sometimes tags Left as 2033)
           ▼
  queue (FIFO, deep)  ──►  paint loop
           │
           │  sysex_to_usb_midi(raw)  →  4-byte USB-MIDI cells
           ▼
  painter.write_bulk(…, pids=[0x1033 or 0x2033])
           │
           ▼
  USB bulk OUT EP 0x03  →  LCD firmware paints tile
```

**Wake is different from live:** wake uses **exact captured bulk URBs** (`write_record`). Re-encoded SysEx alone does **not** cold-wake the panels. Live paint *is* re-encoded SysEx from VDJ, after the panels are already awake.

---

## 6. MIDI / patchbay map (while running)

```text
                    kernel                     user / Wine
                    ──────                     ───────────

  NV Control 24:0 ◄────────────────────────► facade 129:0  NV Control
       ▲                                         │
       │                              ┌──────────┼──────────┐
       │                              ▼          ▼          ▼
       │                         Wine IN    (identity /   notes)
       │                         131:0
       │
       │                    Wine OUT 131:1 ──► nv-screens 128:0 vdj_in
       │                    Wine OUT 131:2 ──► facade Left  129:1 ──► libusb 1033
       │                    Wine OUT 131:3 ──► facade Right 129:2 ──► libusb 2033
       │
  NV Graphics  (gone from amidi while claimed)
  NV Audio MIDI (hidden; PCM card still for sound)
```

While paint is active you should **not** see kernel “NV Graphics MIDI” in `amidi` — exclusive claim is intentional.

---

## 7. Capture files vs runtime roles

```text
  ┌─────────────────────────────────┐
  │ VDJ_start_stop_sequence.pcapng  │  WinUSBNCap (Windows USB capture)
  │  • empty-deck chrome            │────► wake-open-plus-empty bulk (chrome part)
  │  • File→Exit tail               │────► close knowledge / close-bulk.bin
  └─────────────────────────────────┘

  ┌─────────────────────────────────┐
  │ bulk-out.bin                    │  older capture
  │  • proven open URB slice        │────► first ~60 URBs of wake corpus
  └─────────────────────────────────┘

  ┌─────────────────────────────────┐
  │ LINUX_VDJ DUMP.pcapng           │  proof live path paints (0509×hundreds)
  └─────────────────────────────────┘

  Runtime wake file:
    captures/extracted-start-stop/wake-open-plus-empty.bin
         = bulk-out OPEN  +  WinUSBNCap EMPTY CHROME   (all write_record)
```

---

## 8. One-page storyboard

```text
  [Power / plug]     firmware logos on panels
         │
         ▼
  [start-virtualdj]  kill old host → start nv_screens → start Wine (bwrap)
         │
         ▼
  [claim USB]        Graphics exclusive + Audio MIDI-only
         │
         ▼
  [WAKE]             ~963 bulk URBs  →  empty Controllers look (no song tiles)
         │
         ▼
  [VDJ up]           identifies Control + Display L/R → wire once
         │
         ▼
  [PLAY]             live SysEx waterfall → left/right bulk → moving UI
         │
         ▼
  [EXIT]             light clear → facade down → release USB
         │
         ▼
  [usb-reset]        authorized 0→1 on 1033+2033  →  hope for NV logos
         │
         ▼
  [idle]             kernel MIDI all three products back; ready for next launch
```

---

## 9. Key files

| Path | Role |
|------|------|
| `~/bin/start-virtualdj.sh` | Desktop launcher |
| `tools2/nv_screens.py` | Live host |
| `src2/usb_midi_bulk.py` | libusb claim / paint / release |
| `src2/alsa_patchbay.py` | Facade + Control bridge |
| `src2/win_lifecycle.py` | Open/close helpers |
| `captures/extracted-start-stop/wake-open-plus-empty.bin` | Wake corpus (raw bulk) |
| `tools/usb-reset-nv.sh` | `authorized` 0→1 re-enum for logos |
| `tools/wire_hybrid.sh` | One-shot Wine ↔ facade aconnect |

---

## 10. Critical lessons

1. **Re-encoded SysEx alone does not wake firmware** — need exact bulk URBs (`write_record`).
2. **Empty deck ≠ `0509` paint** — WinUSBNCap dump has full empty chrome + close; `0509` is loaded-track tiles.
3. **Do not re-play wake bulk on quit** — logos then paint again.
4. **Do not wrap whole `start-virtualdj` in bwrap** — blocks `sudo` (no new privileges); only Wine is bwrap’d for winealsa.
5. **pyusb reset ≠ logos**; need hub / `authorized` re-enum after the host is fully dead.
6. **Route live paint by facade port name**, not `F0 47` product bytes (VDJ sometimes tags Left as `2033`).

---

## 11. Related docs / snapshots

- Status: `SESSION-STATUS.md`
- Pause handoff: `snapshots/working-20260730-001903-session-pause/SESSION-PAUSE.md`
- WinUSBNCap extract notes: `captures/extracted-start-stop/README.md`
