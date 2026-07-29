#!/usr/bin/env bash
# Apply "fool VDJ" stack for Numark NV under Wine.
#
# Goal: make VDJ see what Windows exposes so factory paths can light up:
#   - USB 15e4:1005 / 2033 / 1033 present
#   - MIDI: Numark NV (Control kernel) + facade "NV Audio"/"NV Graphics"
#     (Windows drivernames → factory NV Display Left/Right; see WINBOAT-GROUND-TRUTH.md)
#   - Audio: WASAPI endpoint with USB VID/PID (via winealsa)
#   - Devices/Numark_NV_Audio.xml → NUMARK NV hardware button
#
set -euo pipefail

ROOT="${ROOT:-$HOME/src/nv-screens}"
WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEPREFIX
VDJ_DEV="$WINEPREFIX/drive_c/users/$USER/AppData/Local/VirtualDJ/Devices"

echo "=== apply-nv-spoof ==="
echo "WINEPREFIX=$WINEPREFIX"

# 1) Wine audio backend: alsa (reads /sys PRODUCT=15e4/1033 for device path)
#    Pulse/PipeWire path often logs "WASAPI device without vid/pid".
echo "[1] Setting Wine Drivers\\Audio=alsa (VID/PID on USB sound devices)"
wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d alsa /f >/dev/null 2>&1 || {
  echo "  wine reg failed — writing user.reg snippet manually may be needed"
}

# 2) Standalone audio definition (NUMARK NV button)
echo "[2] Installing Devices/Numark_NV_Audio.xml"
mkdir -p "$VDJ_DEV"
cp -f "$ROOT/tools/vdj-devices/Numark_NV_Audio.xml" "$VDJ_DEV/Numark_NV_Audio.xml" 2>/dev/null || \
  cp -f "$VDJ_DEV/Numark_NV_Audio.xml" "$VDJ_DEV/Numark_NV_Audio.xml" 2>/dev/null || true
# Prefer repo copy if present
if [[ -f "$ROOT/tools/vdj-devices/Numark_NV_Audio.xml" ]]; then
  cp -f "$ROOT/tools/vdj-devices/Numark_NV_Audio.xml" "$VDJ_DEV/Numark_NV_Audio.xml"
fi
ls -la "$VDJ_DEV/"

# 3) Ensure no shadowing MIDI display XML (factory must win for displays)
echo "[3] Removing shadowing display XML (keep only audio + controllers.dat)"
rm -f "$VDJ_DEV"/NMNV_Display_*.xml "$VDJ_DEV"/NMNV_Graphics.xml 2>/dev/null || true

# 4) USB present?
echo "[4] USB NV products:"
lsusb -d 15e4: || echo "  WARN: NV not on bus"

# 5) usbid for winealsa path
echo "[5] ALSA usbid (winealsa uses this):"
for c in /proc/asound/card*/usbid; do
  [[ -f "$c" ]] || continue
  id=$(cat "$c")
  card=$(echo "$c" | grep -o 'card[0-9]*')
  name=$(cat "/proc/asound/${card}/id" 2>/dev/null || echo '?')
  echo "  $card ($name): $id"
done

echo
echo "Done. Fully quit VirtualDJ and relaunch from the desktop icon."
echo "Then check:"
echo "  • AUDIO tab → NUMARK NV button clickable"
echo "  • Log Report: no longer 'WASAPI device without vid/pid' for NV Audio"
echo "  • Controllers: Numark NV + NV Display Left + NV Display Right (factory)"
echo "  • Wine MIDI names: NV Control + NV Audio + NV Graphics (no 'MIDI 1' suffix)"
echo "  • Mapping: factory default where possible"
echo "  • live-bridge: sysex_forwarded if imagesysex wakes up"
echo "  • Launch: NV_MODE=driver $HOME/bin/start-virtualdj.sh   (or tools/start-nv-driver.sh)"
