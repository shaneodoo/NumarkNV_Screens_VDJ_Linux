"""Append-only CSV traffic log for captures and live nv-screens I/O."""
from __future__ import annotations

import csv
import threading
import time
from pathlib import Path
from typing import Any, Iterable

# Wide enough for protocol RE; hex payloads capped so files stay manageable.
DEFAULT_FIELDS = [
    "ts_mono",
    "ts_wall",
    "seq",
    "direction",
    "source",
    "sink",
    "product",
    "product_name",
    "ep",
    "urb_len",
    "kind",
    "cin",
    "cin_name",
    "sysex_cmd",
    "sysex_role",
    "sysex_id",
    "deck",
    "midi_status",
    "d1",
    "d2",
    "channel",
    "latency_ms",
    "payload_hex",
    "payload_len",
    "note",
]


class CsvTrafficLog:
    def __init__(
        self,
        path: Path,
        *,
        max_hex: int = 512,
        fields: list[str] | None = None,
    ) -> None:
        self.path = Path(path)
        self.max_hex = max_hex
        self.fields = list(fields or DEFAULT_FIELDS)
        self._lock = threading.Lock()
        self._seq = 0
        self._t0 = time.monotonic()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists() or self.path.stat().st_size == 0
        self._fp = self.path.open("a", newline="", encoding="utf-8")
        self._w = csv.DictWriter(self._fp, fieldnames=self.fields, extrasaction="ignore")
        if new:
            self._w.writeheader()
            self._fp.flush()

    def close(self) -> None:
        with self._lock:
            try:
                self._fp.flush()
                self._fp.close()
            except Exception:
                pass

    def write(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            base = {
                "ts_mono": f"{time.monotonic() - self._t0:.6f}",
                "ts_wall": f"{time.time():.6f}",
                "seq": self._seq,
            }
            out = {k: "" for k in self.fields}
            out.update(base)
            for k, v in row.items():
                if k not in out:
                    continue
                if k == "payload_hex" and isinstance(v, (bytes, bytearray)):
                    hx = bytes(v).hex()
                    if len(hx) > self.max_hex:
                        hx = hx[: self.max_hex] + "…"
                    out[k] = hx
                    out["payload_len"] = str(len(v))
                elif k == "payload_hex" and isinstance(v, str) and len(v) > self.max_hex:
                    out[k] = v[: self.max_hex] + "…"
                else:
                    out[k] = "" if v is None else str(v)
            self._w.writerow(out)
            if self._seq % 50 == 0:
                self._fp.flush()

    def write_many(self, rows: Iterable[dict[str, Any]]) -> None:
        for r in rows:
            self.write(r)
