#!/usr/bin/env python3
"""
nv-screens hybrid host for VirtualDJ under Wine + Numark NV dual LCDs.

This version lives in tools2 and uses src2 helpers only.
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src2"))

from alsa_patchbay import AlsaPatchbay, RouteTable, ascii_graph  # noqa: E402
from csv_log import CsvTrafficLog  # noqa: E402
from usb_midi_bulk import (
    PID_AUDIO,
    PID_GRAPHICS,
    NvBulkPainter,
    load_bulk_records,
    load_hex_sysex,
    load_tsv_sysex,
    midi_to_usb_midi,
    sysex_to_usb_midi,
)  # noqa: E402
from usb_midi_decode import PRODUCT_NAMES  # noqa: E402

# Prefer the long Windows capture (paint-rich); fall back to short bulk-out.
_BULK_CANDIDATES = (
    ROOT / "captures/extracted-v2/bulk-long.bin",
    ROOT / "captures/extracted-v2/bulk-out.bin",
)
BULK_BIN = next((p for p in _BULK_CANDIDATES if p.is_file()), _BULK_CANDIDATES[-1])
# Short complete open+paint session — better for one-shot LCD wake than a
# truncated prefix of bulk-long (first paint is at URB ~1474 / ~4998).
WAKE_BULK_BIN = ROOT / "captures/extracted-v2/bulk-out.bin"
INIT1 = ROOT / "captures/extracted-v2/init-cycle-1.tsv"
INIT2 = ROOT / "captures/extracted-v2/init-cycle-2.tsv"
HEX_V2 = ROOT / "captures/extracted-v2/all-sysex-hex.txt"
HEX_V1 = ROOT / "captures/extracted/audio-sysex-hex.txt"

# bulk-long first 0509: Audio/Left ~1474, Graphics/Right ~4998. Truncating
# earlier mid-message desyncs firmware → black LCDs.
_MIN_WAKE_URBS_LONG = 5200

# Capture UI that still *looks* like the old WinBoat session (track art/title
# "After Burn", tempo, waveforms). These are mostly bitmap tiles (0507/0524/0509),
# not plain-text 0531 — so skipping only 0531/0509 still left After Burn on screen.
_CAPTURE_CONTENT_CMDS = frozenset({
    "0507",  # deck chrome tiles (include track title pixels)
    "0509",  # paint
    "0524",  # waveform / UI blocks
    "0531",  # title metadata
    "0521",  # text lines
    "050a",  # browser
    "0504",  # short status text
    "0505",  # tempo / transport status
})
# Cold open / blank: session open + splash only. No 0501/0522/etc. (those still
# draw leftover deck chrome). Title/artist after VDJ is up is usually live 0521.
_OPEN_ONLY_CMDS = frozenset({"0506", "0508", "0530"})


def bulk_open_cut(records: list[tuple[int, int, bytes]]) -> int:
    """Index of last URB of dual-product open (0506/0508/0530 both done)."""
    stream: dict[int, bytearray] = {}
    open_cmds: dict[int, set[str]] = {}
    open_done: dict[int, bool] = {}
    cut = min(80, max(0, len(records) - 1))
    for i, (pid, _ep, pl) in enumerate(records):
        st = stream.setdefault(pid, bytearray())
        open_cmds.setdefault(pid, set())
        open_done.setdefault(pid, False)
        for j in range(0, len(pl), 4):
            if j + 4 > len(pl):
                break
            cin = pl[j] & 0xF
            d = pl[j + 1 : j + 4]
            if cin == 4:
                st += d
            elif cin == 5:
                st += d[:1]
            elif cin == 6:
                st += d[:2]
            elif cin == 7:
                st += d[:3]
            else:
                continue
            while True:
                try:
                    s = st.index(0xF0)
                    e = st.index(0xF7, s)
                except ValueError:
                    if st and 0xF0 not in st:
                        st.clear()
                    elif st and st[0] != 0xF0:
                        try:
                            del st[: st.index(0xF0)]
                        except ValueError:
                            st.clear()
                    break
                msg = bytes(st[s : e + 1])
                del st[: e + 1]
                cmd = msg[4:6].hex() if len(msg) >= 6 else ""
                if cmd in ("0506", "0508", "0530"):
                    open_cmds[pid].add(cmd)
                    if {"0506", "0508", "0530"} <= open_cmds[pid]:
                        open_done[pid] = True
                    if all(open_done.get(p) for p in (PID_AUDIO, PID_GRAPHICS)):
                        return i
    return cut


def bulk_wake_prefix(
    records: list[tuple[int, int, bytes]],
    mode: str = "chrome",
) -> list[tuple[int, int, bytes]]:
    """Raw URB slice for open/full modes (chrome uses filtered actions instead)."""
    mode = (mode or "chrome").strip().lower()
    if not records:
        return []
    if mode in ("full", "all", "session", "chrome", "ui", "default"):
        # chrome keeps full corpus; wake player filters title/paint SysEx
        return list(records)
    if mode in ("open", "init", "minimal"):
        return records[: bulk_open_cut(records) + 1]
    return list(records)


def _first_open_cycle_actions(
    records: list[tuple[int, int, bytes]],
) -> list[tuple[str, int, bytes]]:
    """One open cycle per product: CC + 0506/0508/0530 only (no second reopen)."""
    actions = bulk_wake_actions(
        records, keep_cmds=_OPEN_ONLY_CMDS, include_cc=True
    )
    # Keep CC + first 0506/0508/0530 per pid only
    seen: dict[int, set[str]] = {}
    out: list[tuple[str, int, bytes]] = []
    for kind, pid, payload in actions:
        if kind != "sysex":
            out.append((kind, pid, payload))
            continue
        cmd = payload[4:6].hex() if len(payload) >= 6 else ""
        got = seen.setdefault(pid, set())
        if cmd in got:
            continue
        if cmd in _OPEN_ONLY_CMDS:
            got.add(cmd)
            out.append((kind, pid, payload))
        if all(
            _OPEN_ONLY_CMDS <= seen.get(p, set())
            for p in (PID_AUDIO, PID_GRAPHICS)
        ):
            # Still allow remaining CC raw if any trailing; stop further sysex
            # by marking both complete — drop later reopen cycles
            pass
    # Drop sysex after both products have full open set
    final: list[tuple[str, int, bytes]] = []
    done = {PID_AUDIO: False, PID_GRAPHICS: False}
    for kind, pid, payload in out:
        if kind == "sysex":
            if done.get(pid):
                continue
            final.append((kind, pid, payload))
            cmd = payload[4:6].hex() if len(payload) >= 6 else ""
            if cmd == "0530":
                done[pid] = True
        else:
            # CC only before/during open, not after both done
            if not all(done.values()):
                final.append((kind, pid, payload))
    return final


def bulk_wake_actions(
    records: list[tuple[int, int, bytes]],
    *,
    skip_cmds: frozenset[str] | None = None,
    keep_cmds: frozenset[str] | None = None,
    include_cc: bool = True,
) -> list[tuple[str, int, bytes]]:
    """Expand capture URBs into ordered wake/blank actions.

    keep_cmds: if set, only those SysEx cmds (plus optional CC) — used for
    clean open/splash and shutdown (no After Burn tiles).
    skip_cmds: drop these cmds (chrome mode keeps structure, drops deck art).
    """
    if skip_cmds is None:
        skip_cmds = _CAPTURE_CONTENT_CMDS
    actions: list[tuple[str, int, bytes]] = []
    stream: dict[int, bytearray] = {}

    for pid, _ep, pl in records:
        if not pl:
            continue
        # Fast path: pure short-MIDI URB (CC etc.)
        if len(pl) == 4 and (pl[0] & 0xF) not in (4, 5, 6, 7):
            if include_cc:
                actions.append(("raw", pid, pl))
            continue

        st = stream.setdefault(pid, bytearray())
        raw_cells = bytearray()
        for j in range(0, len(pl), 4):
            if j + 4 > len(pl):
                break
            cell = pl[j : j + 4]
            cin = cell[0] & 0xF
            d = cell[1:4]
            if cin not in (4, 5, 6, 7):
                if include_cc:
                    if raw_cells:
                        actions.append(("raw", pid, bytes(raw_cells)))
                        raw_cells.clear()
                    actions.append(("raw", pid, bytes(cell)))
                continue
            if cin == 4:
                st += d
            elif cin == 5:
                st += d[:1]
            elif cin == 6:
                st += d[:2]
            elif cin == 7:
                st += d[:3]
            while True:
                try:
                    s = st.index(0xF0)
                    e = st.index(0xF7, s)
                except ValueError:
                    if st and 0xF0 not in st:
                        st.clear()
                    elif st and st[0] != 0xF0:
                        try:
                            del st[: st.index(0xF0)]
                        except ValueError:
                            st.clear()
                    break
                msg = bytes(st[s : e + 1])
                del st[: e + 1]
                cmd = msg[4:6].hex() if len(msg) >= 6 else ""
                if keep_cmds is not None:
                    if cmd not in keep_cmds:
                        continue
                elif cmd in skip_cmds:
                    continue
                actions.append(("sysex", pid, msg))
        if raw_cells and include_cc:
            actions.append(("raw", pid, bytes(raw_cells)))

    return actions

VDJ_NAME_HINTS = (
    "virtualdj",
    "virtualdj8",
    "virtualdj.exe",
    "vdj",
)


def vdj_running() -> bool:
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            try:
                cmd = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                    "utf-8", "replace"
                ).lower()
            except (OSError, PermissionError):
                continue
            if not cmd.strip():
                continue
            if "nv_screens" in cmd or "nv-screens" in cmd:
                continue
            for hint in VDJ_NAME_HINTS:
                if hint in cmd:
                    return True
            if "virtualdj" in cmd or "virtual dj" in cmd:
                return True
    except OSError:
        pass
    return False


def wait_for_vdj(poll_s: float = 0.5, timeout_s: float = 0.0) -> bool:
    print("[nv] waiting for VirtualDJ… (Ctrl+C to quit)", flush=True)
    t0 = time.time()
    while True:
        if vdj_running():
            print("[nv] VirtualDJ detected", flush=True)
            return True
        if timeout_s > 0 and (time.time() - t0) >= timeout_s:
            print("[nv] wait timeout — starting paint anyway", flush=True)
            return False
        time.sleep(poll_s)


class DropOldQueue:
    """Thread-safe live paint queue of (bulk_bytes, pids|None).

    *live=True*: FIFO order (multi-packet frames). Drop oldest when full.
    *live=False*: keep-newest burst (capture hybrid).
    """

    def __init__(self, maxlen: int = 64, *, live: bool = True) -> None:
        self._q: deque = deque(maxlen=maxlen)
        self._cv = threading.Condition()
        self.dropped = 0
        self.live = live

    def put(self, item) -> None:
        with self._cv:
            if self._q.maxlen is not None and len(self._q) >= self._q.maxlen:
                self.dropped += 1
            self._q.append(item)
            self._cv.notify()

    def get(self, timeout: float | None = None):
        with self._cv:
            if not self._q:
                if timeout is None:
                    self._cv.wait()
                else:
                    self._cv.wait(timeout)
            if not self._q:
                return None
            if self.live:
                return self._q.popleft()
            item = self._q.pop()
            n = len(self._q)
            if n:
                self.dropped += n
                self._q.clear()
            return item

    def drain(self, max_n: int = 32) -> list:
        with self._cv:
            out = []
            while self._q and len(out) < max_n:
                out.append(self._q.popleft() if self.live else self._q.pop())
            if not self.live and self._q:
                self.dropped += len(self._q)
                self._q.clear()
            return out


def build_init_msgs() -> list[bytes]:
    msgs: list[bytes] = []
    for path in (INIT1, INIT2):
        if not path.is_file():
            continue
        for _port, m in load_tsv_sysex(path):
            if len(m) >= 6 and m[0] == 0xF0 and m[1] == 0x47:
                msgs.append(m)
    return msgs


def build_clear_msgs() -> list[bytes]:
    clear_cmds = {"0502", "0506", "0508", "0530"}
    msgs: list[bytes] = []
    for path in (INIT1, INIT2):
        if not path.is_file():
            continue
        for _port, m in load_tsv_sysex(path):
            if len(m) >= 6 and m[0] == 0xF0 and m[1] == 0x47:
                if m[4:6].hex() in clear_cmds:
                    msgs.append(m)
    return msgs


def build_paint_corpus() -> tuple[list[bytes], list[bytes]]:
    paint: list[bytes] = []
    status: list[bytes] = []
    # Prefer long-capture assembled SysEx (full session, not short bulk-out)
    long_tsv = ROOT / "captures/extracted-v2/bulk-long.traffic.sysex.tsv"
    paths = [
        long_tsv,
        HEX_V1,
        HEX_V2,
        ROOT / "captures/extracted/all-sysex-hex.txt",
        ROOT / "captures/extracted-v2/all-sysex-hex.txt",
    ]
    for path in paths:
        if not path.is_file():
            continue
        # TSV format: product\tcmd\trole\tid\tdeck\tlen\thex
        if path.suffix == ".tsv" or path.name.endswith(".sysex.tsv"):
            for ln in path.read_text().splitlines()[1:]:
                parts = ln.split("\t")
                if len(parts) < 7:
                    continue
                cmd, hx = parts[1], parts[-1]
                try:
                    m = bytes.fromhex(hx)
                except ValueError:
                    continue
                if cmd == "0509":
                    paint.append(m)
                elif cmd == "0505":
                    status.append(m)
                elif cmd == "0531" and len(m) >= 1000:
                    paint.append(m)
        else:
            if not paint:
                paint = load_hex_sysex(path, "0509")
            status.extend(load_hex_sysex(path, "0505"))
            big = [m for m in load_hex_sysex(path) if len(m) >= 2000]
            for m in big:
                if m not in paint:
                    paint.append(m)
        if paint and status:
            break
    # Cap status to keep loop snappy; keep many paint frames for motion
    if len(status) > 800:
        status = status[:: max(1, len(status) // 800)]
    if len(paint) > 2500:
        # subsample evenly to keep memory/loop reasonable
        step = max(1, len(paint) // 2500)
        paint = paint[::step]
    if not paint:
        for path in (INIT1, INIT2):
            if path.is_file():
                paint.extend(m for _, m in load_tsv_sysex(path) if len(m) > 1000)
    return paint, status


class NvScreensDaemon:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.stop = threading.Event()
        products = [PID_GRAPHICS]
        if not args.graphics_only:
            products.append(PID_AUDIO)
        self.painter = NvBulkPainter(
            products=products,
            write_timeout_ms=args.write_timeout_ms,
        )
        # Live path: deep FIFO so multi-tile display frames aren't discarded
        live = bool(getattr(self.args, "live_only", False))
        self.pass_q = DropOldQueue(maxlen=128 if live else 8, live=live)
        self._live_paint_until = 0.0  # wall time: suppress capture while live F0 47 flows
        self._lcd_woken = False
        self._wake_lock = threading.Lock()
        self.bulk_records: list[tuple[int, int, bytes]] = []
        self.wake_records: list[tuple[int, int, bytes]] = []
        self.wake_actions: list[tuple[str, int, bytes]] = []
        self.open_actions: list[tuple[str, int, bytes]] = []  # splash only (shutdown)
        self.wake_mode: str = "chrome"
        self.init_msgs: list[bytes] = []
        self.paint_msgs: list[bytes] = []
        self.status_msgs: list[bytes] = []
        self.clear_msgs: list[bytes] = []
        self._pt_thread: threading.Thread | None = None
        self.csv = None  # CsvTrafficLog | None
        self.patchbay = None  # AlsaPatchbay | None
        self._vdj_csv = None  # CsvTrafficLog | None
        self._csv_every = max(1, int(args.csv_every))
        self._csv_n = 0
        self._vdj_monitor: threading.Thread | None = None
        self._vdj_running = False
        self._vdj_seen_once = False  # only auto-exit after VDJ has actually run
        self._vdj_gone_since: float | None = None
        self._last_activity = time.time()
        self._exit_reason = ""

        # USB gone (ENODEV) → request clean shutdown
        def _fatal_usb(err: Exception) -> None:
            if self.stop.is_set():
                return
            self._exit_reason = f"usb_gone: {err}"
            print(f"[nv] fatal USB — shutting down ({err})", flush=True)
            self.stop.set()

        self.painter.on_fatal_usb = _fatal_usb

    def mark_activity(self) -> None:
        self._last_activity = time.time()

    def setup(self) -> None:
        if BULK_BIN.is_file():
            self.bulk_records = load_bulk_records(BULK_BIN)
            print(f"[nv] bulk corpus: {len(self.bulk_records)} URBs from {BULK_BIN.name}")
        # Wake corpus: short bulk-out. chrome = full dual UI minus title/paint.
        import os

        # Default open = splash only. chrome still strips tiles but can leave
        # residual fields; full = entire capture session (debug only).
        self.wake_mode = (
            getattr(self.args, "wake_mode", None)
            or os.environ.get("NV_WAKE_MODE")
            or "open"
        )
        raw_wake: list[tuple[int, int, bytes]] = []
        if WAKE_BULK_BIN.is_file():
            raw_wake = load_bulk_records(WAKE_BULK_BIN)
            src_name = WAKE_BULK_BIN.name
        elif self.bulk_records:
            raw_wake = self.bulk_records[: max(_MIN_WAKE_URBS_LONG, 5200)]
            src_name = f"{BULK_BIN.name}[:{len(raw_wake)}]"
        else:
            src_name = "(none)"
        self.wake_records = bulk_wake_prefix(raw_wake, mode=str(self.wake_mode))
        # Splash-only (first open cycle per product) for blank + default wake
        if self.wake_records:
            self.open_actions = _first_open_cycle_actions(self.wake_records)
        # chrome = skip deck tiles but keep setup msgs (may still look busy)
        if self.wake_mode in ("chrome", "ui"):
            self.wake_actions = bulk_wake_actions(
                self.wake_records,
                skip_cmds=_CAPTURE_CONTENT_CMDS,
                include_cc=True,
            )
        elif self.wake_mode in ("open", "init", "minimal", "splash", "default", ""):
            self.wake_actions = list(self.open_actions)
        else:
            self.wake_actions = []  # full uses raw URBs
        print(
            f"[nv] wake corpus: {len(self.wake_records)} URBs from {src_name} "
            f"mode={self.wake_mode} wake_actions={len(self.wake_actions)} "
            f"open/splash={len(self.open_actions)} "
            f"(default open = 0506/0508/0530 only, no title tiles)",
            flush=True,
        )
        self.init_msgs = build_init_msgs()
        self.clear_msgs = build_clear_msgs()
        self.paint_msgs, self.status_msgs = build_paint_corpus()
        print(
            f"[nv] init_msgs={len(self.init_msgs)} "
            f"clear_msgs={len(self.clear_msgs)} "
            f"paint={len(self.paint_msgs)} status={len(self.status_msgs)}",
            flush=True,
        )
        if self.args.csv_log:
            self.csv = CsvTrafficLog(Path(self.args.csv_log), max_hex=self.args.csv_max_hex)
            print(f"[nv] CSV log → {self.args.csv_log} (every {self._csv_every} URB)", flush=True)
        if self.args.patchbay:
            try:
                routes = RouteTable()
                if self.args.routes and Path(self.args.routes).is_file():
                    routes = RouteTable.load(Path(self.args.routes))
                print(ascii_graph(routes, live={
                    "wine_vdj": "(Wine)",
                    "capture": "(bulk corpus)",
                    "inject": "(inject_in)",
                    "graphics_bulk": "(libusb LCD)",
                    "csv": "(csv log)" if self.csv else "(off)",
                    "monitor": "(monitor_out)",
                }))
                # Virtual NV Graphics facade: Wine/VDJ *sees* Graphics IN so it
                # will open an OUT path; real USB paint stays libusb-only.
                vgfx = not getattr(self.args, "no_virtual_graphics", False)
                dports = not getattr(self.args, "no_display_ports", False)
                self.patchbay = AlsaPatchbay(
                    virtual_graphics=vgfx,
                    display_ports=dports,
                )
                self.patchbay.open()
                vdj_csv_path = Path(self.args.vdj_csv or (ROOT / "captures/vdj-from-wine.csv"))
                self._vdj_csv = CsvTrafficLog(vdj_csv_path, max_hex=256)

                def _on_event(row: dict) -> None:
                    row.setdefault("direction", "wine_to_nv")
                    try:
                        self._vdj_csv.write(row)
                    except Exception:
                        pass

                # allowlist and lightweight metadata throttling
                allow_set = {s.strip().lower() for s in (self.args.allow_sysex or "").split(",") if s.strip()}
                metadata_cmds = {"050a", "0505", "0531"}
                last_sent: dict[str, float] = {}
                throttle_s = max(0.001, float(getattr(self.args, "metadata_throttle_ms", 150)) / 1000.0)

                def _on_midi(port: str, raw: bytes) -> None:
                    """
                    Wine → facade port → USB-MIDI bulk (correct product per display).

                    Display Left  → force product 15e4:1033 (0x10 0x33)
                    Display Right → force product 15e4:2033 (0x20 0x33)
                    Control / vdj_in: no LCD bulk (Control uses ALSA bridge).
                    """
                    if not raw:
                        return
                    port_l = (port or "").lower()
                    # Only paint from display facade ports (1:1 wire). Skip mesh dupes.
                    is_left = "left" in port_l or (
                        "audio" in port_l and "midi" not in port_l and "display" not in port_l
                    )
                    is_right = "right" in port_l or "graphics" in port_l
                    is_display = is_left or is_right or "display" in port_l
                    if not is_display:
                        # Control LEDs/jogs: facade ALSA bridge only — not libusb paint
                        return

                    if raw[0] != 0xF0:
                        return  # never short-MIDI to LCD bulk
                    if raw[-1:] != b"\xf7" or len(raw) < 6:
                        return

                    cmd = raw[4:6].hex()
                    is_numark = len(raw) >= 2 and raw[1] == 0x47
                    if allow_set and not is_numark and cmd not in allow_set:
                        return
                    now = time.perf_counter()
                    if cmd in metadata_cmds and not is_numark:
                        last = last_sent.get(cmd, 0.0)
                        if (now - last) < throttle_s:
                            return
                        last_sent[cmd] = now

                    # Route to ONE product only (writing both endpoints breaks wake).
                    # Prefer product bytes in the SysEx; else facade port side.
                    pids = None
                    if is_numark and len(raw) >= 4:
                        prod = (raw[2] << 8) | raw[3]
                        if prod in (PID_GRAPHICS, PID_AUDIO):
                            pids = [prod]
                    if pids is None:
                        pids = [PID_GRAPHICS] if is_right else [PID_AUDIO]

                    bulk = sysex_to_usb_midi(raw)
                    kind = "sysex_forwarded"
                    if is_numark and len(raw) > 32:
                        self._live_paint_until = time.perf_counter() + 2.0

                    self.pass_q.put((bulk, pids))
                    self.mark_activity()

                    # Human-readable live stream (tail -f captures/live-bridge.txt)
                    try:
                        live_path = ROOT / "captures/live-bridge.txt"
                        with live_path.open("a", encoding="utf-8") as lf:
                            hx = raw.hex()
                            if len(hx) > 96:
                                hx = hx[:96] + "…"
                            side = "R" if is_right else "L"
                            lf.write(
                                f"{time.strftime('%H:%M:%S')} {kind} {side} "
                                f"cmd={cmd or '-'} len={len(raw)} {hx}\n"
                            )
                    except Exception:
                        pass

                    if self._vdj_csv:
                        try:
                            meta_text = ""
                            if raw[0] == 0xF0:
                                import re

                                s = "".join(chr(x) if 32 <= x < 127 else "." for x in raw)
                                m = re.search(r"[A-Za-z0-9 \-_.]{4,64}", s)
                                meta_text = m.group(0) if m else ""
                            self._vdj_csv.write(
                                {
                                    "direction": "wine_to_nv",
                                    "source": port,
                                    "sink": "audio_bulk" if is_left else "graphics_bulk",
                                    "kind": kind,
                                    "sysex_cmd": cmd,
                                    "meta_text": meta_text,
                                    "payload_hex": raw,
                                }
                            )
                        except Exception:
                            pass

                self.patchbay.on_event = _on_event
                self.patchbay.on_midi = _on_midi
                self.patchbay.start_input_watch()
                print(f"[nv] VDJ/Wine input log → {vdj_csv_path}", flush=True)
            except Exception as e:
                print(f"[nv] patchbay unavailable: {e}", flush=True)
                self.patchbay = None

    def log_urb(self, source: str, pid: int, ep: int, pl: bytes, *, latency_ms: float = 0.0) -> None:
        if not self.csv:
            return
        self._csv_n += 1
        if self._csv_n % self._csv_every != 0:
            return
        self.csv.write(
            {
                "direction": "host_to_dev",
                "source": source,
                "sink": "graphics_bulk" if pid == PID_GRAPHICS else "audio_bulk",
                "product": f"{pid:04x}",
                "product_name": PRODUCT_NAMES.get(pid, ""),
                "ep": f"0x{ep:02x}",
                "urb_len": len(pl),
                "kind": "bulk_urb",
                "latency_ms": f"{latency_ms:.3f}" if latency_ms else "",
                "payload_hex": pl,
                "note": "sampled" if self._csv_every > 1 else "",
            }
        )

    def _play_action_list(
        self,
        actions: list[tuple[str, int, bytes]],
        *,
        reason: str,
        pace: float = 0.0,
    ) -> tuple[int, int]:
        ok = fail = 0
        print(
            f"[nv] LCD stream ({reason}): {len(actions)} actions",
            flush=True,
        )
        for kind, pid, payload in actions:
            if kind == "sysex":
                if self.painter.write_sysex(payload, pids=[pid], inter_chunk_s=0.0):
                    ok += 1
                else:
                    fail += 1
            else:
                if self.painter.write_record(pid, 0x03, payload):
                    ok += 1
                else:
                    fail += 1
            if pace:
                time.sleep(pace)
        return ok, fail

    def _play_wake_stream(self, *, reason: str, pace: float = 0.0) -> tuple[int, int]:
        """Play wake corpus: filtered actions, or raw URB records (full mode)."""
        actions = self.wake_actions
        if actions and self.wake_mode not in ("full", "all", "session"):
            return self._play_action_list(actions, reason=reason, pace=pace)

        recs = self.wake_records or self.bulk_records
        import os

        env_n = os.environ.get("NV_WAKE_BULK_URBS")
        n = min(len(recs), max(50, int(env_n))) if env_n is not None else len(recs)
        ok = fail = 0
        print(
            f"[nv] LCD bulk wake ({reason}): {n} exact capture URBs mode={self.wake_mode}",
            flush=True,
        )
        for pid, ep, pl in recs[:n]:
            if self.painter.write_record(pid, ep, pl):
                ok += 1
            else:
                fail += 1
            if pace:
                time.sleep(pace)
        return ok, fail

    def wake_lcds(self, *, reason: str = "start") -> None:
        """Open both LCDs without capture track UI (no After Burn tiles).

        chrome (default): dual open/splash + safe setup; strips deck tiles
        (0507/0509/0524/…) that painted the old WinBoat session.
        open/splash: 0506/0508/0530 only.
        """
        with self._wake_lock:
            if self._lcd_woken and reason != "force":
                print(f"[nv] LCD already woken — skip ({reason})", flush=True)
                return

            pace = float(getattr(self.args, "init_delay", 0.0) or 0.0)
            has_stream = bool(self.wake_actions or self.wake_records or self.bulk_records)

            if has_stream and not getattr(self.args, "sysex_only", False):
                t0 = time.perf_counter()
                ok, fail = self._play_wake_stream(reason=reason, pace=pace)
                self._lcd_woken = True
                print(
                    f"[nv] LCD wake done ok={ok} fail={fail} "
                    f"in {(time.perf_counter() - t0) * 1000:.0f}ms — live VDJ next",
                    flush=True,
                )
                return

            # Fallback: open SysEx only
            ok = fail = 0
            open_only = [
                m
                for m in self.init_msgs
                if len(m) >= 6 and m[4:6].hex() in ("0506", "0508", "0530")
            ] or self.init_msgs[:40]
            print(
                f"[nv] LCD sysex wake ({reason}): {len(open_only)} open messages",
                flush=True,
            )
            for m in open_only:
                if self.painter.write_sysex(m, inter_chunk_s=0.0):
                    ok += 1
                else:
                    fail += 1
                if pace:
                    time.sleep(pace)
            self._lcd_woken = True
            print(f"[nv] LCD sysex wake done ok={ok} fail={fail}", flush=True)

    def blank_lcds(self, *, reason: str = "shutdown") -> None:
        """Reset panels to open/splash (not capture chrome, not last track).

        Uses open_actions only (0506/0508/0530 + CC). Replaying chrome tiles
        was leaving "After Burn" / tempo on screen after VDJ quit.
        We do not have a full factory logo-restore capture yet; splash is best.
        """
        if not self.painter.handles:
            print(f"[nv] LCD blank ({reason}): no handles", flush=True)
            return
        if not self._wake_lock.acquire(blocking=False):
            print(f"[nv] LCD blank ({reason}): skip (wake in progress)", flush=True)
            return
        try:
            t0 = time.perf_counter()
            actions = self.open_actions or self.wake_actions
            if actions:
                ok, fail = self._play_action_list(
                    actions, reason=f"blank/splash:{reason}", pace=0.0
                )
                print(
                    f"[nv] LCD blank ({reason}): ok={ok} fail={fail} "
                    f"in {(time.perf_counter() - t0) * 1000:.0f}ms "
                    f"(open/splash only — not capture track UI)",
                    flush=True,
                )
            else:
                for m in (self.clear_msgs or [])[:40]:
                    try:
                        self.painter.write_sysex(m, inter_chunk_s=0.0)
                    except Exception:
                        break
                print(f"[nv] LCD blank ({reason}): clear SysEx fallback", flush=True)
        finally:
            self._wake_lock.release()

    def run_init(self) -> None:
        print("[nv] init sequence…", flush=True)
        self.wake_lcds(reason="hybrid-init")

    def paint_loop_bulk(self) -> None:
        """
        Dual-mode hot path:
          1) Any live SysEx from Wine (pass_q) wins immediately (drop-old).
          2) Otherwise replay bulk-long capture (proven LCD paint).
        """
        recs = self.bulk_records
        if not recs:
            self.paint_loop_sysex()
            return
        start = min(self.args.init_bulk_limit, len(recs))
        loop_recs = recs[start:] if start < len(recs) else recs
        if not loop_recs:
            loop_recs = recs

        # Prefer Graphics product records when graphics-only (Audio PID skipped anyway)
        if self.args.graphics_only:
            gfx = [r for r in loop_recs if r[0] == PID_GRAPHICS]
            if gfx:
                loop_recs = gfx

        print(
            f"[nv] hybrid paint: corpus={len(loop_recs)} URBs from {BULK_BIN.name} "
            f"+ live SysEx override; inter_urb={self.args.paint_delay*1000:.2f}ms",
            flush=True,
        )
        loop_n = 0
        last_stat = time.time()
        while not self.stop.is_set():
            # Live frames first (waveform latency / drop-old)
            pt = self.pass_q.get(timeout=0.0)
            if pt is not None:
                if isinstance(pt, tuple):
                    payload, pids = pt
                else:
                    payload, pids = pt, None
                self.painter.write_bulk(payload, pids=pids, inter_chunk_s=0.0)
                continue

            t_loop = time.perf_counter()
            for i, (pid, ep, pl) in enumerate(loop_recs):
                if self.stop.is_set():
                    break
                # Abandon stale capture loop if live SysEx arrives mid-frame
                if self.pass_q._q:
                    break
                t0 = time.perf_counter()
                self.painter.write_record(pid, ep, pl)
                self.log_urb("capture", pid, ep, pl, latency_ms=(time.perf_counter() - t0) * 1000)
                if self.args.paint_delay > 0:
                    time.sleep(self.args.paint_delay)
            loop_n += 1
            elapsed = time.perf_counter() - t_loop
            if time.time() - last_stat >= 5.0:
                print(
                    f"[nv] loops={loop_n} last_loop={elapsed*1000:.0f}ms "
                    f"{self.painter.stats.summary()} pass_dropped={self.pass_q.dropped}",
                    flush=True,
                )
                last_stat = time.time()

    def paint_loop_sysex(self) -> None:
        """
        Hot paint from assembled 0509/0505 SysEx (avoids replaying capture
        teardown / short MIDI that can flash the NV logo between loops).
        """
        paint = self.paint_msgs or []
        status = self.status_msgs or []
        if not paint and not status:
            print("[nv] no paint corpus — idle (pass-through only)", flush=True)
            while not self.stop.is_set():
                pt = self.pass_q.get(timeout=0.2)
                if pt is not None:
                    if isinstance(pt, tuple):
                        payload, pids = pt
                    else:
                        payload, pids = pt, None
                    self.painter.write_bulk(payload, pids=pids, inter_chunk_s=0.0)
            return

        # Default: push as fast as USB allows (hz only paces if > 0 via paint_delay)
        hz = max(self.args.paint_hz, 0.0)
        period = (1.0 / hz) if hz > 0 else 0.0
        # Delay capture reel so startup isn't stuck on old WinBoat frames;
        # live VDJ F0 47 should arrive first after factory displays bind.
        capture_grace_s = float(
            __import__("os").environ.get("NV_CAPTURE_GRACE_S", "12")
        )
        capture_start = time.perf_counter() + max(0.0, capture_grace_s)
        print(
            f"[nv] sysex HOT paint: paint_frames={len(paint)} status={len(status)} "
            f"(capture grace {capture_grace_s:.0f}s — prefer live F0 47)",
            flush=True,
        )
        pi = si = 0
        last_stat = time.time()
        while not self.stop.is_set():
            t0 = time.perf_counter()
            pt = self.pass_q.get(timeout=0.0)
            # After VDJ closed, stop capture paint (hold last frame) until auto-exit
            if (
                self._vdj_seen_once
                and not self._vdj_running
                and self._vdj_gone_since is not None
            ):
                self.stop.wait(0.5)
                continue

            if pt is not None:
                if isinstance(pt, tuple):
                    payload, pids = pt
                else:
                    payload, pids = pt, None
                self.painter.write_bulk(payload, pids=pids, inter_chunk_s=0.0)
                self.mark_activity()
            elif time.perf_counter() < getattr(self, "_live_paint_until", 0.0):
                # Live F0 47 from factory displays — do not overlay capture reel
                self.stop.wait(0.01)
            elif time.perf_counter() < capture_start:
                # Wait for VDJ factory paint before falling back to capture
                self.stop.wait(0.05)
            else:
                # denser paint: several tiles then a status tick (fallback only)
                if paint:
                    for _ in range(3):
                        m = paint[pi % len(paint)]
                        pi += 1
                        self.painter.write_sysex(m, inter_chunk_s=0.0)
                        if self.pass_q._q:
                            break
                if status and (pi % 6 == 0):
                    m = status[si % len(status)]
                    si += 1
                    self.painter.write_sysex(m, inter_chunk_s=0.0)
            spent = time.perf_counter() - t0
            if period > 0:
                sleep_for = period - spent
                if sleep_for > 0:
                    self.stop.wait(sleep_for)
            if time.time() - last_stat >= 5.0:
                print(
                    f"[nv] {self.painter.stats.summary()} pass_dropped={self.pass_q.dropped} "
                    f"frame_i={pi}",
                    flush=True,
                )
                last_stat = time.time()

    def live_loop(self) -> None:
        print(
            "[nv] LIVE BRIDGE ONLY — Wine → USB-MIDI cells → libusb dual bulk",
            flush=True,
        )
        print("[nv] NO capture/test paint — LCD content is VDJ only", flush=True)
        last_stat = time.time()
        while not self.stop.is_set():
            # Batch-drain queue (ordered) for smoother multi-packet frames
            batch = self.pass_q.drain(max_n=48)
            if not batch:
                pt = self.pass_q.get(timeout=0.05)
                if pt is not None:
                    batch = [pt]
            for item in batch:
                if isinstance(item, tuple):
                    payload, pids = item
                else:
                    payload, pids = item, None
                self.painter.write_bulk(payload, pids=pids, inter_chunk_s=0.0)
                self.mark_activity()
            if time.time() - last_stat >= 5.0:
                print(
                    f"[nv] bridge {self.painter.stats.summary()} "
                    f"pass_dropped={self.pass_q.dropped} "
                    f"vdj={'up' if self._vdj_running else 'down'}",
                    flush=True,
                )
                last_stat = time.time()

    def start_pass_through_listener(self) -> None:
        port = self.args.pass_through_port
        if not port:
            return

        def worker() -> None:
            import subprocess

            print(f"[nv] pass-through listening on {port}", flush=True)
            proc = subprocess.Popen(
                ["amidi", "-p", port, "-d"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            buf = bytearray()
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    if self.stop.is_set():
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = bytes.fromhex(line.replace(" ", ""))
                    except ValueError:
                        continue
                    for b in chunk:
                        if b == 0xF0:
                            buf = bytearray([0xF0])
                        elif buf:
                            buf.append(b)
                            if b == 0xF7:
                                msg = bytes(buf)
                                buf.clear()
                                self.pass_q.put((sysex_to_usb_midi(msg), None))
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    proc.kill()

        self._pt_thread = threading.Thread(target=worker, name="nv-pass", daemon=True)
        self._pt_thread.start()

    def start_vdj_monitor(self) -> None:
        if self._vdj_monitor and self._vdj_monitor.is_alive():
            return

        # Exit promptly so facade leaves the patchbay when VDJ quits
        idle_after = float(getattr(self.args, "idle_after_vdj_s", 3.0))

        def monitor() -> None:
            print(
                f"[nv] VDJ monitor started "
                f"(auto-exit {idle_after:.0f}s after VDJ closes if idle)",
                flush=True,
            )
            while not self.stop.is_set():
                running = vdj_running()
                now = time.time()

                if running and not self._vdj_running:
                    print("[nv] VirtualDJ started", flush=True)
                    self._vdj_seen_once = True
                    self._vdj_gone_since = None
                    self.mark_activity()

                    def _on_start() -> None:
                        try:
                            time.sleep(self.args.settle)
                            if not self.painter.handles:
                                try:
                                    self.painter.open()
                                except Exception as e:
                                    print(f"[nv] claim on start failed: {e}", flush=True)
                                    return
                            # Bulk wake then live bridge (live-only never loops capture)
                            try:
                                self.wake_lcds(reason="vdj-start")
                            except Exception as e:
                                print(f"[nv] wake_lcds error: {e}", flush=True)
                            if getattr(self.args, "live_only", False):
                                print(
                                    "[nv] live-only: bulk wake done — VDJ paint on facade",
                                    flush=True,
                                )
                                return
                        except Exception as e:
                            print(f"[nv] on_start worker error: {e}", flush=True)

                    threading.Thread(target=_on_start, name="vdj-start", daemon=True).start()

                elif not running and self._vdj_running:
                    # Transition: VDJ just closed — blank panels, then exit soon
                    print("[nv] VirtualDJ stopped", flush=True)
                    self._vdj_gone_since = now
                    try:
                        self.blank_lcds(reason="vdj-stop")
                    except Exception as e:
                        print(f"[nv] blank on VDJ stop failed: {e}", flush=True)
                    print(
                        f"[nv] paint stopped; blank sent; exit in {idle_after:.0f}s "
                        f"if VDJ stays closed (facade leaves patchbay)",
                        flush=True,
                    )

                elif not running and self._vdj_seen_once and self._vdj_gone_since is not None:
                    gone_for = now - self._vdj_gone_since
                    idle_for = now - self._last_activity
                    # Exit when VDJ has been gone long enough
                    if gone_for >= idle_after:
                        self._exit_reason = (
                            f"vdj_closed_{gone_for:.0f}s "
                            f"(idle_bridge={idle_for:.0f}s)"
                        )
                        print(
                            f"[nv] VDJ closed for {gone_for:.0f}s — "
                            f"shutting down nv-screens ({self._exit_reason})",
                            flush=True,
                        )
                        self.stop.set()
                        break

                elif running:
                    self._vdj_gone_since = None

                self._vdj_running = running
                time.sleep(1.0)

        self._vdj_monitor = threading.Thread(target=monitor, name="vdj-monitor", daemon=True)
        self._vdj_monitor.start()

    def run(self) -> int:
        self.setup()
        if self.args.live_only:
            print(
                "[nv] mode=live-only (Wine→nv-screens→libusb; NO capture paint)",
                flush=True,
            )
        elif not self.args.no_wait:
            wait_for_vdj(timeout_s=self.args.wait_timeout)
            if self.stop.is_set():
                return 0
        else:
            print("[nv] --no-wait: claim Graphics immediately", flush=True)

        if self.args.settle > 0:
            time.sleep(self.args.settle)

        self.start_pass_through_listener()
        self.start_vdj_monitor()
        # Claim Graphics before Wine opens MIDI so ALSA Graphics is gone
        if self.args.no_wait or self.args.live_only:
            try:
                self.painter.open()
            except Exception as e:
                print(f"[nv] claim failed: {e}", file=sys.stderr)
                return 1
            # Immediate bulk wake so panels leave logo before live SysEx
            if self.args.live_only:
                try:
                    self.wake_lcds(reason="claim")
                except Exception as e:
                    print(f"[nv] wake after claim failed: {e}", flush=True)
        try:
            if self.args.live_only:
                self.live_loop()
            else:
                self.run_init()
                if self.args.full_bulk_loop and self.bulk_records and not self.args.sysex_only:
                    self.paint_loop_bulk()
                else:
                    self.paint_loop_sysex()
        except KeyboardInterrupt:
            print("\n[nv] stop requested", flush=True)
        finally:
            self.stop.set()
            reason = self._exit_reason or "stop"
            # Blank once more if VDJ had run (desktop icon may SIGTERM us)
            if self._vdj_seen_once and self.painter.handles:
                try:
                    self.blank_lcds(reason=f"exit:{reason}")
                except Exception as e:
                    print(f"[nv] blank on exit failed: {e}", flush=True)
            print(
                f"[nv] releasing. reason={reason} {self.painter.stats.summary()}",
                flush=True,
            )
            if self.csv:
                self.csv.close()
                print(f"[nv] CSV closed → {self.args.csv_log}", flush=True)
            if getattr(self, "_vdj_csv", None):
                self._vdj_csv.close()
                print("[nv] VDJ input CSV closed", flush=True)
            if self.patchbay:
                print(f"[nv] {self.patchbay.status_line()}", flush=True)
                self.patchbay.close()
            # Prefer reattach so NV Graphics returns to ALSA after VDJ session
            try:
                self.painter.close(reattach=not self.args.keep_claimed)
            except Exception as e:
                print(f"[nv] close note: {e}", flush=True)
            print("[nv] exited cleanly (facade gone)", flush=True)
        return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Low-latency NV dual-screen host for VDJ under Wine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for VirtualDJ process",
    )
    ap.add_argument(
        "--wait-timeout",
        type=float,
        default=0.0,
        help="Seconds to wait for VDJ (0=forever)",
    )
    ap.add_argument(
        "--settle",
        type=float,
        default=0.4,
        help="Seconds after VDJ detect before claiming bulk (let Wine open Control)",
    )
    ap.add_argument(
        "--idle-after-vdj-s",
        type=float,
        default=2.0,
        help="After VirtualDJ stops, exit nv-screens after this many seconds "
        "(default 2 — removes facade from patchbay quickly). "
        "0 = never auto-exit on VDJ close.",
    )
    ap.add_argument(
        "--wake-mode",
        choices=("open", "chrome", "full"),
        default=None,
        help="LCD wake: open=init only, chrome=blank UI no capture titles (default), "
        "full=entire bulk-out (old track flash). Env NV_WAKE_MODE overrides if unset.",
    )
    ap.add_argument(
        "--graphics-only",
        action="store_true",
        help="Claim Graphics MIDI bulk only — leave NV Audio fully to ALSA/VDJ",
    )
    ap.add_argument(
        "--sysex-only",
        action="store_true",
        help="Use SysEx→cells paint instead of raw bulk capture replay",
    )
    ap.add_argument(
        "--live-only",
        action="store_true",
        help="Only forward inbound Wine SysEx (no capture replay). "
        "Default hybrid = SysEx 0509/0505 hot paint + live override.",
    )
    ap.add_argument(
        "--full-bulk-loop",
        action="store_true",
        help="Loop entire bulk-long.bin (can flash logo on capture teardown segments)",
    )
    ap.add_argument(
        "--init-bulk-limit",
        type=int,
        default=800,
        help="How many bulk URBs from capture to treat as init before loop",
    )
    ap.add_argument(
        "--init-delay",
        type=float,
        default=0.0003,
        help="Pace between init URBs (s); paint path uses --paint-delay",
    )
    ap.add_argument(
        "--paint-delay",
        type=float,
        default=0.0,
        help="Delay between paint URBs (s). Default 0 = lowest latency",
    )
    ap.add_argument(
        "--paint-hz",
        type=float,
        default=30.0,
        help="Target frame rate for sysex-only mode (default 30)",
    )
    ap.add_argument(
        "--write-timeout-ms",
        type=int,
        default=500,
        help="libusb bulk write timeout (ms) — keep low to avoid stuck queues",
    )
    ap.add_argument(
        "--pass-through-port",
        default="",
        help="Optional amidi port to listen for SysEx and bulk-forward (e.g. hw:5,0)",
    )
    ap.add_argument(
        "--csv-log",
        default="",
        help="Append live paint traffic to this CSV (e.g. captures/live.csv)",
    )
    ap.add_argument(
        "--csv-every",
        type=int,
        default=10,
        help="Log every Nth URB to CSV (default 10; use 1 for full detail — larger files)",
    )
    ap.add_argument(
        "--csv-max-hex",
        type=int,
        default=128,
        help="Max hex chars of payload stored per CSV row",
    )
    ap.add_argument(
        "--patchbay",
        action="store_true",
        help="Expose ALSA seq ports (nv-screens) for aconnect / qpwgraph routing",
    )
    ap.add_argument(
        "--no-virtual-graphics",
        action="store_true",
        help="Do not create virtual 'NV Graphics' ALSA client (default: create it "
        "with --patchbay so VDJ sees Graphics while real OUT is libusb)",
    )
    ap.add_argument(
        "--no-display-ports",
        action="store_true",
        help="With virtual Graphics, only create Numark NV Display Left "
        "(skip Display Right)",
    )
    ap.add_argument(
        "--routes",
        default="",
        help="Optional routes JSON (from nv_patchbay.py --save-routes)",
    )
    ap.add_argument(
        "--vdj-csv",
        default="",
        help="CSV for Wine→vdj_in events (default captures/vdj-from-wine.csv)",
    )
    ap.add_argument(
        "--allow-sysex",
        default="0509,0531,0505",
        help="Comma-separated SysEx command hex codes to forward (e.g. 0509,0531)",
    )
    ap.add_argument(
        "--metadata-throttle-ms",
        type=int,
        default=150,
        help="Minimum ms between forwarded metadata SysEx messages per command (default 150)",
    )
    ap.add_argument(
        "--keep-claimed",
        action="store_true",
        help="Do not reattach kernel drivers on exit",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    daemon = NvScreensDaemon(args)

    def _sig(_signum, _frame):
        daemon.stop.set()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)
    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
