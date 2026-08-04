"""
Low-latency USB-MIDI bulk helpers for Numark NV screens.

Firmware only paints when we write USB-MIDI event packets (CIN 4/5/6/7)
directly to the bulk OUT endpoint via libusb. ALSA/amidi reassembly is
not enough for this device.
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import usb.core
import usb.util

VID = 0x15E4
PID_GRAPHICS = 0x2033
PID_AUDIO = 0x1033
PID_CONTROL = 0x1005

# Default paint targets (Control stays free for VDJ pads/jogs).
DEFAULT_PAINT_PIDS = (PID_GRAPHICS, PID_AUDIO)

# Deck assignment on dual LCDs (user-confirmed):
#   Left  = decks 1, 3
#   Right = decks 2, 4
LEFT_DECKS = (0x01, 0x03)
RIGHT_DECKS = (0x02, 0x04)
ALL_DECKS = LEFT_DECKS + RIGHT_DECKS


def sysex_to_usb_midi(msg: bytes) -> bytes:
    """Pack raw SysEx (or long stream) into USB-MIDI event packets (4 bytes each)."""
    out = bytearray()
    i = 0
    n = len(msg)
    while i + 3 < n:
        out += bytes((0x04, msg[i], msg[i + 1], msg[i + 2]))
        i += 3
    rem = n - i
    if rem == 1:
        out += bytes((0x05, msg[i], 0, 0))
    elif rem == 2:
        out += bytes((0x06, msg[i], msg[i + 1], 0))
    elif rem == 3:
        out += bytes((0x07, msg[i], msg[i + 1], msg[i + 2]))
    return bytes(out)


def midi_to_usb_midi(msg: bytes) -> bytes:
    """
    Pack any short MIDI or SysEx into USB-MIDI bulk cells (CIN + 3 data).

    This is what Windows VDJ puts on the wire; ALSA/amidi re-encoding is not enough.
    """
    if not msg:
        return b""
    # SysEx / multi-byte stream starting with F0
    if msg[0] == 0xF0:
        return sysex_to_usb_midi(msg)
    st = msg[0]
    hi = st & 0xF0
    # Channel voice: 3-byte
    if hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
        cin = hi >> 4
        d1 = msg[1] if len(msg) > 1 else 0
        d2 = msg[2] if len(msg) > 2 else 0
        return bytes((cin, st, d1 & 0x7F, d2 & 0x7F))
    # Channel voice: 2-byte
    if hi in (0xC0, 0xD0):
        cin = hi >> 4
        d1 = msg[1] if len(msg) > 1 else 0
        return bytes((cin, st, d1 & 0x7F, 0))
    # Single-byte system realtime / common
    if st >= 0xF8 or st in (0xF1, 0xF2, 0xF3, 0xF6):
        return bytes((0x0F, st, 0, 0))
    # Fallback: treat as stream
    return sysex_to_usb_midi(msg)


def load_bulk_records(path: Path) -> list[tuple[int, int, bytes]]:
    """Load extract_usb_bulk.py format: <pid u16><ep u8><pad u8><len u32><payload>."""
    data = path.read_bytes()
    off = 0
    out: list[tuple[int, int, bytes]] = []
    while off + 8 <= len(data):
        pid, ep, _pad, length = struct.unpack_from("<HBBI", data, off)
        off += 8
        pl = data[off : off + length]
        off += length
        if len(pl) != length:
            break
        out.append((pid, ep, pl))
    return out


def load_tsv_sysex(path: Path) -> list[tuple[str, bytes]]:
    rows: list[tuple[str, bytes]] = []
    for ln in path.read_text().splitlines():
        if not ln.strip() or ln.startswith("#"):
            continue
        if "\t" in ln:
            port, hx = ln.split("\t", 1)
        else:
            port, hx = "graphics", ln
        try:
            rows.append((port.strip().lower(), bytes.fromhex(hx.strip())))
        except ValueError:
            continue
    return rows


def load_hex_sysex(path: Path, want_cmd: str | None = None) -> list[bytes]:
    out: list[bytes] = []
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        hx = ln.split("\t", 1)[-1]
        try:
            m = bytes.fromhex(hx)
        except ValueError:
            continue
        if len(m) < 6:
            continue
        if want_cmd and m[4:6].hex() != want_cmd:
            continue
        out.append(m)
    return out


def set_sysex_deck(msg: bytes, deck: int) -> bytes:
    if len(msg) <= 10:
        return msg
    b = bytearray(msg)
    b[10] = deck & 0x7F
    return bytes(b)


def set_sysex_id(msg: bytes, hi: int, lo: int) -> bytes:
    if len(msg) < 4:
        return msg
    b = bytearray(msg)
    b[2], b[3] = hi & 0x7F, lo & 0x7F
    return bytes(b)


@dataclass
class BulkHandle:
    dev: usb.core.Device
    pid: int
    ifn: int
    ep_out: int
    # Every interface we detached (Graphics exclusive may detach AC+MIDI)
    detached_ifns: list[int] = field(default_factory=list)


@dataclass
class LatencyStats:
    """Rolling latency stats for paint path (milliseconds)."""

    samples: list[float] = field(default_factory=list)
    max_keep: int = 256
    writes: int = 0
    fails: int = 0
    bytes_out: int = 0
    dropped: int = 0

    def add(self, ms: float) -> None:
        self.samples.append(ms)
        if len(self.samples) > self.max_keep:
            self.samples = self.samples[-self.max_keep :]

    def summary(self) -> str:
        if not self.samples:
            return f"writes={self.writes} fails={self.fails} dropped={self.dropped}"
        s = sorted(self.samples)
        p50 = s[len(s) // 2]
        p95 = s[int(len(s) * 0.95)]
        return (
            f"writes={self.writes} fails={self.fails} dropped={self.dropped} "
            f"lat_ms p50={p50:.2f} p95={p95:.2f} max={s[-1]:.2f} "
            f"bytes={self.bytes_out}"
        )


class NvBulkPainter:
    """
    Owns Graphics (and optionally Audio) MIDI bulk OUT for LCD paint.

    Control (1005) is never claimed — VDJ keeps pads/jogs.
    """

    def __init__(
        self,
        products: Iterable[int] = DEFAULT_PAINT_PIDS,
        write_timeout_ms: int = 500,
    ) -> None:
        self.want = list(products)
        self.write_timeout_ms = write_timeout_ms
        self.handles: list[BulkHandle] = []
        self.stats = LatencyStats()
        # Called with USBError when device disappears (errno 19) etc.
        self.on_fatal_usb: Callable[[BaseException], None] | None = None

    def open(self) -> None:
        self.close(reattach=False)
        for pid in self.want:
            dev = usb.core.find(idVendor=VID, idProduct=pid)
            if dev is None:
                print(f"[nv] missing 15e4:{pid:04x}", flush=True)
                continue
            # WinBoat: Audio 1033 = Display Left, Graphics 2033 = Display Right.
            # Graphics: exclusive (hide ALSA; facade presents "NV Graphics").
            # Audio: MIDI bulk only — hide Audio *MIDI* (facade "NV Audio") but
            # keep PCM for Wine/VDJ sound + NUMARK NV audio button.
            midi_only = pid == PID_AUDIO
            ifn, ep, detached = self._claim_midi(dev, midi_only=midi_only)
            self.handles.append(
                BulkHandle(
                    dev=dev,
                    pid=pid,
                    ifn=ifn,
                    ep_out=ep,
                    detached_ifns=detached,
                )
            )
            mode = (
                "midi-only (PCM free; facade = NV Audio / Display Left)"
                if midi_only
                else "exclusive (facade = NV Graphics / Display Right)"
            )
            print(
                f"[nv] claimed 15e4:{pid:04x} if={ifn} ep=0x{ep:02x} "
                f"detached={detached} ({mode})",
                flush=True,
            )
            if midi_only:
                # Detaching MIDI can drop the whole ALSA card (PCM gone).
                # Best-effort rebind of AC+AS without root when possible.
                try:
                    self._rebind_audio_pcm(dev)
                except Exception as e:
                    print(f"[nv] Audio PCM rebind note: {e}", flush=True)
        if not self.handles:
            raise RuntimeError(
                "No NV Graphics/Audio MIDI bulk claimed. "
                "Unplug WinBoat passthrough / stop other paint tools."
            )

    def _rebind_audio_pcm(self, dev: usb.core.Device) -> None:
        """Try to restore ALSA PCM after claiming Audio MIDI via usbfs."""
        import os
        import time as _time

        # Already have a card with usbid 15e4:1033?
        for usbid in Path("/proc/asound").glob("card*/usbid"):
            try:
                if usbid.read_text().strip().lower() == "15e4:1033":
                    print(
                        f"[nv] NV Audio PCM still present ({usbid.parent.name})",
                        flush=True,
                    )
                    return
            except OSError:
                continue

        # Resolve sysfs device path (…/1-4.2)
        try:
            bus = dev.bus
            addr = dev.address
        except Exception:
            return
        # Match /sys/bus/usb/devices/* by busnum/devnum
        base = Path("/sys/bus/usb/devices")
        devpath = None
        for d in base.iterdir():
            try:
                if (d / "busnum").read_text().strip() == str(bus) and (
                    d / "devnum"
                ).read_text().strip() == str(addr):
                    if (d / "idProduct").read_text().strip().lower() in (
                        "1033",
                        "0x1033",
                    ):
                        devpath = d
                        break
            except OSError:
                continue
        if devpath is None:
            print("[nv] NV Audio sysfs path not found for PCM rebind", flush=True)
            return

        # Prefer external helper (may use sudo) so bind/unbind work
        helper = Path.home() / "src/nv-screens/tools/rebind-nv-audio-pcm.sh"
        if helper.is_file() and os.access(helper, os.X_OK):
            import subprocess

            r = subprocess.run(
                [str(helper), str(devpath.name)],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if r.stdout.strip():
                print(r.stdout.strip(), flush=True)
            if r.returncode == 0:
                return
            if r.stderr.strip():
                print(f"[nv] rebind helper: {r.stderr.strip()}", flush=True)

        # Direct sysfs attempt (needs write access — usually root)
        drv = Path("/sys/bus/usb/drivers/snd-usb-audio")
        for ifn in (0, 2):  # AudioControl + AudioStreaming on NV Audio
            ifname = f"{devpath.name}:1.{ifn}"
            ifp = devpath.parent / ifname if False else Path(f"/sys/bus/usb/devices/{ifname}")
            if not ifp.exists():
                ifp = Path(f"/sys/bus/usb/devices/{devpath.name}:1.{ifn}")
            try:
                unbind = drv / "unbind"
                bind = drv / "bind"
                if (ifp / "driver").exists():
                    unbind.write_text(ifname)
                    _time.sleep(0.05)
                bind.write_text(ifname)
            except OSError as e:
                print(
                    f"[nv] PCM rebind {ifname} needs privileges ({e}); "
                    f"run tools/rebind-nv-audio-pcm.sh once with sudoers",
                    flush=True,
                )
                return
        _time.sleep(0.3)
        for usbid in Path("/proc/asound").glob("card*/usbid"):
            try:
                if usbid.read_text().strip().lower() == "15e4:1033":
                    print(
                        f"[nv] NV Audio PCM restored → {usbid.parent.name}",
                        flush=True,
                    )
                    return
            except OSError:
                continue
        print("[nv] NV Audio PCM still missing after rebind attempt", flush=True)

    def _claim_midi(
        self, dev: usb.core.Device, *, midi_only: bool = False
    ) -> tuple[int, int, list[int]]:
        try:
            cfg = dev.get_active_configuration()
        except usb.core.USBError:
            dev.set_configuration()
            cfg = dev.get_active_configuration()

        # Find MIDI Streaming interface (class 1 / subclass 3) first
        midi_ifn = None
        ep_out = None
        for intf in cfg:
            if intf.bInterfaceClass != 1 or intf.bInterfaceSubClass != 3:
                continue
            for ep in intf:
                if (
                    usb.util.endpoint_direction(ep.bEndpointAddress)
                    == usb.util.ENDPOINT_OUT
                    and usb.util.endpoint_type(ep.bmAttributes)
                    == usb.util.ENDPOINT_TYPE_BULK
                ):
                    midi_ifn = intf.bInterfaceNumber
                    ep_out = ep.bEndpointAddress
                    break
            if midi_ifn is not None:
                break
        if midi_ifn is None or ep_out is None:
            raise RuntimeError(f"No MIDI bulk OUT on {dev.idProduct:04x}")

        detached: list[int] = []

        def _detach(ifn: int) -> None:
            for attempt in range(3):
                try:
                    if dev.is_kernel_driver_active(ifn):
                        print(
                            f"[nv] detaching kernel if{ifn} on {dev.idProduct:04x}",
                            flush=True,
                        )
                        dev.detach_kernel_driver(ifn)
                        if ifn not in detached:
                            detached.append(ifn)
                    break
                except (NotImplementedError, usb.core.USBError) as e:
                    print(f"[nv] detach if{ifn} attempt {attempt}: {e}", flush=True)
                    time.sleep(0.15)

        if midi_only:
            # Leave AudioControl + AudioStreaming (PCM) on kernel for sound
            _detach(midi_ifn)
        else:
            # Exclusive: detach every interface so ALSA card vanishes
            for intf in cfg:
                _detach(intf.bInterfaceNumber)

        usb.util.claim_interface(dev, midi_ifn)
        return midi_ifn, ep_out, detached

    def close(self, reattach: bool = True) -> None:
        for h in self.handles:
            try:
                usb.util.release_interface(h.dev, h.ifn)
            except Exception:
                pass
            if reattach:
                # Reattach *every* interface we detached (not only the paint IF)
                ifns = list(h.detached_ifns) if h.detached_ifns else [h.ifn]
                if h.ifn not in ifns:
                    ifns.append(h.ifn)
                for ifn in ifns:
                    try:
                        h.dev.attach_kernel_driver(ifn)
                        print(
                            f"[nv] reattached kernel if{ifn} on {h.pid:04x}",
                            flush=True,
                        )
                    except Exception as e:
                        print(
                            f"[nv] reattach if{ifn} {h.pid:04x}: {e}",
                            flush=True,
                        )
            try:
                usb.util.dispose_resources(h.dev)
            except Exception:
                pass
        self.handles.clear()
        # Brief settle so USB is quiet before optional device reset
        if not reattach:
            time.sleep(0.05)

    def _wait_alsa_restored(self, timeout_s: float = 5.0) -> bool:
        """Poll until Graphics + Audio MIDI show in amidi (no root needed)."""
        import subprocess

        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                out = subprocess.check_output(
                    ["amidi", "-l"], text=True, stderr=subprocess.DEVNULL
                )
            except Exception:
                out = ""
            has_g = "NV Graphics" in out or "Graphics" in out
            has_a = "NV Audio" in out
            has_pcm = any(
                p.read_text().strip().lower() == "15e4:1033"
                for p in Path("/proc/asound").glob("card*/usbid")
                if p.is_file()
            )
            if has_g and has_a and has_pcm:
                print(
                    f"[nv] ALSA restored in {time.time() - t0:.1f}s "
                    "(Graphics+Audio MIDI + PCM)",
                    flush=True,
                )
                return True
            time.sleep(0.25)
        return False

    def _attach_all_kernel_drivers(self, pid: int) -> None:
        """Bind snd-usb-audio on every unbound IF (user-level, no root)."""
        dev = usb.core.find(idVendor=VID, idProduct=pid)
        if dev is None:
            return
        try:
            try:
                dev.get_active_configuration()
            except usb.core.USBError:
                try:
                    dev.set_configuration()
                except Exception:
                    pass
            for ifn in range(0, 4):
                try:
                    if not dev.is_kernel_driver_active(ifn):
                        dev.attach_kernel_driver(ifn)
                        print(
                            f"[nv] attach_kernel if{ifn} on {pid:04x}",
                            flush=True,
                        )
                except (usb.core.USBError, NotImplementedError, ValueError):
                    pass
        except Exception as e:
            print(f"[nv] attach_all {pid:04x}: {e}", flush=True)

    def stock_firmware_reenum(self, *, wipe_already_done: bool = False) -> bool:
        """Stock restore via tools/usb-reset-nv.sh (sudo -n).

        WinUSBNCap finding:
          1) zero-chrome bulk wipe (skip if wipe_already_done — host did it)
          2) authorized 0→1 → firmware logos

        Must run AFTER bulk is fully released when wipe_already_done=True.
        """
        import subprocess

        tools = Path(__file__).resolve().parents[1] / "tools"
        if not tools.is_dir():
            tools = Path.home() / "src/nv-screens/tools"
        usb_script = tools / "usb-reset-nv.sh"
        if not usb_script.is_file():
            print(f"[nv] missing {usb_script}", flush=True)
            return False

        time.sleep(0.35)
        cmd = ["sudo", "-n", str(usb_script.resolve())]
        if wipe_already_done:
            cmd.append("--reenum-only")
            print("[nv] stock re-enum only (zero-wipe already done)…", flush=True)
        else:
            print("[nv] stock wipe + re-enum (WinUSBNCap close bulk → logos)…", flush=True)
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as e:
            print(f"[nv] stock re-enum failed to spawn: {e}", flush=True)
            return False

        for line in (r.stdout or "").splitlines():
            print(line, flush=True)
        for line in (r.stderr or "").splitlines():
            print(f"[nv-usb-reset:err] {line}", flush=True)

        ok = r.returncode == 0
        if ok:
            print("[nv] stock restore OK — blank tiles + firmware logos + ALSA", flush=True)
        else:
            print(
                f"[nv] stock restore rc={r.returncode} — "
                f"ensure: sudo -n {usb_script} (NOPASSWD, not under bwrap)",
                flush=True,
            )
        self._wait_alsa_restored(timeout_s=5.0)
        return ok

    def restore_after_session(self, *, usb_reset: bool = True) -> None:
        """After bulk release: optional attach leftovers, then stock re-enum.

        Preferred path for logos is stock_firmware_reenum() (authorized 0→1).
        """
        # Best-effort attach if anything still unbound (usually empty after re-enum)
        for pid in (PID_GRAPHICS, PID_AUDIO):
            self._attach_all_kernel_drivers(pid)
        time.sleep(0.2)

        if usb_reset:
            if self.stock_firmware_reenum():
                return
            print(
                "[nv] stock re-enum failed — MIDI may still return without logos",
                flush=True,
            )

        if self._wait_alsa_restored(timeout_s=3.0):
            print("[nv] ALSA present (logos may need manual usb-reset-nv.sh)", flush=True)
        else:
            print(
                "[nv] restore incomplete — run: sudo -n tools/usb-reset-nv.sh",
                flush=True,
            )

    def write_bulk(
        self,
        payload: bytes,
        pids: Iterable[int] | None = None,
        *,
        inter_chunk_s: float = 0.0,
    ) -> bool:
        """
        Write one USB bulk payload to matching handles.

        Latency: default inter_chunk_s=0 — fire URBs as fast as USB allows.
        Never sleep between chunks of a single frame; DJs hate delayed waveforms.
        """
        if not payload:
            return True
        want = set(pids) if pids is not None else None
        ok = True
        t0 = time.perf_counter()
        for h in self.handles:
            if want is not None and h.pid not in want:
                continue
            try:
                # Single URB when <=64; otherwise stream without artificial delay.
                off = 0
                n = len(payload)
                while off < n:
                    chunk = payload[off : off + 64]
                    written = h.dev.write(h.ep_out, chunk, timeout=self.write_timeout_ms)
                    if written != len(chunk):
                        ok = False
                    self.stats.bytes_out += written
                    off += 64
                    if inter_chunk_s > 0 and off < n:
                        time.sleep(inter_chunk_s)
                self.stats.writes += 1
            except usb.core.USBError as e:
                self.stats.fails += 1
                ok = False
                errno = getattr(e, "errno", None)
                if self.stats.fails <= 8:
                    print(f"[nv] USBError pid={h.pid:04x}: {e}", flush=True)
                # ENODEV / EIO often mean unplug or VDJ/host tore the bus
                if errno in (19, 5, 32) or "No such device" in str(e):
                    if self.on_fatal_usb:
                        try:
                            self.on_fatal_usb(e)
                        except Exception:
                            pass
        self.stats.add((time.perf_counter() - t0) * 1000.0)
        return ok

    def write_sysex(
        self,
        msg: bytes,
        pids: Iterable[int] | None = None,
        *,
        inter_chunk_s: float = 0.0,
    ) -> bool:
        # Route F0 47 <hi> <lo> … to the matching USB product when present
        # (Windows paint: 0x2033 Graphics vs 0x1033 Audio ≈ dual LCD streams).
        if pids is None and len(msg) >= 4 and msg[0] == 0xF0 and msg[1] == 0x47:
            prod = (msg[2] << 8) | msg[3]
            if any(h.pid == prod for h in self.handles):
                pids = [prod]
        return self.write_bulk(
            sysex_to_usb_midi(msg), pids=pids, inter_chunk_s=inter_chunk_s
        )

    def write_record(self, pid: int, ep: int, payload: bytes) -> bool:
        """Replay one captured bulk URB (exact bytes from USBPcap)."""
        for h in self.handles:
            if h.pid != pid:
                continue
            use_ep = ep if ep else h.ep_out
            t0 = time.perf_counter()
            try:
                n = h.dev.write(use_ep, payload, timeout=self.write_timeout_ms)
                self.stats.writes += 1
                self.stats.bytes_out += n
                self.stats.add((time.perf_counter() - t0) * 1000.0)
                return n == len(payload)
            except usb.core.USBError as e:
                self.stats.fails += 1
                if self.stats.fails <= 8:
                    print(f"[nv] USBError record pid={pid:04x}: {e}", flush=True)
                errno = getattr(e, "errno", None)
                if errno in (19, 5, 32) or "No such device" in str(e):
                    if self.on_fatal_usb:
                        try:
                            self.on_fatal_usb(e)
                        except Exception:
                            pass
                return False
        return False
