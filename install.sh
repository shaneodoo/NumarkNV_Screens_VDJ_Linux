#!/usr/bin/env bash
# =============================================================================
#  Numark NV + VirtualDJ on Linux — simple installer
#
#  Double-click in a terminal, or run:
#      ./install.sh
#
#  That's it. The script explains each step.
# =============================================================================
set -euo pipefail

# Pretty output (works without color too)
if [[ -t 1 ]]; then
  B='\033[1m'; G='\033[32m'; Y='\033[33m'; R='\033[31m'; N='\033[0m'
else
  B=''; G=''; Y=''; R=''; N=''
fi
ok()   { echo -e "  ${G}✓${N} $*"; }
warn() { echo -e "  ${Y}!${N} $*"; }
bad()  { echo -e "  ${R}✗${N} $*"; }
step() { echo -e "\n${B}[$1]${N} $2"; }
pause() {
  echo
  read -r -p "  Press Enter to continue (or Ctrl+C to stop)… " _
}

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${NV_INSTALL_ROOT:-$HOME/src/nv-screens}"
BIN="${NV_BIN_DIR:-$HOME/bin}"
NEED_SUDO=0
MISSING=()

clear 2>/dev/null || true
cat <<'BANNER'

  ╔══════════════════════════════════════════════════════╗
  ║     Numark NV  +  VirtualDJ  on  Linux               ║
  ║     Simple installer                                 ║
  ╚══════════════════════════════════════════════════════╝

  This will set up the dual LCD + controller bridge so
  VirtualDJ (Wine) can drive your Numark NV.

  You still need:
    • A Numark NV plugged in (or plug it in later)
    • VirtualDJ for Windows already installed in Wine
      (or install it after this script)

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

# -----------------------------------------------------------------------------
step 1/6 "Checking your computer…"
# -----------------------------------------------------------------------------

have() { command -v "$1" >/dev/null 2>&1; }

if have python3; then ok "Python 3 found"; else bad "Python 3 missing"; MISSING+=("python3"); fi

if python3 -c "import usb.core" 2>/dev/null; then
  ok "PyUSB found (talks to the NV over USB)"
else
  bad "PyUSB missing"
  MISSING+=("pyusb")
fi

if have wine || have wine64; then
  ok "Wine found"
else
  warn "Wine not found yet — install Wine, then install VirtualDJ (Windows) into it"
  MISSING+=("wine")
fi

if have bwrap; then
  ok "bubblewrap found (loads MIDI fix without changing system Wine files)"
  USE_BWRAP=1
else
  warn "bubblewrap not found — we can still install, but may need a one-time Wine library copy"
  USE_BWRAP=0
fi

if have aconnect && have amidi; then
  ok "ALSA MIDI tools found"
else
  warn "ALSA tools (aconnect/amidi) missing — install alsa-utils"
  MISSING+=("alsa-utils")
fi

# Suggest packages
if ((${#MISSING[@]} > 0)); then
  echo
  warn "Some pieces are missing. On many systems you can run:"
  if have dnf; then
    echo -e "    ${B}sudo dnf install wine python3-pyusb bubblewrap alsa-utils${N}"
  elif have apt; then
    echo -e "    ${B}sudo apt install wine python3-pyusb bubblewrap alsa-utils${N}"
    echo "    (package names may vary slightly by distro)"
  elif have pacman; then
    echo -e "    ${B}sudo pacman -S wine python-pyusb bubblewrap alsa-utils${N}"
  else
    echo "    Install: wine, python3, pyusb, bubblewrap, alsa-utils"
  fi
  echo
  echo "  For PyUSB only:  python3 -m pip install --user pyusb"
  echo
  read -r -p "  Continue anyway? [y/N] " ans
  if [[ ! "${ans:-N}" =~ ^[Yy]$ ]]; then
    echo "  Install the packages above, then run ./install.sh again."
    exit 1
  fi
fi

# -----------------------------------------------------------------------------
step 2/6 "Copying the NV software into your home folder…"
# -----------------------------------------------------------------------------

mkdir -p "$DEST" "$BIN"
for d in tools2 src2 tools wine-patch captures vdj-devices udev docs; do
  [[ -d "$SRC/$d" ]] || continue
  rm -rf "$DEST/$d"
  cp -a "$SRC/$d" "$DEST/"
  ok "copied $d"
done
cp -a "$SRC/README.md" "$SRC/INSTALL.md" "$SRC/FILE-LIST.md" "$DEST/" 2>/dev/null || true
ok "Files are in $DEST"

# -----------------------------------------------------------------------------
step 3/6 "Installing the start button…"
# -----------------------------------------------------------------------------

install -m 0755 "$SRC/bin/start-virtualdj.sh" "$BIN/start-virtualdj.sh"
install -m 0755 "$SRC/bin/vdj-set-nv-audio.py" "$BIN/vdj-set-nv-audio.py"

if [[ "$DEST" != "$HOME/src/nv-screens" ]]; then
  sed -i "s|ROOT=\"\${ROOT:-\$HOME/src/nv-screens}\"|ROOT=\"\${ROOT:-$DEST}\"|" \
    "$BIN/start-virtualdj.sh"
fi

# PATH hint
if [[ ":$PATH:" != *":$BIN:"* ]]; then
  warn "$BIN is not on your PATH — the desktop icon still works"
  if [[ -f "$HOME/.bashrc" ]] && ! grep -q 'HOME/bin' "$HOME/.bashrc" 2>/dev/null; then
    read -r -p "  Add ~/bin to PATH in .bashrc? [Y/n] " ans
    ans=${ans:-Y}
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      echo '' >> "$HOME/.bashrc"
      echo '# Numark NV / user scripts' >> "$HOME/.bashrc"
      echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
      ok "Added to ~/.bashrc (open a new terminal to use it)"
    fi
  fi
else
  ok "~/bin is on your PATH"
fi

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
ok "App menu entry: VirtualDJ (Numark NV)"

# Kill old bad autostart
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/numark-nv-midi.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Numark NV MIDI Wire
Exec=/bin/true
Hidden=true
X-GNOME-Autostart-enabled=false
EOF
ok "Disabled old MIDI rewire autostart (if any)"

# -----------------------------------------------------------------------------
step 4/6 "USB permissions (needs your password once)…"
# -----------------------------------------------------------------------------

if [[ -f "$SRC/udev/99-numark-nv.rules" ]]; then
  if [[ -w /etc/udev/rules.d/99-numark-nv.rules ]] 2>/dev/null; then
    cp -a "$SRC/udev/99-numark-nv.rules" /etc/udev/rules.d/99-numark-nv.rules
    ok "udev rules installed"
  else
    echo "  We need admin rights so the NV is usable without root."
    if have sudo; then
      if sudo cp -a "$SRC/udev/99-numark-nv.rules" /etc/udev/rules.d/99-numark-nv.rules; then
        sudo udevadm control --reload-rules 2>/dev/null || true
        sudo udevadm trigger 2>/dev/null || true
        ok "udev rules installed"
      else
        warn "Could not install udev rules — re-run later:"
        echo "    sudo cp $SRC/udev/99-numark-nv.rules /etc/udev/rules.d/"
      fi
    else
      warn "No sudo — install rules yourself as root (see INSTALL.md)"
    fi
  fi
fi

# groups
if have groups; then
  g=$(groups)
  if [[ "$g" != *audio* ]] || [[ "$g" != *plugdev* ]]; then
    warn "For best results, add yourself to groups audio + plugdev, then log out/in:"
    echo -e "    ${B}sudo usermod -aG audio,plugdev $USER${N}"
  else
    ok "User groups look fine"
  fi
fi

# -----------------------------------------------------------------------------
step 5/6 "Wine audio + VirtualDJ extras…"
# -----------------------------------------------------------------------------

if have wine; then
  wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /t REG_SZ /d alsa /f >/dev/null 2>&1 \
    && ok "Wine set to use ALSA audio (needed for NV sound)" \
    || warn "Could not set Wine audio registry (ok if Wine not fully set up yet)"
else
  warn "Skipped Wine settings (install Wine first)"
fi

VDJ_EXE="$HOME/.wine/drive_c/Program Files/VirtualDJ/virtualdj.exe"
VDJ_DEV="$HOME/.wine/drive_c/users/$USER/AppData/Local/VirtualDJ/Devices"
if [[ -f "$VDJ_EXE" ]]; then
  ok "VirtualDJ found under Wine"
  mkdir -p "$VDJ_DEV"
  cp -a "$SRC/vdj-devices/Numark_NV_Audio.xml" "$VDJ_DEV/" 2>/dev/null && \
    ok "Installed optional NUMARK NV audio helper" || true
else
  warn "VirtualDJ not found yet at:"
  echo "    $VDJ_EXE"
  echo "  Install VirtualDJ (Windows) with Wine, then you can re-run this installer"
  echo "  or just start DJ — the LCD host still works once VDJ is installed."
fi

# Optional system winealsa if no bwrap
if [[ "$USE_BWRAP" -eq 0 ]]; then
  echo
  warn "No bubblewrap — the MIDI fix can be installed into Wine system-wide (with backup)."
  read -r -p "  Install patched winealsa into the system Wine? [y/N] " ans
  if [[ "${ans:-N}" =~ ^[Yy]$ ]]; then
    if [[ -x "$DEST/tools/install-winealsa-nv.sh" ]]; then
      bash "$DEST/tools/install-winealsa-nv.sh" "$DEST/wine-patch/x86_64-unix/winealsa.so" \
        && ok "System winealsa updated (backup created)" \
        || warn "System winealsa install failed — see docs"
    fi
  fi
fi

# -----------------------------------------------------------------------------
step 6/6 "Checking the Numark NV…"
# -----------------------------------------------------------------------------

if have lsusb; then
  if lsusb 2>/dev/null | grep -qi '15e4'; then
    ok "Numark device(s) seen on USB:"
    lsusb 2>/dev/null | grep -i '15e4' | sed 's/^/    /'
  else
    warn "No Numark NV seen yet — plug it in (and unplug/replug after udev install)"
  fi
else
  warn "lsusb not available; skip hardware check"
fi

# -----------------------------------------------------------------------------
echo
echo -e "${B}══════════════════════════════════════════════════════${N}"
echo -e "${B}  All set!${N}"
echo -e "${B}══════════════════════════════════════════════════════${N}"
echo
echo "  How to start every time:"
echo
echo -e "    ${G}1.${N} Plug in the Numark NV"
echo -e "    ${G}2.${N} Run:  ${B}start-virtualdj.sh${N}"
echo "       or open  “VirtualDJ (Numark NV)”  from your app menu"
echo
echo "  First time in VirtualDJ:"
echo "    • Controllers should show Numark NV + Display Left + Display Right"
echo "    • Load a track — both screens should paint"
echo "    • Audio: pick NV Audio if it appears (master 1–2, phones 3–4)"
echo
echo "  Logs if something’s wrong:"
echo "    tail -f /tmp/nv-screens-live.log"
echo
echo "  More help:"
echo "    $DEST/INSTALL.md"
echo "    $DEST/docs/TROUBLESHOOTING.md"
echo
read -r -p "  Start VirtualDJ + NV now? [y/N] " ans
if [[ "${ans:-N}" =~ ^[Yy]$ ]]; then
  if [[ ! -f "$VDJ_EXE" ]]; then
    bad "VirtualDJ is not installed under Wine yet."
    echo "  Install it, then run:  start-virtualdj.sh"
    exit 0
  fi
  echo "  Launching…"
  exec "$BIN/start-virtualdj.sh"
fi

echo "  When you’re ready:  start-virtualdj.sh"
echo
exit 0
