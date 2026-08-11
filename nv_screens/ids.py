"""
Single source of truth for Numark NV USB identity.

Reads ``config/nv-ids.env`` (KEY=VALUE, hex digits without a 0x prefix) so
the VID/PIDs are declared exactly once and shared with shell scripts and
udev tooling, instead of being hardcoded independently in every consumer.

Adding a new NV variant (e.g. an NV II with different product IDs) means
editing config/nv-ids.env only — everything importing from this module
picks the new values up automatically.
"""
from __future__ import annotations

from pathlib import Path

# config/ and nv_screens/ are sibling directories under the install root.
_ENV_PATH = Path(__file__).resolve().parent.parent / "config" / "nv-ids.env"

# Fallback = stock Numark NV factory product IDs (not machine-specific).
# Real installs get config/nv-ids.env from tools/detect-nv.sh / install.sh.
_DEFAULTS = {
    "NV_VID": "15e4",
    "NV_PID_CONTROL": "1005",
    "NV_PID_AUDIO": "1033",
    "NV_PID_GRAPHICS": "2033",
}


def _load(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key:
                values[key] = val
    except OSError:
        pass
    return values


def _env_paths() -> list[Path]:
    paths: list[Path] = []
    override = __import__("os").environ.get("NV_IDS_ENV", "").strip()
    if override:
        paths.append(Path(override).expanduser())
    root = __import__("os").environ.get("ROOT", "").strip()
    if root:
        paths.append(Path(root).expanduser() / "config" / "nv-ids.env")
    paths.append(_ENV_PATH)
    return paths


_RAW = dict(_DEFAULTS)
for _p in _env_paths():
    loaded = _load(_p)
    if loaded:
        _RAW.update(loaded)
        break

VID: int = int(_RAW["NV_VID"], 16)
PID_CONTROL: int = int(_RAW["NV_PID_CONTROL"], 16)
PID_AUDIO: int = int(_RAW["NV_PID_AUDIO"], 16)
PID_GRAPHICS: int = int(_RAW["NV_PID_GRAPHICS"], 16)

# Convenience 4-digit lowercase hex strings, no 0x prefix — the format used
# throughout sysfs (/sys/bus/usb/devices/*/idProduct), /proc/asound usbid,
# lsusb, and the existing "vid_15e4&pid_1033" style port-name matching.
VID_HEX: str = f"{VID:04x}"
PID_CONTROL_HEX: str = f"{PID_CONTROL:04x}"
PID_AUDIO_HEX: str = f"{PID_AUDIO:04x}"
PID_GRAPHICS_HEX: str = f"{PID_GRAPHICS:04x}"

PRODUCT_NAMES: dict[int, str] = {
    PID_CONTROL: "control",
    PID_AUDIO: "audio",
    PID_GRAPHICS: "graphics",
}

# Order matters for the two paint targets (Control is never claimed).
KNOWN_PIDS: tuple[int, ...] = (PID_CONTROL, PID_AUDIO, PID_GRAPHICS)
