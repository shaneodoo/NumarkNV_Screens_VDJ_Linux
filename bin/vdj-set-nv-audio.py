#!/usr/bin/env python3
"""Point VirtualDJ master+phones at Numark NV Audio PCM (4ch) using live Wine GUID.

Portable: uses WINEPREFIX, ROOT / NV_IDS_ENV, and config next to the install tree.
No machine-specific GUIDs or fixed home paths.
"""
from __future__ import annotations

import os
import re
import struct
import sys
from pathlib import Path


def _install_root() -> Path:
    """Resolve install tree: ROOT env, or parent of bin/ when this file lives there."""
    env = os.environ.get("ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parent
    parent = here.parent
    if (parent / "config" / "nv-ids.env").is_file() or (parent / "nv_screens").is_dir():
        return parent
    return parent  # best effort


def _wineprefix() -> Path:
    return Path(os.environ.get("WINEPREFIX", Path.home() / ".wine")).expanduser().resolve()


def _load_nv_audio_usbid(root: Path) -> str:
    candidates: list[Path] = []
    env_override = os.environ.get("NV_IDS_ENV")
    if env_override:
        candidates.append(Path(env_override).expanduser())
    candidates.append(root / "config" / "nv-ids.env")
    # When this script still lives under bin/ of the tree
    candidates.append(Path(__file__).resolve().parent.parent / "config" / "nv-ids.env")

    for path in candidates:
        try:
            values: dict[str, str] = {}
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
            vid = values.get("NV_VID")
            pid = values.get("NV_PID_AUDIO")
            if vid and pid:
                return f"{vid}:{pid}".lower()
        except OSError:
            continue
    # Stock Numark NV Audio (product default only — not a personal machine ID)
    return "15e4:1033"


def main() -> int:
    root = _install_root()
    prefix = _wineprefix()
    user = os.environ.get("USER") or Path.home().name
    settings = (
        prefix
        / "drive_c"
        / "users"
        / user
        / "AppData"
        / "Local"
        / "VirtualDJ"
        / "settings.xml"
    )
    if not settings.exists():
        # Common alternate casing for username folder under Wine
        users_dir = prefix / "drive_c" / "users"
        if users_dir.is_dir():
            for cand in users_dir.iterdir():
                p = cand / "AppData" / "Local" / "VirtualDJ" / "settings.xml"
                if p.is_file():
                    settings = p
                    break
    if not settings.exists():
        print("VDJ settings.xml not found — skip audio pin (install VirtualDJ first)")
        return 0

    nv_audio_usbid = _load_nv_audio_usbid(root)

    card_num: str | None = None
    for usbid in Path("/proc/asound").glob("card*/usbid"):
        try:
            if usbid.read_text().strip().lower() == nv_audio_usbid:
                card_num = usbid.parent.name.replace("card", "")
                break
        except OSError:
            continue
    if card_num is None:
        try:
            cards = Path("/proc/asound/cards").read_text(errors="replace")
        except OSError:
            cards = ""
        for line in cards.splitlines():
            m = re.match(r"\s*(\d+)\s+\[[^\]]*Audio\].*NV Audio", line, re.I)
            if m:
                card_num = m.group(1)
                break
    if card_num is None:
        print(
            f"NV Audio card not found (usbid {nv_audio_usbid}) — "
            "is the deck plugged in / PCM claimed by mistake?"
        )
        return 0

    # Resolve GUID for plughw:card,0 from this prefix's user.reg only
    guid: str | None = None
    user_reg = prefix / "user.reg"
    if user_reg.exists():
        text = user_reg.read_text(errors="replace")
        pat = re.compile(
            r"\[Software\\\\Wine\\\\Drivers\\\\winealsa\.drv\\\\devices\\\\0,plughw:"
            + re.escape(card_num)
            + r",0\][^\[]*?\"guid\"=hex:([0-9a-fA-F,]+)",
            re.S,
        )
        m = pat.search(text)
        if m:
            hx = [int(x, 16) for x in m.group(1).split(",") if x]
            b = bytes(hx[:16])
            if len(b) == 16:
                d1, d2, d3 = struct.unpack("<IHH", b[:8])
                d4 = b[8:16]
                guid = (
                    f"{{{d1:08X}-{d2:04X}-{d3:04X}-"
                    f"{d4[0]:02X}{d4[1]:02X}-"
                    f"{d4[2]:02X}{d4[3]:02X}{d4[4]:02X}{d4[5]:02X}"
                    f"{d4[6]:02X}{d4[7]:02X}}}"
                )

    if not guid:
        print(
            f"NV Audio card {card_num} found, but no Wine alsa GUID for "
            f"plughw:{card_num},0 yet — start VDJ once with winealsa so Wine "
            "enumerates devices, then re-run or relaunch start-virtualdj.sh"
        )
        return 0

    dev = f"wasapi://{{0.0.0.00000000}}.{guid} (Out: NV Audio - USB Audio)"
    new_audio = f"""<audioConfig current="config 1">
<setup name="config 1">
<audio soundcard="{dev}" leftChannel="1" rightChannel="2" source="master" />
<audio soundcard="{dev}" leftChannel="3" rightChannel="4" source="headphones" />
</setup>
</audioConfig>"""

    text = settings.read_text(encoding="utf-8", errors="replace")
    text2, n = re.subn(r"<audioConfig[\s\S]*?</audioConfig>", new_audio, text, count=1)
    if not n:
        print("audioConfig not found in settings.xml")
        return 0

    text2 = re.sub(
        r"<exclusiveAudioAccess>[^<]*</exclusiveAudioAccess>",
        "<exclusiveAudioAccess>yes</exclusiveAudioAccess>",
        text2,
        count=1,
    )
    text2 = re.sub(
        r"<audioAutoDetect>[^<]*</audioAutoDetect>",
        "<audioAutoDetect>yes</audioAutoDetect>",
        text2,
        count=1,
    )

    devices = settings.parent / "Devices"
    devices.mkdir(parents=True, exist_ok=True)
    audio_xml = devices / "Numark_NV_Audio.xml"
    for cand in (
        root / "config" / "vdj-devices" / "Numark_NV_Audio.xml",
        Path(__file__).resolve().parent.parent / "config" / "vdj-devices" / "Numark_NV_Audio.xml",
    ):
        if cand.is_file():
            audio_xml.write_text(cand.read_text(encoding="utf-8"), encoding="utf-8")
            break

    settings.write_text(text2, encoding="utf-8")
    print(f"VDJ audio -> NV card {card_num} {guid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
