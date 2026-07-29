#!/usr/bin/env bash
# Install Numark-VID/PID-aware winealsa.so (built for Wine 11.0).
# Requires sudo once. Safe: keeps timestamped backup of the system file.
set -euo pipefail
SRC="${1:-$HOME/src/nv-screens/wine-patch/x86_64-unix/winealsa.so}"
DST="/usr/lib64/wine-wow64/wine/x86_64-unix/winealsa.so"
if [[ ! -f "$SRC" ]]; then
  echo "Missing $SRC"
  echo "Build: see docs/HARD-PUSH-FACTORY-DISPLAYS.md"
  exit 1
fi
if [[ ! -f "$DST" ]]; then
  echo "System winealsa not at $DST — adjust path for your Wine package"
  exit 1
fi
BAK="${DST}.bak-pre-nv-$(date +%Y%m%d%H%M%S)"
echo "Backup: $BAK"
sudo cp -a "$DST" "$BAK"
echo "Install: $SRC → $DST"
sudo cp -a "$SRC" "$DST"
sudo chmod 755 "$DST"
echo "Verify:"
ls -la "$DST"
strings "$DST" | grep -E 'nv_apply|NV Display Left|pid_1033' | head -10
echo
echo "OK. Kill all wine/VDJ processes, then relaunch."
echo "  pkill -x virtualdj.exe; sleep 2"
echo "  NV_MODE=hybrid NV_FACADE_NAME_MODE=factory ~/bin/start-virtualdj.sh"
