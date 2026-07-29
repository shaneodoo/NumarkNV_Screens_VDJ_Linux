#!/usr/bin/env bash
# Clear VDJ custom SIMPLE_MIDI mappers that steal factory display bind,
# and backup mapper XML. Safe to re-run.
set -euo pipefail
WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
VDJ="$WINEPREFIX/drive_c/users/$USER/AppData/Local/VirtualDJ"
SETTINGS="$VDJ/settings.xml"
MAP="$VDJ/Mappers"
BAK="$VDJ/Mappers/backup-simple-midi-$(date +%Y%m%d-%H%M%S)"

if [[ ! -f "$SETTINGS" ]]; then
  echo "No settings.xml at $SETTINGS"
  exit 1
fi

python3 - "$SETTINGS" <<'PY'
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
t = p.read_text(encoding="utf-8", errors="replace")
orig = t
# Drop SIMPLE_MIDI customization lines (keep NMNV)
t2, n = re.subn(
    r'\s*<controller\s+name="SIMPLE_MIDI[^"]*"[^/]*/>\s*',
    "\n",
    t,
)
# Also clear empty custom mappers glued to NV ports if present
t2, n2 = re.subn(
    r'\s*<controller\s+name="NV (Audio|Graphics|Display)[^"]*"[^>]*mapper="[^"]*custom[^"]*"[^/]*/>\s*',
    "\n",
    t2,
    flags=re.I,
)
if t2 != orig:
    p.write_text(t2, encoding="utf-8")
    print(f"settings.xml: removed SIMPLE_MIDI/custom display lines (simple={n} display={n2})")
else:
    print("settings.xml: no SIMPLE_MIDI controller lines to remove")
PY

mkdir -p "$BAK"
shopt -s nullglob
moved=0
for f in "$MAP"/SIMPLE_MIDI*.xml "$MAP"/*custom*mapping*.xml; do
  [[ -f "$f" ]] || continue
  # keep Numark NV custom if any, only move SIMPLE_MIDI
  base=$(basename "$f")
  if [[ "$base" == SIMPLE_MIDI* ]]; then
    mv -f "$f" "$BAK/"
    moved=$((moved + 1))
  fi
done
echo "Moved $moved SIMPLE_MIDI mapper XML → $BAK"
ls -la "$VDJ/Devices/" 2>/dev/null || true
# Ensure no shadowing display device XML
rm -f "$VDJ/Devices"/NMNV_Display*.xml "$VDJ/Devices"/NMNV_Graphics.xml \
  "$VDJ/Devices"/*Display*Left*.xml "$VDJ/Devices"/*Display*Right*.xml 2>/dev/null || true
echo "Devices/ left:"
ls -la "$VDJ/Devices/" 2>/dev/null || true
echo "Done. Fully restart VirtualDJ."
