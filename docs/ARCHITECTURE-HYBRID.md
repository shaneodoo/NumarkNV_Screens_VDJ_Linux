# Hybrid architecture: Wine VDJ + nv-screens LCDs

## Goal

VirtualDJ under **Wine** keeps doing what it already does well (mix, library,
**NV Control** pads/jogs). **nv-screens** owns the dual LCDs via **libusb bulk**
(the only path proven to paint on Linux).

To get *live* display content out of VDJ we must make VDJ believe it has the
same **Left Display / Right Display** targets it uses on Windows, **before** it
starts, so the built-in controller definition can open them and (hopefully)
emit `CMIDIOutputSysexImage` traffic. We log that traffic and, when present,
forward it as USB-MIDI bulk cells to the real panels.

```
                    ┌─────────────────────────────┐
                    │   VirtualDJ (Wine)          │
                    │   device NMNV + displays    │
                    └──────┬──────────┬───────────┘
           pads/jogs/LEDs  │          │  display SysEx (desired)
                           ▼          ▼
                  ┌────────────┐  ┌──────────────────────────┐
                  │ NV Control │  │ nv-screens               │
                  │ (kernel    │  │  "NV Display Left"       │
                  │  ALSA)     │  │  "NV Display Right"      │
                  └────────────┘  │  (ALSA ports, pre-VDJ)   │
                                  │         │                │
                                  │    if SysEx arrives      │
                                  │         ▼                │
                                  │  encode → USB-MIDI cells │
                                  │         ▼                │
                                  │  libusb bulk → real LCDs │
                                  └──────────────────────────┘
                  ┌────────────┐
                  │ NV Audio   │  PCM stays on kernel for sound
                  │ (ALSA)     │
                  └────────────┘
```

## Why this shape

| Piece | Owner | Why |
|-------|--------|-----|
| Control MIDI | Kernel + VDJ | Works under Wine today |
| Audio PCM | Kernel + VDJ | Sound path |
| LCD paint | **nv-screens libusb** | amidi/ALSA reassembly does **not** paint; raw bulk does |
| Display “devices” VDJ opens | **nv-screens virtual ports** | On Windows VDJ maps **Left/Right LCD**; we must present equivalents early |

Mapper XML (`NMNV`) only maps buttons/LEDs. LCD pixels come from the **built-in
definition** (`controllers.dat` / `CMIDIOutputSysexImage`), not from the custom
mapper.

## Startup order (critical)

1. Plug NV, ALSA sees Control / Graphics / Audio.  
2. **Start nv-screens display proxy** (Left + Right ports up, optional claim Graphics bulk).  
3. **Then** start VirtualDJ / Wine.  
4. In VDJ Controllers: bind Left/Right displays to our ports if not auto-detected.  
5. Wire qpwgraph if needed: Wine outs → Display Left/Right; **do not** fight libusb on Graphics if claimed.

If VDJ starts first, it may bind the real **NV Graphics** port and never see our proxies.

## What we already have (enough to build the proxy)

| Data | Source | Use |
|------|--------|-----|
| USB-MIDI bulk framing that **paints** | WinBoat USBPcap → `bulk-out.bin` | libusb replay / forward path |
| Init / paint SysEx cmds (`0506`…`0509`/`0531`) | decoded traffic CSV | protocol map |
| Deck → screen | user + captures: Left **1,3** Right **2,4** | routing |
| Identity SysEx from panels | Wine startup Log Report | reply when VDJ probes devices |
| CreateMidiLog under Wine | `midilog.dat` | short notes only this session — baseline for “no paint yet” |
| Proof Wine does not paint today | Linux USB capture: Graphics OUT = CC only | limitation baseline |

We do **not** yet have: live frame encoder from deck state alone, or a captured
Windows **Left/Right as separate ports** enumeration dump (names/IDs VDJ stores).

## Wine limitations (measured, not theoretical)

1. **Paint SysEx absent under Wine today**  
   Host→Graphics bulk is short CC; CreateMidiLog has **no `F0` paint**; midilog
   was only note 98 on/off. So either:
   - VDJ never runs `CMIDIOutputSysexImage` on Wine, **or**
   - it only runs when the display endpoints look/behave like Windows (hypothesis
     we test with Left/Right proxies).

2. **Wine ALSA MIDI may not be ideal for multi‑KB SysEx**  
   Even if VDJ emits paint, long SysEx can be fragmented/truncated in winealsa.
   Mitigation: capture at our ports; if truncated, try larger buffers / rawmidi
   bridge / different Wine MIDI backend.

3. **Real NV Graphics vs virtual displays**  
   If both exist, VDJ may bind the real device and ignore proxies. Proxy mode may
   need to **detach/hide** kernel Graphics MIDI while still using libusb for paint.

4. **Latency**  
   Forward path must stay drop-old, zero inter-URB delay (DJs hate delayed
   waveforms). Never queue seconds of paint frames.

5. **Wine is still required for the experiment**  
   Agree: only VDJ has the private encoder. We use Wine to *elicit* the stream;
   we do not reimplement VDJ’s DSP. If Wine never emits SysEx, fallback is
   WinBoat/native Windows bridge or a future open encoder.

## Success criteria for the proxy experiment

| Result | Meaning |
|--------|---------|
| VDJ lists **NV Display Left/Right** and opens them | Port presentation OK |
| CreateMidiLog / our CSV shows **large SysEx** (`F0 47…`) while decks play | Wine paint path unlocked → forward to bulk |
| Still only CC / short MIDI | Limitation is inside VDJ/Wine, not port names → need Windows-side bridge or encoder |

## Non-goals (for now)

- Replacing VDJ mixing  
- Kernel driver for LCDs  
- Perfect logo teardown until we capture Windows File→Exit bulk  
