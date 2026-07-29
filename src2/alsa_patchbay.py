"""
Minimal ALSA sequencer client for nv-screens — shows up in `aconnect -l`
and in qpwgraph (MIDI / ALSA view) for drag-route style wiring.

Ports (application client name: "nv-screens"):
  0  vdj_in        WRITE only — Wine outs connect HERE (we receive)
  1  inject_in     WRITE only — optional tools

NV driver facade (separate ALSA client, default on):
  client "nv-screens-facade"  (long → Wine uses port-only names)
  ports  "NV Audio" / "NV Graphics"  (= Windows drivernames)

  WinBoat: NV Audio → factory Display Left; NV Graphics → Display Right.
  Real USB MIDI OUT stays libusb bulk; identity probes get product replies.

NO monitor_out / log_out — those READ ports were auto-wired into
WINE ALSA Input by PipeWire/qpwgraph and created a feedback mess.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import select
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ---- libasound thin binding -------------------------------------------------

_libname = ctypes.util.find_library("asound")
if not _libname:
    raise ImportError("libasound not found")
_asound = ctypes.CDLL(_libname)

SND_SEQ_OPEN_DUPLEX = 3
SND_SEQ_NONBLOCK = 1
SND_SEQ_PORT_CAP_READ = 1 << 0
SND_SEQ_PORT_CAP_WRITE = 1 << 1
SND_SEQ_PORT_CAP_SUBS_READ = 1 << 5
SND_SEQ_PORT_CAP_SUBS_WRITE = 1 << 6
SND_SEQ_PORT_TYPE_MIDI_GENERIC = 1 << 1
SND_SEQ_PORT_TYPE_APPLICATION = 1 << 20
SND_SEQ_PORT_TYPE_PORT = 1 << 16
SND_SEQ_PORT_TYPE_HARDWARE = 1 << 16  # not always set; PORT is fine

# event types (alsa/seq_event.h)
SND_SEQ_EVENT_NOTEON = 6
SND_SEQ_EVENT_NOTEOFF = 7
SND_SEQ_EVENT_KEYPRESS = 8
SND_SEQ_EVENT_CONTROLLER = 10
SND_SEQ_EVENT_PGMCHANGE = 11
SND_SEQ_EVENT_CHANPRESS = 12
SND_SEQ_EVENT_PITCHBEND = 13
SND_SEQ_EVENT_SYSEX = 130
SND_SEQ_EVENT_SENSING = 46  # often ignore

# event flags / addresses (x86_64 layout: sizeof snd_seq_event_t = 28)
SND_SEQ_EVENT_LENGTH_VARIABLE = 1 << 2
SND_SEQ_ADDRESS_SUBSCRIBERS = 254
SND_SEQ_ADDRESS_UNKNOWN = 255
SND_SEQ_QUEUE_DIRECT = 253

POLLIN = 0x0001

# Identity replies (universal non-realtime). Product field matches USB product
# family used in factory defs (…0206xx / 030600…). WinBoat + successful Wine
# sessions map:
#   15e4:1005 NV Control  → Numark NV          (needs serial in identity)
#   15e4:1033 NV Audio    → NV Display Left
#   15e4:2033 NV Graphics → NV Display Right
#
# Control serial captured from working Wine Log Report:
#   Identified by Sysex: … Numark NV
#   F0 7E 00 06 02 … 03 06 00 … "N11412876110298"
ID_CONTROL = bytes.fromhex(
    "f07e00060200013f3300190000030600"
    "7f7f7f7f"
    "4e313134313238373631313032393800"  # N11412876110298\0
    "f7"
)
ID_GRAPHICS = bytes.fromhex(
    "f07e00060200013f3300190000020620"
    "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7ff7"
)
ID_AUDIO = bytes.fromhex(
    "f07e00060200013f3300190000020610"
    "7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7f7ff7"
)
# Back-compat alias
ID_AUDIO_LIKE = ID_AUDIO


# ---- snd_seq_event_t (x86_64: 28 bytes) for identity replies ----
class _SndSeqAddr(ctypes.Structure):
    _fields_ = [("client", ctypes.c_ubyte), ("port", ctypes.c_ubyte)]


class _SndSeqRealTime(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_uint), ("tv_nsec", ctypes.c_uint)]


class _SndSeqTimestamp(ctypes.Union):
    _fields_ = [("tick", ctypes.c_uint), ("time", _SndSeqRealTime)]


class _SndSeqEvExt(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("len", ctypes.c_uint), ("ptr", ctypes.c_void_p)]


class _SndSeqEventData(ctypes.Union):
    # Largest legacy member is 12 bytes (raw8 / queue param); ext is packed 12.
    _fields_ = [
        ("raw8", ctypes.c_ubyte * 12),
        ("ext", _SndSeqEvExt),
    ]


class _SndSeqEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ubyte),
        ("flags", ctypes.c_ubyte),
        ("tag", ctypes.c_ubyte),
        ("queue", ctypes.c_ubyte),
        ("time", _SndSeqTimestamp),
        ("source", _SndSeqAddr),
        ("dest", _SndSeqAddr),
        ("data", _SndSeqEventData),
    ]


assert ctypes.sizeof(_SndSeqEvent) == 28, ctypes.sizeof(_SndSeqEvent)

_asound.snd_seq_open.argtypes = [
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_char_p,
    ctypes.c_int,
    ctypes.c_int,
]
_asound.snd_seq_open.restype = ctypes.c_int
_asound.snd_seq_close.argtypes = [ctypes.c_void_p]
_asound.snd_seq_set_client_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
_asound.snd_seq_create_simple_port.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_uint,
    ctypes.c_uint,
]
_asound.snd_seq_create_simple_port.restype = ctypes.c_int
_asound.snd_seq_client_id.argtypes = [ctypes.c_void_p]
_asound.snd_seq_client_id.restype = ctypes.c_int
_asound.snd_seq_event_input.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_void_p),
]
_asound.snd_seq_event_input.restype = ctypes.c_int
_asound.snd_seq_free_event.argtypes = [ctypes.c_void_p]
_asound.snd_seq_poll_descriptors_count.argtypes = [ctypes.c_void_p, ctypes.c_short]
_asound.snd_seq_poll_descriptors_count.restype = ctypes.c_int
_asound.snd_seq_poll_descriptors.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_short,
]
_asound.snd_seq_poll_descriptors.restype = ctypes.c_int
_asound.snd_seq_event_output.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_asound.snd_seq_event_output.restype = ctypes.c_int
_asound.snd_seq_event_output_direct.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_asound.snd_seq_event_output_direct.restype = ctypes.c_int
_asound.snd_seq_drain_output.argtypes = [ctypes.c_void_p]
_asound.snd_seq_drain_output.restype = ctypes.c_int
_asound.snd_seq_connect_from.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
_asound.snd_seq_connect_from.restype = ctypes.c_int
_asound.snd_seq_connect_to.argtypes = [
    ctypes.c_void_p,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
_asound.snd_seq_connect_to.restype = ctypes.c_int

# midi event decoder: seq event → raw MIDI bytes
_asound.snd_midi_event_new.argtypes = [ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)]
_asound.snd_midi_event_new.restype = ctypes.c_int
_asound.snd_midi_event_free.argtypes = [ctypes.c_void_p]
_asound.snd_midi_event_decode.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_ubyte),
    ctypes.c_long,
    ctypes.c_void_p,
]
_asound.snd_midi_event_decode.restype = ctypes.c_long
_asound.snd_midi_event_reset_decode.argtypes = [ctypes.c_void_p]
_asound.snd_midi_event_no_status.argtypes = [ctypes.c_void_p, ctypes.c_int]


@dataclass
class PortSpec:
    name: str
    caps: int
    type: int = SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION
    identity: bytes | None = None  # reply payload if this port is probed


# WRITE-only ports: destinations for Wine. Do NOT create READ/subs-read ports
# on the nv-screens client or PipeWire will auto-link them into WINE ALSA Input.
DEFAULT_PORTS = [
    PortSpec(
        "vdj_in",
        SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
    ),
    PortSpec(
        "inject_in",
        SND_SEQ_PORT_CAP_WRITE | SND_SEQ_PORT_CAP_SUBS_WRITE,
    ),
    # Intentionally NO monitor_out / log_out (READ ports auto-wire into Wine)
]

# WinBoat ground truth (Log Report + Controllers UI):
#   OS drivername   VID:PID   → factory title after identify
#   NV Control      15e4:1005 → Numark NV          (keep real kernel)
#   NV Audio        15e4:1033 → NV Display Left
#   NV Graphics     15e4:2033 → NV Display Right
#
# Windows identifies displays primarily by USB PID/VID path. Wine's winealsa
# never attaches USB paths to MIDI (hardcodes wMid=0xFF wPid=0x0001). Fallback
# is "Identified by name" / Sysex — so facade port names MUST match Windows
# drivernames exactly: "NV Audio" / "NV Graphics" (not "… MIDI 1").
#
# Custom Devices/*.xml SHADOW factory controllers.dat — do not install display
# stubs. Audio button may use Numark_NV_Audio.xml (PCM only).
#
# winealsa: "client - port" if len < 32 else port name only.
# Client name long enough that szPname becomes the port name alone.
# winealsa uses "client - port" when (len(client)+len(port)+3) < 32.
# Shortest port "NV Audio" is 8 chars → need len(client) >= 21 for port-only.
FACADE_CLIENT_NAME = "nv-screens-facade-midi"  # 21 chars → Wine szPname = port only
_FACADE_CAPS = (
    SND_SEQ_PORT_CAP_READ
    | SND_SEQ_PORT_CAP_WRITE
    | SND_SEQ_PORT_CAP_SUBS_READ
    | SND_SEQ_PORT_CAP_SUBS_WRITE
)
_FACADE_TYPE = (
    SND_SEQ_PORT_TYPE_MIDI_GENERIC
    | SND_SEQ_PORT_TYPE_PORT
    | SND_SEQ_PORT_TYPE_APPLICATION
)

# Name modes (NV_FACADE_NAME_MODE):
#   factory (default) — port names = factory Controllers titles so
#     "Identified by name" can hit controllers.dat:
#       NV Control / NV Display Left / NV Display Right
#   windows — OS product strings NV Control / NV Audio / NV Graphics
#   vidpid  — embed vid_15e4&pid_XXXX for path-style PID/VID parse
def _facade_port_specs() -> list[PortSpec]:
    mode = __import__("os").environ.get("NV_FACADE_NAME_MODE", "factory").strip().lower()
    if mode in ("vidpid", "vid_pid", "pidvid"):
        ctl_name = "vid_15e4&pid_1005"
        left_name = "vid_15e4&pid_1033"
        right_name = "vid_15e4&pid_2033"
    elif mode in ("windows", "os", "product"):
        ctl_name = "NV Control"
        left_name = "NV Audio"
        right_name = "NV Graphics"
    else:
        # factory / display / default
        ctl_name = "NV Control"
        left_name = "NV Display Left"
        right_name = "NV Display Right"
    # Identities: Control needs serial. Displays use product family bytes.
    # Successful Wine session once matched 020610 → Display Right; WinBoat PID
    # maps 1033→Left / 2033→Right. Paint bulk routes by F0 47 product field.
    return [
        PortSpec(ctl_name, _FACADE_CAPS, _FACADE_TYPE, identity=ID_CONTROL),
        PortSpec(left_name, _FACADE_CAPS, _FACADE_TYPE, identity=ID_AUDIO),
        PortSpec(right_name, _FACADE_CAPS, _FACADE_TYPE, identity=ID_GRAPHICS),
    ]


GRAPHICS_FACADE_PORTS = _facade_port_specs()


@dataclass
class RouteTable:
    edges: list[tuple[str, str]] = field(
        default_factory=lambda: [
            ("wine_vdj", "graphics_bulk"),
            ("wine_vdj", "csv"),
            ("capture", "graphics_bulk"),
            ("capture", "csv"),
            ("inject", "graphics_bulk"),
            ("inject", "csv"),
        ]
    )

    def connects(self, source: str, sink: str) -> bool:
        return (source, sink) in self.edges

    def sinks_for(self, source: str) -> list[str]:
        return [s for src, s in self.edges if src == source]

    def to_dict(self) -> dict:
        return {"edges": [{"from": a, "to": b} for a, b in self.edges]}

    @classmethod
    def from_dict(cls, d: dict) -> "RouteTable":
        edges = []
        for e in d.get("edges", []):
            edges.append((e["from"], e["to"]))
        return cls(edges=edges or RouteTable().edges)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "RouteTable":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def ascii_graph(routes: RouteTable, *, live: dict[str, str] | None = None) -> str:
    live = live or {}
    lines = [
        "nv-screens patchbay (logical routes)",
        "====================================",
        "",
    ]
    for src in sorted({a for a, _ in routes.edges}):
        sinks = routes.sinks_for(src)
        tag = live.get(src, "")
        src_l = f"[{src}]{(' ' + tag) if tag else ''}"
        if not sinks:
            lines.append(f"  {src_l}")
            continue
        for i, snk in enumerate(sinks):
            st = live.get(snk, "")
            snk_l = f"[{snk}]{(' ' + st) if st else ''}"
            if i == 0:
                lines.append(f"  {src_l} ──► {snk_l}")
            else:
                pad = " " * (len(src_l) + 2)
                lines.append(f"  {pad}└──► {snk_l}")
    lines.append("")
    lines.append("ALSA ports:")
    lines.append("  nv-screens:vdj_in          ← Wine outs (bridge sink)")
    lines.append("  nv-screens:inject_in       ← optional tools")
    lines.append(
        "  nv-screens-facade-midi: NV Control / NV Audio / NV Graphics "
        "← Windows drivernames (factory Numark NV + Display L/R)"
    )
    lines.append("")
    lines.append(
        "Real LCD paint = libusb bulk only. Kernel NV Graphics is claimed "
        "and hidden; the user client is a facade so VDJ still opens Graphics OUT."
    )
    return "\n".join(lines)


class _SeqClient:
    """One ALSA seq handle with named ports and an input pump."""

    def __init__(self, client_name: str) -> None:
        self.client_name = client_name
        self._seq = ctypes.c_void_p()
        self.client_id: int | None = None
        self.ports: dict[str, int] = {}
        self.port_identity: dict[int, bytes] = {}  # port id → identity sysex
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.on_midi: Callable[[str, bytes], None] | None = None
        self.on_event: Callable[[dict], None] | None = None
        self.stats = {
            "events": 0,
            "sysex": 0,
            "cc": 0,
            "note": 0,
            "other": 0,
            "bytes": 0,
            "id_req": 0,
            "id_reply": 0,
        }
        # Keep identity payload buffers alive while ALSA drains output
        self._id_bufs: dict[int, ctypes.Array] = {}

    def open(self, specs: list[PortSpec]) -> None:
        err = _asound.snd_seq_open(
            ctypes.byref(self._seq), b"default", SND_SEQ_OPEN_DUPLEX, 0
        )
        if err < 0:
            raise OSError(f"snd_seq_open failed: {err}")
        _asound.snd_seq_set_client_name(self._seq, self.client_name.encode())
        self.client_id = int(_asound.snd_seq_client_id(self._seq))
        for spec in specs:
            pid = _asound.snd_seq_create_simple_port(
                self._seq,
                spec.name.encode(),
                spec.caps,
                spec.type,
            )
            if pid < 0:
                raise OSError(f"create port {spec.name} failed: {pid}")
            self.ports[spec.name] = pid
            if spec.identity:
                self.port_identity[pid] = spec.identity
                # pin buffer for possible replies
                buf = (ctypes.c_ubyte * len(spec.identity)).from_buffer_copy(spec.identity)
                self._id_bufs[pid] = buf
        print(
            f"[patchbay] ALSA client '{self.client_name}' id={self.client_id} "
            f"ports={self.ports}",
            flush=True,
        )

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        if self._seq:
            _asound.snd_seq_close(self._seq)
            self._seq = ctypes.c_void_p()

    def start_input_watch(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._pump, name=f"nv-pb-{self.client_name}", daemon=True
        )
        self._thread.start()

    def _dest_port(self, ev_ptr: ctypes.c_void_p) -> int | None:
        """Read dest.port from raw snd_seq_event_t (offset 15)."""
        try:
            # ev_ptr is pointer to event; cast to byte array of 28
            base = ctypes.cast(ev_ptr, ctypes.POINTER(ctypes.c_ubyte))
            return int(base[15])
        except Exception:
            return None

    def _source_client(self, ev_ptr: ctypes.c_void_p) -> int | None:
        try:
            base = ctypes.cast(ev_ptr, ctypes.POINTER(ctypes.c_ubyte))
            return int(base[12])
        except Exception:
            return None

    def bridge_kernel_control(self, control_port_name: str = "NV Control") -> bool:
        """Bidirectional ALSA link: facade Control ↔ kernel NV Control MIDI."""
        import subprocess

        port_id = self.ports.get(control_port_name)
        # vidpid mode uses different port name
        if port_id is None:
            for n, p in self.ports.items():
                if "Control" in n or "1005" in n:
                    port_id = p
                    control_port_name = n
                    break
        if port_id is None or self.client_id is None:
            return False
        # find kernel client id for NV Control
        out = subprocess.check_output(["aconnect", "-l"], text=True)
        kern_id = None
        cur = None
        for line in out.splitlines():
            if line.startswith("client "):
                # client 24: 'NV Control' [type=kernel,card=2]
                parts = line.split()
                try:
                    cur = int(parts[1].rstrip(":"))
                except Exception:
                    cur = None
                if "NV Control" in line and "type=kernel" in line:
                    kern_id = cur
                    break
        if kern_id is None:
            print("[patchbay] kernel NV Control not found — Control bridge skipped", flush=True)
            return False
        self._ctl_kern_client = kern_id
        self._ctl_port_id = port_id
        # receive hardware → our port; send our port → hardware
        e1 = _asound.snd_seq_connect_from(self._seq, port_id, kern_id, 0)
        e2 = _asound.snd_seq_connect_to(self._seq, port_id, kern_id, 0)
        print(
            f"[patchbay] Control bridge facade:{control_port_name!r}({port_id}) "
            f"↔ kernel {kern_id}:0 (from={e1} to={e2})",
            flush=True,
        )
        return e1 >= 0 or e2 >= 0

    def _emit_sysex_to_subscribers(self, port_id: int, payload: bytes) -> None:
        """Rebroadcast SysEx (e.g. from hardware) to Wine subscribers."""
        if not self._seq or not payload:
            return
        key = f"emit-{port_id}-{len(payload)}-{id(payload)}"
        buf = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
        self._id_bufs[key] = buf  # pin
        ev = _SndSeqEvent()
        ev.type = SND_SEQ_EVENT_SYSEX
        ev.flags = SND_SEQ_EVENT_LENGTH_VARIABLE
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.source.port = port_id & 0xFF
        ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
        ev.dest.port = SND_SEQ_ADDRESS_UNKNOWN
        ev.data.ext.len = len(payload)
        ev.data.ext.ptr = ctypes.cast(buf, ctypes.c_void_p)
        err = _asound.snd_seq_event_output_direct(self._seq, ctypes.byref(ev))
        if err < 0:
            _asound.snd_seq_event_output(self._seq, ctypes.byref(ev))
            _asound.snd_seq_drain_output(self._seq)

    def _emit_raw_to_subscribers(self, port_id: int, raw: bytes) -> None:
        """Rebroadcast short MIDI from hardware as if sourced from facade port.

        Wine opens Numark NV on the *facade* ALSA address only. Kernel Control
        events must be re-emitted with source=facade or jogs/pads never reach VDJ.
        """
        if not self._seq or not raw:
            return
        if raw[0] == 0xF0:
            self._emit_sysex_to_subscribers(port_id, raw)
            return
        midi_ev = ctypes.c_void_p()
        if _asound.snd_midi_event_new(256, ctypes.byref(midi_ev)) < 0:
            return
        try:
            if not hasattr(_asound, "snd_midi_event_encode"):
                _asound.snd_midi_event_encode.argtypes = [
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_ubyte),
                    ctypes.c_long,
                    ctypes.c_void_p,
                ]
                _asound.snd_midi_event_encode.restype = ctypes.c_long
            _asound.snd_midi_event_no_status(midi_ev, 1)
            buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            ev = _SndSeqEvent()
            n = _asound.snd_midi_event_encode(
                midi_ev, buf, len(raw), ctypes.byref(ev)
            )
            if n <= 0:
                return
            ev.queue = SND_SEQ_QUEUE_DIRECT
            ev.source.port = port_id & 0xFF
            ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
            ev.dest.port = SND_SEQ_ADDRESS_UNKNOWN
            _asound.snd_seq_event_output_direct(self._seq, ctypes.byref(ev))
        finally:
            _asound.snd_midi_event_free(midi_ev)

    def _forward_raw_to_kernel_control(self, port_id: int, raw: bytes) -> None:
        """Send MIDI bytes to kernel NV Control (Wine → hardware)."""
        kern = getattr(self, "_ctl_kern_client", None)
        if kern is None or not self._seq or not raw:
            return
        # SysEx path
        if raw[0] == 0xF0:
            buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            self._id_bufs[f"fwd-{id(buf)}"] = buf
            ev = _SndSeqEvent()
            ev.type = SND_SEQ_EVENT_SYSEX
            ev.flags = SND_SEQ_EVENT_LENGTH_VARIABLE
            ev.queue = SND_SEQ_QUEUE_DIRECT
            ev.source.port = port_id & 0xFF
            ev.dest.client = kern & 0xFF
            ev.dest.port = 0
            ev.data.ext.len = len(raw)
            ev.data.ext.ptr = ctypes.cast(buf, ctypes.c_void_p)
            _asound.snd_seq_event_output_direct(self._seq, ctypes.byref(ev))
            return
        # Short MIDI: use midi encoder
        midi_ev = ctypes.c_void_p()
        if _asound.snd_midi_event_new(256, ctypes.byref(midi_ev)) < 0:
            return
        try:
            _asound.snd_midi_event_no_status(midi_ev, 1)
            # encode_byte is available via encode if we bind it — fallback: wrap as sysex-less direct
            # Use variable raw by stuffing into SYSEX-like isn't valid.
            # Bind encode if present
            if not hasattr(_asound, "snd_midi_event_encode"):
                _asound.snd_midi_event_encode.argtypes = [
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_ubyte),
                    ctypes.c_long,
                    ctypes.c_void_p,
                ]
                _asound.snd_midi_event_encode.restype = ctypes.c_long
            ev = _SndSeqEvent()
            buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
            n = _asound.snd_midi_event_encode(
                midi_ev, buf, len(raw), ctypes.byref(ev)
            )
            if n <= 0:
                return
            ev.queue = SND_SEQ_QUEUE_DIRECT
            ev.source.port = port_id & 0xFF
            ev.dest.client = kern & 0xFF
            ev.dest.port = 0
            _asound.snd_seq_event_output_direct(self._seq, ctypes.byref(ev))
        finally:
            _asound.snd_midi_event_free(midi_ev)

    def _reply_identity(self, port_id: int, payload: bytes) -> None:
        """Send identity SysEx back out the same port (to subscribers / Wine)."""
        if not self._seq:
            return
        buf = self._id_bufs.get(port_id)
        if buf is None:
            buf = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
            self._id_bufs[port_id] = buf

        ev = _SndSeqEvent()
        ev.type = SND_SEQ_EVENT_SYSEX
        ev.flags = SND_SEQ_EVENT_LENGTH_VARIABLE
        ev.queue = SND_SEQ_QUEUE_DIRECT
        ev.source.port = port_id & 0xFF
        ev.dest.client = SND_SEQ_ADDRESS_SUBSCRIBERS
        ev.dest.port = SND_SEQ_ADDRESS_UNKNOWN
        ev.data.ext.len = len(payload)
        ev.data.ext.ptr = ctypes.cast(buf, ctypes.c_void_p)

        # Prefer direct path so we never block the input pump on a full queue.
        err = _asound.snd_seq_event_output_direct(self._seq, ctypes.byref(ev))
        if err < 0:
            err = _asound.snd_seq_event_output(self._seq, ctypes.byref(ev))
            if err < 0:
                print(f"[patchbay] identity output err={err}", flush=True)
                return
            _asound.snd_seq_drain_output(self._seq)
        self.stats["id_reply"] += 1

    def _is_identity_request(self, raw: bytes) -> bool:
        # F0 7E xx 06 01 F7
        return (
            len(raw) >= 6
            and raw[0] == 0xF0
            and raw[1] == 0x7E
            and raw[3] == 0x06
            and raw[4] == 0x01
            and raw[-1] == 0xF7
        )

    def _pump(self) -> None:
        midi_ev = ctypes.c_void_p()
        if _asound.snd_midi_event_new(4096, ctypes.byref(midi_ev)) < 0:
            print(f"[patchbay] snd_midi_event_new failed ({self.client_name})", flush=True)
            return
        _asound.snd_midi_event_no_status(midi_ev, 1)

        class Pollfd(ctypes.Structure):
            _fields_ = [
                ("fd", ctypes.c_int),
                ("events", ctypes.c_short),
                ("revents", ctypes.c_short),
            ]

        buf = (ctypes.c_ubyte * 4096)()
        port_names = {v: k for k, v in self.ports.items()}

        while not self._stop.is_set():
            if not getattr(self._seq, "value", None):
                time.sleep(0.05)
                continue
            try:
                npoll = _asound.snd_seq_poll_descriptors_count(self._seq, POLLIN)
            except Exception as e:
                print(f"[patchbay] poll_count error: {e}", flush=True)
                time.sleep(0.05)
                continue
            if npoll <= 0:
                time.sleep(0.05)
                continue
            pfds = (Pollfd * npoll)()
            try:
                _asound.snd_seq_poll_descriptors(
                    self._seq, ctypes.byref(pfds), npoll, POLLIN
                )
            except Exception as e:
                print(f"[patchbay] poll_desc error: {e}", flush=True)
                time.sleep(0.05)
                continue
            try:
                r, _, _ = select.select(
                    [pfds[i].fd for i in range(npoll)], [], [], 0.2
                )
            except (ValueError, OSError):
                time.sleep(0.05)
                continue
            if not r:
                continue

            while not self._stop.is_set():
                ev_ptr = ctypes.c_void_p()
                err = _asound.snd_seq_event_input(self._seq, ctypes.byref(ev_ptr))
                if err < 0 or not ev_ptr:
                    break
                try:
                    n = _asound.snd_midi_event_decode(midi_ev, buf, 4096, ev_ptr)
                    if n <= 0:
                        continue
                    raw = bytes(buf[:n])
                    dest = self._dest_port(ev_ptr)
                    port_name = port_names.get(dest, next(iter(self.ports), "unknown"))
                    if dest is not None and dest in port_names:
                        port_name = port_names[dest]

                    self.stats["events"] += 1
                    self.stats["bytes"] += n

                    kind = "other"
                    ch = d1 = d2 = ""
                    if raw and raw[0] == 0xF0:
                        kind = "sysex"
                        self.stats["sysex"] += 1
                        if self._is_identity_request(raw):
                            kind = "identity_request"
                            self.stats["id_req"] += 1
                            id_payload = None
                            if dest is not None:
                                id_payload = self.port_identity.get(dest)
                            if id_payload is None and self.port_identity:
                                id_payload = next(iter(self.port_identity.values()))
                            if id_payload is not None and dest is not None:
                                try:
                                    self._reply_identity(dest, id_payload)
                                    print(
                                        f"[patchbay] identity reply → {port_name} "
                                        f"({len(id_payload)} B)",
                                        flush=True,
                                    )
                                except Exception as e:
                                    print(f"[patchbay] identity reply failed: {e}", flush=True)
                            # Do not forward identity request to USB bulk
                            if self.on_event:
                                try:
                                    self.on_event(
                                        {
                                            "event_type": kind,
                                            "channel": "",
                                            "d1": "",
                                            "d2": "",
                                            "payload_hex": raw.hex(),
                                            "payload_len": len(raw),
                                            "source": "wine_vdj",
                                            "sink": port_name,
                                            "kind": kind,
                                            "note": "identity_probe",
                                        }
                                    )
                                except Exception:
                                    pass
                            continue

                    # Control port: identity is answered above; forward other
                    # Wine→HW traffic to kernel NV Control. Hardware→Wine is
                    # wired separately (kernel Control → WINE input). Never bulk.
                    is_ctl = (
                        port_name == "NV Control"
                        or "1005" in port_name
                        or (
                            "Control" in port_name
                            and "MIDI" not in port_name
                        )
                    )
                    src_cli = self._source_client(ev_ptr)
                    kern_ctl = getattr(self, "_ctl_kern_client", None)
                    if is_ctl and dest is not None:
                        # Hardware → facade: rebroadcast so Wine (subscribed to
                        # facade Control only) receives jogs/pads/notes.
                        if kern_ctl is not None and src_cli == kern_ctl:
                            # Drop hardware identity replies (we answer probes)
                            if self._is_identity_request(raw):
                                continue
                            if (
                                len(raw) >= 5
                                and raw[0] == 0xF0
                                and raw[1] == 0x7E
                                and raw[3] == 0x06
                                and raw[4] == 0x02
                            ):
                                continue
                            try:
                                self._emit_raw_to_subscribers(dest, raw)
                            except Exception as e:
                                if self.stats["events"] <= 8:
                                    print(f"[patchbay] ctl HW→Wine err: {e}", flush=True)
                            continue
                        # Wine → hardware Control LEDs/etc.
                        if not self._is_identity_request(raw):
                            try:
                                self._forward_raw_to_kernel_control(dest, raw)
                            except Exception as e:
                                if self.stats["events"] <= 5:
                                    print(f"[patchbay] ctl forward err: {e}", flush=True)
                        continue

                    elif raw and (raw[0] & 0xF0) == 0xB0:
                        kind = "cc"
                        self.stats["cc"] += 1
                        ch = str((raw[0] & 0x0F) + 1)
                        d1 = str(raw[1]) if len(raw) > 1 else ""
                        d2 = str(raw[2]) if len(raw) > 2 else ""
                    elif raw and (raw[0] & 0xF0) in (0x80, 0x90):
                        kind = "note_on" if (raw[0] & 0xF0) == 0x90 else "note_off"
                        self.stats["note"] += 1
                        ch = str((raw[0] & 0x0F) + 1)
                        d1 = str(raw[1]) if len(raw) > 1 else ""
                        d2 = str(raw[2]) if len(raw) > 2 else ""
                    else:
                        self.stats["other"] += 1

                    if self.on_midi:
                        try:
                            self.on_midi(port_name, raw)
                        except Exception as e:
                            if self.stats["events"] <= 3:
                                print(f"[patchbay] on_midi err: {e}", flush=True)
                    if self.on_event:
                        try:
                            self.on_event(
                                {
                                    "event_type": kind,
                                    "channel": ch,
                                    "d1": d1,
                                    "d2": d2,
                                    "payload_hex": raw.hex(),
                                    "payload_len": len(raw),
                                    "source": "wine_vdj",
                                    "sink": port_name,
                                    "kind": kind,
                                    "note": f"from_{self.client_name}",
                                }
                            )
                        except Exception:
                            pass

                    if kind == "sysex":
                        print(
                            f"[patchbay] SYSEX {port_name} len={len(raw)} "
                            f"{raw[:24].hex()}…",
                            flush=True,
                        )
                    elif self.stats["events"] <= 20 or self.stats["events"] % 200 == 0:
                        print(
                            f"[patchbay] {self.client_name} in #{self.stats['events']} "
                            f"{kind} {port_name} ch={ch} d1={d1} d2={d2} "
                            f"hex={raw[:8].hex()}",
                            flush=True,
                        )
                finally:
                    pass

        _asound.snd_midi_event_free(midi_ev)


class AlsaPatchbay:
    """
    nv-screens ALSA clients:
      - 'nv-screens'   : vdj_in / inject_in (WRITE sinks)
      - 'NV Graphics'  : virtual facade so Wine/VDJ still sees Graphics
                         (real USB OUT is libusb-only)
    """

    def __init__(
        self,
        client_name: str = "nv-screens",
        *,
        virtual_graphics: bool = True,
        display_ports: bool = True,
    ) -> None:
        self.client_name = client_name
        self.virtual_graphics = virtual_graphics
        self.display_ports = display_ports
        self._bridge = _SeqClient(client_name)
        self._gfx: _SeqClient | None = None
        self.client_id: int | None = None
        self.ports: dict[str, int] = {}
        self.gfx_client_id: int | None = None
        self.gfx_ports: dict[str, int] = {}
        self.on_midi: Callable[[str, bytes], None] | None = None
        self.on_event: Callable[[dict], None] | None = None
        self.stats = self._bridge.stats  # primary stats (merged view below)

    def open(self) -> None:
        self._bridge.on_midi = self._dispatch_midi
        self._bridge.on_event = self._dispatch_event
        self._bridge.open(DEFAULT_PORTS)
        self.client_id = self._bridge.client_id
        self.ports = dict(self._bridge.ports)

        if self.virtual_graphics:
            # Re-read env each open so NV_FACADE_NAME_MODE can change without reload issues
            specs = _facade_port_specs()
            if not self.display_ports:
                specs = specs[:1]
            # Long client name → Wine szPname = port only (exact Windows drivernames)
            self._gfx = _SeqClient(FACADE_CLIENT_NAME)
            self._gfx.on_midi = self._dispatch_midi
            self._gfx.on_event = self._dispatch_event
            self._gfx.open(specs)
            self.gfx_client_id = self._gfx.client_id
            self.gfx_ports = dict(self._gfx.ports)
            # Control identity + Wine→HW bridge (serial from working Log Report)
            try:
                self._gfx.bridge_kernel_control()
            except Exception as e:
                print(f"[patchbay] Control bridge setup failed: {e}", flush=True)
            print(
                f"[patchbay] NV driver facade UP client={FACADE_CLIENT_NAME!r} "
                f"→ Wine MIDI names: {[s.name for s in specs]} "
                f"(mode={__import__('os').environ.get('NV_FACADE_NAME_MODE', 'windows')}; "
                f"Control identity=factory serial; libusb owns Graphics/Audio bulk)",
                flush=True,
            )

    def close(self) -> None:
        self._bridge.close()
        if self._gfx:
            self._gfx.close()
            self._gfx = None

    def start_input_watch(self) -> None:
        self._bridge.start_input_watch()
        if self._gfx:
            self._gfx.start_input_watch()
        print(
            "[patchbay] input watch started "
            "(Wine → vdj_in / virtual NV Graphics → libusb)",
            flush=True,
        )

    def _dispatch_midi(self, port: str, raw: bytes) -> None:
        if self.on_midi:
            self.on_midi(port, raw)

    def _dispatch_event(self, row: dict) -> None:
        if self.on_event:
            self.on_event(row)

    def _merged_stats(self) -> dict:
        s = dict(self._bridge.stats)
        if self._gfx:
            for k, v in self._gfx.stats.items():
                s[k] = s.get(k, 0) + v
        return s

    def status_line(self) -> str:
        if self.client_id is None:
            return "patchbay: closed"
        ports = ", ".join(f"{n}={p}" for n, p in self.ports.items())
        s = self._merged_stats()
        gfx = ""
        if self._gfx and self.gfx_client_id is not None:
            gp = ", ".join(f"{n}={p}" for n, p in self.gfx_ports.items())
            gfx = f" | NV Graphics ({self.gfx_client_id}) [{gp}]"
        return (
            f"patchbay: {self.client_name} ({self.client_id}) [{ports}]{gfx} "
            f"in_events={s['events']} sysex={s['sysex']} id_req={s.get('id_req', 0)} "
            f"id_reply={s.get('id_reply', 0)} cc={s['cc']} note={s['note']}"
        )

