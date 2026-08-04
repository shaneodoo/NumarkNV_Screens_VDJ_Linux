# Wine + Numark NV screens — what actually helps

Generic “Wine bulk endpoint” guides are **mostly wrong for this controller**.
This file is what we measured on Fedora + Wine Staging 11 + VirtualDJ.

## Already in place on this machine

| Item | Status |
|------|--------|
| udev `99-numark-nv.rules` VID `15e4` MODE 0666, `audio`/`uaccess` | **Yes** |
| User in `audio` + `plugdev` | **Yes** |
| Large ALSA seq MIDI buffers (`snd-seq-midi`) | **Yes** |
| VDJ sees NV Control / Audio / Graphics MIDI under Wine | **Yes** (system report) |
| Controls / LEDs / audio usable under Wine | **Mostly yes** |
| LCD paint under Wine | **No** — logo only |

## Why the “roadmap” fails the evidence

1. **“Dedicated bulk endpoint Wine can’t see”**  
   NV **Graphics** is class-compliant **USB-MIDI bulk only** (EP 0x03). There is
   no third proprietary bulk IF. Linux binds it with `snd-usb-audio`. Wine
   reaches it as **ALSA rawmidi / winealsa MIDI**, not as a mystery HID bulk pipe.

2. **“udev plugdev will unlock screens”**  
   Permissions were never the blocker. Devices are `0666` / group `audio` and
   MIDI nodes are world-writable for the user. Still no paint SysEx from VDJ.

3. **WineBus `DisableDatagram` / `EnableHub`**  
   `winebus.sys` is primarily the **HID** bus. Forcing hub enumeration does not
   teach VDJ to emit `CMIDIOutputSysexImage` frames. Risk: fighting the kernel
   driver if something tries to claim USB twice. **Not applied** here.

4. **`sound=alsa` only**  
   Can reduce latency for PCM; we already force NV 4ch WASAPI-style routing in
   settings when useful. It does **not** create a display protocol path.

5. **`winebus:handle_hid_packet` warnings**  
   Expected noise if Wine probes non-HID interfaces. NV screens are not HID
   report streams.

## Real reason screens stay on “NV” under Wine

Windows USBPcap: heavy **`F0 47 …` SysEx** paint while decks paint.  
Linux + VDJ/Wine USB capture: **Control Change / short traffic only** — the
image SysEx stream is **not generated**.

So Wine *sees* the ports; the **Windows-only paint code path doesn’t run**.

## What actually works for screens today

| Approach | Result |
|----------|--------|
| Native Windows / WinBoat + USB passthrough | Screens work; best capture source |
| Wine VDJ | Controls/audio; **no LCD paint** |
| Linux SysEx replay (`amidi` / `nv_host_sim`) | Wire OK; **LCD no change** |
| libusb raw bulk URB replay | **LCD paints** (capture fragment) |
| Hybrid host `tools/nv_screens.py` | Wait for VDJ → claim Graphics bulk → low-latency paint loop; Control free for VDJ |

### Recommended hybrid workflow

1. Start `./tools/start-nv-screens.sh` (optionally `--graphics-only` so ALSA keeps full NV Audio).
2. Start VDJ under Wine — pads/jogs on Control, sound on NV Audio PCM.
3. Screens show the last captured session UI (until we encode live frames).

**Latency:** default `--paint-delay 0` (max USB speed). Pass-through uses a drop-old
queue so a backlog cannot delay the waveform the DJ is mixing.

## Safe optional tweaks (already done or low risk)

- Keep udev + large MIDI buffers (done).  
- `CreateMidiLog=yes` in VDJ settings for diagnostics (done in Wine profile).  
- Prefer **WinBoat capture** over Wine for protocol work.  
- Do **not** unload `snd-usb-audio` hoping Wine will grab raw bulk for MIDI class devices without a custom userspace driver.

## If someone still wants to try WineBus keys

Only as a controlled experiment (export registry first):

```reg
[HKEY_LOCAL_MACHINE\System\CurrentControlSet\Services\WineBus]
"Enable SDL"=dword:00000000
```

Modern Wine uses different keys over time; “DisableDatagram/EnableHub” from
random guides may be **no-ops or obsolete**. Verify against your Wine version
docs before relying on them.
