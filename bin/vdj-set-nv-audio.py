#!/usr/bin/env python3
"""Point VirtualDJ master+phones at Numark NV Audio PCM (4ch) using current card GUID.

Hybrid claim can renumber cards; always resolve NV Audio via /proc/asound and
Wine's winealsa.drv device GUID for plughw:N,0.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

home = Path.home()
user_reg = home / ".wine/user.reg"
settings = home / ".wine/drive_c/users" / home.name / "AppData/Local/VirtualDJ/settings.xml"
if not settings.exists():
    raise SystemExit(0)

# Find NV Audio card number (by usbid 15e4:1033 or id Audio + USB)
card_num: str | None = None
for usbid in Path("/proc/asound").glob("card*/usbid"):
    try:
        if usbid.read_text().strip().lower() == "15e4:1033":
            card_num = usbid.parent.name.replace("card", "")
            break
    except OSError:
        continue
if card_num is None:
    cards = Path("/proc/asound/cards").read_text(errors="replace")
    for line in cards.splitlines():
        m = re.match(r"\s*(\d+)\s+\[[^\]]*Audio\].*NV Audio", line, re.I)
        if m:
            card_num = m.group(1)
            break
if card_num is None:
    print("NV Audio card not found — is hybrid claiming PCM by mistake?")
    raise SystemExit(0)

# Resolve GUID for plughw:card,0 from user.reg
guid = None
if user_reg.exists():
    text = user_reg.read_text(errors="replace")
    # Wine stores: [Software\\Wine\\Drivers\\winealsa.drv\\devices\\0,plughw:4,0]
    # "guid"=hex:fe,dc,96,b4,...
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
            # Wine GUID binary is mixed-endian like Windows
            d1, d2, d3 = struct.unpack("<IHH", b[:8])
            d4 = b[8:16]
            guid = (
                f"{{{d1:08X}-{d2:04X}-{d3:04X}-"
                f"{d4[0]:02X}{d4[1]:02X}-"
                f"{d4[2]:02X}{d4[3]:02X}{d4[4]:02X}{d4[5]:02X}{d4[6]:02X}{d4[7]:02X}}}"
            )

if not guid:
    # Last known good from this machine's plughw:4,0 mapping
    guid = "{B496DCFE-8C7B-4CE3-9C77-F9CED9D8C35F}"

# Prefer name that includes USB Audio so user sees NV hardware
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
    print("audioConfig not found")
    raise SystemExit(0)

# Prefer hardware-style options
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
# Ensure Numark audio def is present (button)
devices = settings.parent / "Devices"
devices.mkdir(parents=True, exist_ok=True)
audio_xml = devices / "Numark_NV_Audio.xml"
repo = home / "src/nv-screens/tools/vdj-devices/Numark_NV_Audio.xml"
if repo.exists():
    audio_xml.write_text(repo.read_text(encoding="utf-8"), encoding="utf-8")

settings.write_text(text2, encoding="utf-8")
print(f"VDJ audio -> NV card {card_num} {guid}")
