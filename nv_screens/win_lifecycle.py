"""
VDJ open/close SysEx for Numark NV dual LCDs.

USB products:
  1.2.*  15e4:1005  Control          pads/jogs (kernel ALSA — we never claim)
  1.3.3  15e4:2033  Graphics EP 0x03 Display Right MIDI bulk
  1.4.0  15e4:1033  Audio   EP 0x00 control (SET_INTERFACE)
  1.4.1  15e4:1033  Audio   EP 0x01 ISO PCM (kernel — we never claim)
  1.4.3  15e4:1033  Audio   EP 0x03 Display Left MIDI bulk

Startup (after SET_INTERFACE alt=1 + audio pipe prep):
  host→1.4.3  short CC, then 0506/0508 open
  host→1.3.3  same open

Shutdown (VDJ File→Exit):
  zeroed 0505 / 0504 / 0520 on Left then Right
  ABORT_PIPE + SET_INTERFACE alt=0 on audio (kernel closes PCM)
  firmware logos after host releases pipes (no logo bitmap SysEx)

On Linux we replay the MIDI halves; PCM open/close is ALSA/kernel.
"""
from __future__ import annotations

# Product IDs in F0 47 <hi> <lo> … — canonical values from config/nv-ids.env
from nv_screens.ids import PID_AUDIO, PID_GRAPHICS, PID_CONTROL  # noqa: E402,F401

# --- Open (frame ~381+): 0506 then 0508 per product ---
OPEN_LEFT: list[bytes] = [
    bytes.fromhex("f04710330506000a00080160030001000200f7"),
    bytes.fromhex("f04710330508000a0008013c000002400000f7"),
]
OPEN_RIGHT: list[bytes] = [
    bytes.fromhex("f04720330506000a00080160030001000200f7"),
    bytes.fromhex("f04720330508000a0008013c000002400000f7"),
]

# Layout blob (0530) — same payload on both products in reference capture; we send
# once per USB product after 0506/0508 so panels leave logo chrome.
OPEN_0530 = bytes.fromhex(
    "f04720330530091509130000000000000000004c010000202600000030060000407f000000787f7f3f0033660000606c0c0000324e010000731900007c1f0300000066000018630c0000664c01001053190000181b0300603f33000000480900401919010030161300001933020040392600007e67040000006600004c610c0000334c010048491900004c190300701f330000007c0700604c7f0000187b0f00404c7f0100607c1f00007f7f03000000401900660018034019003300640430060066006600780f600c0000664c0130664c19004c4d19032066193300301e3306407f33660000606c0c00334c4d01604c591900321a1b0300333333007c37360600001967001813730c0066324e01103366190018671c03607f4c330000603c0640194c67003046790c0019194f0140197319007e331e0300407f33004c793f0600337f670048797f0c004c7f4f01707f7f190000003006600c0066001803600c404c004c01600c4019007f01180300600c3300664c31064059196600641c630c0066334c01783f461900004c190330461933004c19330620263366003036660c407f664c01001053190033321a03602c2633003266340600734c66007c4f690c00004c4d01184359190066181b03101333330018333606603f66660000786f0c40197f4d0130765f1900197f1b0340793f33007e7f370600000019014c011013003300320248092026004c016404701f404c00004c4909604c191901181b1313404c333202603c2626007f6764040040594c0066184b094019331901643416130066663202786f2c2600003266043026664c004c654c0920664c1901304e1913407f193302004039260033186704600c734c0032324e0900336619017c671c1300007f330218733f2600667e670410737f4c00187f4f09607f7f190100004019401900180330060033001901300640190066007e03600c0040194c014c194319003333180348390633004c673006707f0c66000018630c600c334c0118334619404c661803606c0c33007f4d310600202666006664640c40594c4c01644c49190066191903781f1333000018330630063366004c31660c2026664c0130664c19407f4c190300701f3300337e3306606c3f6600327e670c00737f4c017c7f4f190000007e031803603f0066007c071013407f001803780f603f007f010018731f4019337e033036663f0019677c0740794c7f007e4f790f0000337f014c31761f0033667e0348696c3f004c4d7d07705f597f0000647c0f604c4c7f01184b791f404c197f03601c733f007f337e070000737f0066307e0f4019667f0164647c1f00664c7f03784f793f00007e7f0730667f7f004c7d7f0f20667f7f01307e7f1f407f7f7f0300000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f7"
)


# Short host→device CC packets that precede open  (USB-MIDI cells).
# Exact first cells from capture bulk start on 1.4.3 (4-byte event packets).
WAKE_CC_CELLS: list[bytes] = [
    bytes.fromhex("0bb00000"),  # CC style cell (as seen in early bulk OUT)
    bytes.fromhex("0bb00000"),
    bytes.fromhex("0bb00000"),
]


def _zero_status(pid: int) -> list[bytes]:
    """Zeroed 0505/0504/0520 for one product (shutdown clear from capture)."""
    hi, lo = (pid >> 8) & 0xFF, pid & 0xFF
    # Templates from 1.4 shutdown (16.67s) with product bytes substituted.
    # 0505 decks 1 and 3 (or 2 and 4 on right — body is zeroed either way)
    s0505_a = bytes(
        [0xF0, 0x47, hi, lo, 0x05, 0x05, 0x00, 0x14, 0x00, 0x12, 0x01]
        + [0x00] * 16
        + [0xF7]
    )
    s0505_b = bytes(
        [0xF0, 0x47, hi, lo, 0x05, 0x05, 0x00, 0x14, 0x00, 0x12, 0x03]
        + [0x00] * 16
        + [0xF7]
    )
    s0504_a = bytes(
        [0xF0, 0x47, hi, lo, 0x05, 0x04, 0x00, 0x18, 0x00, 0x16, 0x01]
        + [0x00] * 20
        + [0xF7]
    )
    s0504_b = bytes(
        [0xF0, 0x47, hi, lo, 0x05, 0x04, 0x00, 0x18, 0x00, 0x16, 0x03]
        + [0x00] * 20
        + [0xF7]
    )
    s0520 = bytes(
        [0xF0, 0x47, hi, lo, 0x05, 0x20, 0x00, 0x0E, 0x00, 0x0C]
        + [0x00] * 12
        + [0xF7]
    )
    return [s0505_a, s0505_b, s0504_a, s0504_b, s0520]


# Exact bytes from capture (prefer these over synthesised)
CLOSE_LEFT: list[bytes] = [
    bytes.fromhex(
        "f0471033050500140012010000000000000000000000000000000000f7"
    ),
    bytes.fromhex(
        "f0471033050500140012030000000000000000000000000000000000f7"
    ),
    bytes.fromhex(
        "f047103305040018001601000000000000000000000000000000000000000000f7"
    ),
    bytes.fromhex(
        "f047103305040018001603000000000000000000000000000000000000000000f7"
    ),
    bytes.fromhex("f04710330520000e000c000000000000000000000000f7"),
]
CLOSE_RIGHT: list[bytes] = [
    bytes.fromhex(
        "f0472033050500140012010000000000000000000000000000000000f7"
    ),
    bytes.fromhex(
        "f0472033050500140012030000000000000000000000000000000000f7"
    ),
    bytes.fromhex(
        "f047203305040018001601000000000000000000000000000000000000000000f7"
    ),
    bytes.fromhex(
        "f047203305040018001603000000000000000000000000000000000000000000f7"
    ),
    bytes.fromhex("f04720330520000e000c000000000000000000000000f7"),
]


def open_sequence() -> list[tuple[int, bytes]]:
    """(usb_product_id, sysex) for dual-LCD open — Left then Right."""
    out: list[tuple[int, bytes]] = []
    for m in OPEN_LEFT:
        out.append((PID_AUDIO, m))
    # 0530 layout on Left USB (capture tags product 2033; port/USB is Audio)
    out.append((PID_AUDIO, OPEN_0530))
    for m in OPEN_RIGHT:
        out.append((PID_GRAPHICS, m))
    out.append((PID_GRAPHICS, OPEN_0530))
    return out


def close_sequence() -> list[tuple[int, bytes]]:
    """(usb_product_id, sysex) standard zero clear — Left then Right."""
    out: list[tuple[int, bytes]] = []
    for m in CLOSE_LEFT:
        out.append((PID_AUDIO, m))
    for m in CLOSE_RIGHT:
        out.append((PID_GRAPHICS, m))
    return out


def close_then_reopen() -> list[tuple[int, bytes]]:
    """Clear ghost frames then re-send open (best captured LCD teardown)."""
    return close_sequence() + open_sequence()


# ---------------------------------------------------------------------------
# Full empty-deck UI + close from wake sequence
# ---------------------------------------------------------------------------

def empty_deck_sequence() -> list[tuple[int, bytes]]:
    """Open + full empty Controllers chrome (no track 0509). Left then Right."""
    from nv_screens.win_empty_deck_data import EMPTY_DECK
    return list(EMPTY_DECK)


def empty_deck_wake_clean() -> list[tuple[int, bytes]]:
    """Full Controllers chrome with capture track/browser text blanked.

    The stock empty-deck capture still embeds a ghost library row (e.g. After
    Burn). Open-only (0506/0508/0530) leaves the panels half-asleep / blank.
    This keeps open + chrome (0501/0502/0507/…) and zeroes 0521 title lines
    plus non-empty 0524 browser strips so the LCD wakes fully without a fake
    track list. Live VDJ paint replaces it next.
    """
    from nv_screens.win_empty_deck_data import EMPTY_DECK

    # Blank 0524 row templates: strip index 1..6 are already empty rows.
    blank_0524: dict[int, bytes] = {}
    for pid, m in EMPTY_DECK:
        if len(m) < 12 or m[0] != 0xF0 or m[4:6] != b"\x05\x24":
            continue
        strip = m[10]
        body_nz = sum(1 for b in m[11:-1] if b)
        if strip != 0 and body_nz <= 12:
            # Retarget this empty row to strip 0 later
            blank_0524[pid] = m

    out: list[tuple[int, bytes]] = []
    for pid, m in EMPTY_DECK:
        if len(m) < 6 or m[0] != 0xF0:
            out.append((pid, m))
            continue
        cmd = m[4:6].hex()
        if cmd == "0521":
            # Keep product + line index header; zero glyph payload (no After Burn)
            nm = bytearray(m)
            for i in range(11, len(nm) - 1):
                nm[i] = 0
            out.append((pid, bytes(nm)))
        elif cmd == "0524" and m[10] == 0 and pid in blank_0524:
            tmpl = bytearray(blank_0524[pid])
            tmpl[2] = m[2]  # product family byte
            tmpl[10] = 0  # strip 0
            out.append((pid, bytes(tmpl)))
        else:
            out.append((pid, m))
    return out


def full_close_sequence() -> list[tuple[int, bytes]]:
    """File→Exit tail from same capture (status clear on both LCDs)."""
    from nv_screens.win_empty_deck_data import CLOSE_SEQ
    return list(CLOSE_SEQ)


def close_then_empty_open() -> list[tuple[int, bytes]]:
    """Clear then re-show empty deck (best pre-USB-reset quit path)."""
    return full_close_sequence() + empty_deck_sequence()

