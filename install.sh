#!/usr/bin/env bash
# Numark NV + VirtualDJ on Linux — installer (v1.1.0)
set -euo pipefail

if [[ -t 1 ]]; then
  B='\033[1m'; G='\033[32m'; Y='\033[33m'; R='\033[31m'; N='\033[0m'
else
  B=''; G=''; Y=''; R=''; N=''
fi
ok()   { echo -e "  ${G}✓${N} $*"; }
warn() { echo -e "  ${Y}!${N} $*"; }
bad()  { echo -e "  ${R}✗${N} $*"; }
step() { echo -e "\n${B}[$1]${N} $2"; }

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${NV_INSTALL_ROOT:-$HOME/src/nv-screens}"
BIN="${NV_BIN_DIR:-$HOME/bin}"
MISSING=()

cat <<'BANNER'

  Numark NV  +  VirtualDJ  on  Linux   (v1.1.0)
  Dual LCD + Controllers under Wine

BANNER

echo "  Install folder: ${B}$DEST${N}"
echo "  Shortcuts:      ${B}$BIN/start-virtualdj.sh${N}"
echo
read -r -p "  Ready? [Y/n] " ans
ans=${ans:-Y}
if [[ ! "$ans" =~ ^[Yy]$ ]]; then
  echo "  Cancelled."
  exit 0
fi

step 1/5 "Checking dependencies…"
have() { command -v "$1" >/dev/null 2>&1; }

if have python3; then ok "Python 3"; else bad "Python 3 missing"; MISSING+=("python3"); fi
if python3 -c "import usb.core" 2>/dev/null; then
  ok "PyUSB"
else
  bad "PyUSB missing"; MISSING+=("pyusb")
fi
if have wine || have wine64; then ok "Wine"; else warn "Wine not found"; MISSING+=("wine"); fi
if have bwrap; then ok "bubblewrap"; else warn "bubblewrap not found (optional)"; fi
if have aconnect && have amidi; then ok "ALSA MIDI tools"; else warn "alsa-utils recommended"; MISSING+=("alsa-utils"); fi

if ((${#MISSING[@]} > 0)); then
  echo
  warn "Missing: ${MISSING[*]}"
  if have dnf; then
    echo -e "    ${B}sudo dnf install wine python3-pyusb bubblewrap alsa-utils${N}"
  elif have apt; then
    echo -e "    ${B}sudo apt install wine python3-pyusb bubblewrap alsa-utils${N}"
  fi
  read -r -p "  Continue anyway? [y/N] " ans
  [[ "${ans:-N}" =~ ^[Yy]$ ]] || exit 1
fi

step 2/5 "Installing tree → $DEST"
mkdir -p "$DEST" "$BIN"
if [[ "$SRC" != "$DEST" ]]; then
  for d in bin nv_screens scripts config data wine-patch docs; do
    [[ -d "$SRC/$d" ]] || continue
    rm -rf "$DEST/$d"
    cp -a "$SRC/$d" "$DEST/"
    ok "copied $d"
  done
  # sudoers-compat wrappers
  if [[ -d "$SRC/tools" ]]; then
    rm -rf "$DEST/tools"
    cp -a "$SRC/tools" "$DEST/"
  fi
  for f in README.md LICENSE VERSION CHANGELOG.md install.sh; do
    [[ -f "$SRC/$f" ]] && cp -a "$SRC/$f" "$DEST/"
  done
else
  ok "Already in place at $DEST"
fi

step 3/5 "Shortcuts in $BIN"
install -m 0755 "$DEST/bin/start-virtualdj.sh" "$BIN/start-virtualdj.sh"
install -m 0755 "$DEST/bin/vdj-set-nv-audio.py" "$BIN/vdj-set-nv-audio.py"
if [[ "$DEST" != "$HOME/src/nv-screens" ]]; then
  sed -i "s|ROOT=\"\${ROOT:-\$HOME/src/nv-screens}\"|ROOT=\"\${ROOT:-$DEST}\"|" \
    "$BIN/start-virtualdj.sh"
fi
ok "start-virtualdj.sh"

mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/numark-nv-virtualdj.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VirtualDJ (Numark NV)
Comment=Start VirtualDJ with Numark NV screens + controls
Exec=$BIN/start-virtualdj.sh
Icon=wine
Terminal=false
Categories=AudioVideo;Audio;
Keywords=DJ;Numark;VirtualDJ;NV;
EOF
ok "Desktop entry"

step 4/5 "USB udev rules (optional password)…"
RULES_SRC="$DEST/config/udev/99-numark-nv.rules"
if [[ -f "$RULES_SRC" ]]; then
  if [[ -w /etc/udev/rules.d ]] 2>/dev/null; then
    cp -a "$RULES_SRC" /etc/udev/rules.d/99-numark-nv.rules
    udevadm control --reload-rules 2>/dev/null || true
    ok "udev rules installed"
  else
    echo "  sudo cp $RULES_SRC /etc/udev/rules.d/"
    echo "  sudo udevadm control --reload-rules && sudo udevadm trigger"
    read -r -p "  Run with sudo now? [Y/n] " ans
    ans=${ans:-Y}
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      sudo cp -a "$RULES_SRC" /etc/udev/rules.d/99-numark-nv.rules
      sudo udevadm control --reload-rules
      sudo udevadm trigger
      ok "udev rules installed"
    else
      warn "Skipped udev — you may need root for USB bulk"
    fi
  fi
fi

step 5/5 "Logo restore sudoers (optional)"
RESET="$DEST/scripts/usb-reset-nv.sh"
echo "  For passwordless logo restore on VDJ exit, add to sudoers:"
echo -e "    ${B}$USER ALL=(root) NOPASSWD: $RESET${N}"
echo "  (compat wrapper still at $DEST/tools/usb-reset-nv.sh)"

echo
ok "Install complete — version $(cat "$DEST/VERSION" 2>/dev/null || echo 1.1.0)"
echo
echo "  Start with:  ${B}start-virtualdj.sh${N}"
echo "  or:          ${B}$BIN/start-virtualdj.sh${N}"
echo
