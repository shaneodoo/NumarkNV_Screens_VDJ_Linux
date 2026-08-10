#!/usr/bin/env bash
# Point Wine/VDJ at Numark NV audio and drop shadowing display XML.
set -euo pipefail

ROOT="${ROOT:-$HOME/src/nv-screens}"
WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEPREFIX
VDJ_DEV="$WINEPREFIX/drive_c/users/$USER/AppData/Local/VirtualDJ/Devices"
XML="$ROOT/config/vdj-devices/Numark_NV_Audio.xml"

# Canonical USB identity — see config/nv-ids.env (single source of truth)
# shellcheck source=/dev/null
source "$ROOT/config/nv-ids.env"

echo "apply-nv-spoof: WINEPREFIX=$WINEPREFIX"

wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d alsa /f >/dev/null 2>&1 || true

mkdir -p "$VDJ_DEV"
if [[ -f "$XML" ]]; then
  cp -f "$XML" "$VDJ_DEV/Numark_NV_Audio.xml"
fi
rm -f "$VDJ_DEV"/NMNV_Display_*.xml "$VDJ_DEV"/NMNV_Graphics.xml 2>/dev/null || true

lsusb -d "${NV_VID}:" >/dev/null 2>&1 || echo "WARN: Numark NV not seen on USB"

echo "done — fully quit VDJ and relaunch start-virtualdj.sh"
