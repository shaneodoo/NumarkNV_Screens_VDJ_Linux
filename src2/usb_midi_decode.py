"""
Decode USB-MIDI event packets (4-byte cells) and reassemble SysEx.

USB-MIDI cell layout (USB MIDI 1.0):
  byte0: cable_nibble (hi) | Code Index Number (lo)
  bytes1-3: MIDI data

CIN common values:
  0x4 = SysEx starts/continues (3 bytes)
  0x5 = SysEx ends 1 byte / single-byte system common
  0x6 = SysEx ends 2 bytes
  0x7 = SysEx ends 3 bytes
  0x8 Note Off, 0x9 Note On, 0xA Poly Pressure
  0xB Control Change, 0xC Program Change, 0xD Channel Pressure
  0xE Pitch Bend, 0xF Single byte
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

CIN_NAMES = {
    0x0: "misc",
    0x1: "cable_event",
    0x2: "two_byte_common",
    0x3: "three_byte_common",
    0x4: "sysex_start_cont",
    0x5: "sysex_end_1_or_single",
    0x6: "sysex_end_2",
    0x7: "sysex_end_3",
    0x8: "note_off",
    0x9: "note_on",
    0xA: "poly_pressure",
    0xB: "cc",
    0xC: "program_change",
    0xD: "channel_pressure",
    0xE: "pitch_bend",
    0xF: "single_byte",
}

PRODUCT_NAMES = {
    0x1005: "control",
    0x2033: "graphics",
    0x1033: "audio",
}


@dataclass
class MidiCell:
    cable: int
    cin: int
    data: bytes  # 1–3 meaningful MIDI bytes (may include padding zeros in raw)

    @property
    def cin_name(self) -> str:
        return CIN_NAMES.get(self.cin, f"cin_{self.cin:x}")

    @property
    def midi_bytes(self) -> bytes:
        """Data bytes without trailing pad zeros implied by CIN."""
        if self.cin in (0x4, 0x7):
            return self.data[:3]
        if self.cin == 0x6:
            return self.data[:2]
        if self.cin in (0x5, 0xF, 0xC, 0xD):
            # 0x5 may be 1-byte sysex end or 1-byte system; 0xC/D are 1 data + status
            if self.cin == 0x5:
                return bytes(b for b in self.data if True)[:1] if self.data[0] == 0xF7 else self.data[:1]
            if self.cin in (0xC, 0xD):
                return self.data[:2]  # status + 1
            return self.data[:1]
        if self.cin in (0x8, 0x9, 0xA, 0xB, 0xE, 0x2, 0x3):
            if self.cin in (0xC, 0xD):  # pragma: no cover
                return self.data[:2]
            if self.cin == 0x2:
                return self.data[:2]
            return self.data[:3]
        return self.data.rstrip(b"\x00") or self.data[:1]


def iter_cells(payload: bytes) -> Iterator[MidiCell]:
    """Yield 4-byte USB-MIDI cells from a bulk URB payload."""
    for i in range(0, len(payload) - 3, 4):
        b0, b1, b2, b3 = payload[i : i + 4]
        cable = (b0 >> 4) & 0x0F
        cin = b0 & 0x0F
        if cin == 0 and b1 == 0 and b2 == 0 and b3 == 0:
            continue  # padding
        yield MidiCell(cable=cable, cin=cin, data=bytes((b1, b2, b3)))


def cells_to_midi_stream(payload: bytes) -> bytes:
    """Flatten USB-MIDI cells into a raw MIDI byte stream (best-effort)."""
    out = bytearray()
    for cell in iter_cells(payload):
        cin = cell.cin
        d = cell.data
        if cin == 0x4:
            out += d[:3]
        elif cin == 0x5:
            out += d[:1]
        elif cin == 0x6:
            out += d[:2]
        elif cin == 0x7:
            out += d[:3]
        elif cin in (0x8, 0x9, 0xA, 0xB, 0xE):
            out += d[:3]
        elif cin in (0xC, 0xD):
            out += d[:2]
        elif cin == 0xF:
            out += d[:1]
        elif cin == 0x2:
            out += d[:2]
        elif cin == 0x3:
            out += d[:3]
    return bytes(out)


@dataclass
class SysexMsg:
    data: bytes
    cable: int = 0

    @property
    def cmd(self) -> str:
        # F0 47 id_hi id_lo cmd_hi cmd_lo …
        if len(self.data) >= 6 and self.data[0] == 0xF0 and self.data[1] == 0x47:
            return self.data[4:6].hex()
        return ""

    @property
    def mfg_id(self) -> str:
        if len(self.data) >= 4 and self.data[0] == 0xF0:
            return self.data[2:4].hex()
        return ""

    @property
    def deck(self) -> int | None:
        if len(self.data) > 10 and self.data[0] == 0xF0 and self.data[1] == 0x47:
            return self.data[10]
        return None

    @property
    def role(self) -> str:
        c = self.cmd
        return {
            "0506": "init_a",
            "0508": "init_b",
            "0530": "layout",
            "0501": "setup_1",
            "0502": "setup_2",
            "0507": "block_0507",
            "0505": "status",
            "0509": "paint",
            "0531": "paint_big",
            "050a": "cmd_050a",
            "0521": "cmd_0521",
            "0522": "cmd_0522",
            "0524": "cmd_0524",
        }.get(c, f"cmd_{c}" if c else "sysex")


class SysexReassembler:
    """Reassemble SysEx spanning multiple USB-MIDI cells / URBs."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._cable = 0

    def reset(self) -> None:
        self._buf.clear()

    def feed_payload(self, payload: bytes) -> list[SysexMsg]:
        done: list[SysexMsg] = []
        for cell in iter_cells(payload):
            cin = cell.cin
            if cin not in (0x4, 0x5, 0x6, 0x7):
                # short MIDI — ignore for sysex reassembly
                continue
            if cin == 0x4:
                if not self._buf and cell.data[0] == 0xF0:
                    self._buf = bytearray(cell.data[:3])
                    self._cable = cell.cable
                elif self._buf:
                    self._buf += cell.data[:3]
                else:
                    # orphan continue — start soft
                    self._buf = bytearray(cell.data[:3])
                    self._cable = cell.cable
            elif cin == 0x5:
                self._buf += cell.data[:1]
                if self._buf and self._buf[-1] == 0xF7:
                    done.append(SysexMsg(data=bytes(self._buf), cable=self._cable))
                    self._buf.clear()
            elif cin == 0x6:
                self._buf += cell.data[:2]
                if self._buf and self._buf[-1] == 0xF7:
                    done.append(SysexMsg(data=bytes(self._buf), cable=self._cable))
                    self._buf.clear()
            elif cin == 0x7:
                self._buf += cell.data[:3]
                if self._buf and self._buf[-1] == 0xF7:
                    done.append(SysexMsg(data=bytes(self._buf), cable=self._cable))
                    self._buf.clear()
        return done


def short_midi_summary(payload: bytes) -> list[dict]:
    """Summarise non-SysEx cells for CSV rows."""
    rows = []
    for idx, cell in enumerate(iter_cells(payload)):
        if cell.cin in (0x4, 0x5, 0x6, 0x7):
            continue
        d = cell.data
        status = d[0] if d else 0
        ch = (status & 0x0F) + 1 if status & 0x80 else 0
        rows.append(
            {
                "cell": idx,
                "cable": cell.cable,
                "cin": cell.cin,
                "cin_name": cell.cin_name,
                "status": f"{status:02x}",
                "d1": f"{d[1]:02x}" if len(d) > 1 else "",
                "d2": f"{d[2]:02x}" if len(d) > 2 else "",
                "channel": ch,
            }
        )
    return rows
