#!/usr/bin/env bash
# Install VirtualDJ on Linux glue: Numark NV screens + optional DXVK video stack.
# Absolute paths, per-user desktop and logs. Portable (no host-specific paths).
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
WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEPREFIX
DEST="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$DEST")"
BIN="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$BIN")"
MISSING=()
AUTO_YES="${NV_INSTALL_YES:-}"
# Install DXVK video stack by default if present (NV_INSTALL_DXVK=0 to skip)
INSTALL_DXVK="${NV_INSTALL_DXVK:-1}"

ask_yn() {
  local prompt="$1" def="${2:-Y}" ans
  if [[ -n "$AUTO_YES" ]]; then
    [[ "$AUTO_YES" =~ ^[Yy1] ]] && return 0 || return 1
  fi
  if [[ ! -t 0 ]]; then
    [[ "$def" == "Y" ]] && return 0 || return 1
  fi
  read -r -p "  $prompt" ans
  ans=${ans:-$def}
  [[ "$ans" =~ ^[Yy]$ ]]
}

VER="$(cat "$SRC/VERSION" 2>/dev/null || echo 1.2.0)"

cat <<BANNER

  VirtualDJ on Linux  (v${VER})
  Numark NV dual LCD + controllers + video (DXVK)

BANNER

echo "  Install folder: ${B}$DEST${N}"
echo "  Launcher:       ${B}$BIN/start-virtualdj.sh${N}"
echo "  Wine prefix:    ${B}$WINEPREFIX${N}"
echo "  App menu:       VirtualDJ (Numark NV)"
echo
if ! ask_yn "Ready? [Y/n] " Y; then
  echo "  Cancelled."
  exit 0
fi

step 1/6 "Checking dependencies…"
have() { command -v "$1" >/dev/null 2>&1; }

if have python3; then ok "Python 3"; else bad "Python 3 missing"; MISSING+=("python3"); fi
if python3 -c "import usb.core" 2>/dev/null; then
  ok "PyUSB"
else
  bad "PyUSB missing"; MISSING+=("pyusb")
fi
if have wine || have wine64; then ok "Wine"; else warn "Wine not found"; MISSING+=("wine"); fi
if have bwrap; then ok "bubblewrap"; else warn "bubblewrap not found (optional winealsa bind)"; fi
if have aconnect && have amidi; then ok "ALSA MIDI tools"; else warn "alsa-utils recommended"; MISSING+=("alsa-utils"); fi
if have vulkaninfo; then ok "vulkaninfo present"; else warn "Vulkan tools optional (needed for VDJ video)"; fi

if ((${#MISSING[@]} > 0)); then
  echo
  warn "Missing: ${MISSING[*]}"
  if have dnf; then
    echo -e "    ${B}sudo dnf install wine python3-pyusb bubblewrap alsa-utils vulkan-tools${N}"
  elif have apt; then
    echo -e "    ${B}sudo apt install wine python3-pyusb bubblewrap alsa-utils vulkan-tools${N}"
  elif have pacman; then
    echo -e "    ${B}sudo pacman -S wine python-pyusb bubblewrap alsa-utils vulkan-tools${N}"
  fi
  if ! ask_yn "Continue anyway? [y/N] " N; then
    exit 1
  fi
fi

step 2/6 "Installing tree → $DEST"
mkdir -p "$DEST" "$BIN"
if [[ "$SRC" != "$DEST" ]]; then
  for d in bin nv_screens scripts config data wine-patch tools wine-stack; do
    [[ -d "$SRC/$d" ]] || continue
    rm -rf "$DEST/$d"
    cp -a "$SRC/$d" "$DEST/"
    ok "copied $d"
  done
  for f in README.md LICENSE VERSION CHANGELOG.md INSTALL.md install.sh; do
    [[ -f "$SRC/$f" ]] && cp -a "$SRC/$f" "$DEST/"
  done
else
  ok "Already in place at $DEST"
fi

chmod +x "$DEST/bin/start-virtualdj.sh" "$DEST/bin/nv-screens" 2>/dev/null || true
find "$DEST/bin" "$DEST/scripts" "$DEST/tools" -type f 2>/dev/null | while read -r f; do
  head -1 "$f" 2>/dev/null | grep -q '^#!' && chmod +x "$f" || true
done

step 3/6 "Shortcuts in $BIN"
cat > "$BIN/start-virtualdj.sh" <<WRAP
#!/usr/bin/env bash
# Installed by install.sh — re-run install.sh to refresh
export ROOT="$DEST"
exec "$DEST/bin/start-virtualdj.sh" "\$@"
WRAP
chmod 0755 "$BIN/start-virtualdj.sh"
ok "start-virtualdj.sh → $DEST/bin/start-virtualdj.sh"

install -m 0755 "$DEST/bin/vdj-set-nv-audio.py" "$BIN/vdj-set-nv-audio.py"
ok "vdj-set-nv-audio.py"

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
DESKTOP="$APPS/numark-nv-virtualdj.desktop"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=VirtualDJ (Numark NV)
GenericName=DJ Software
Comment=VirtualDJ under Wine — Numark NV dual LCDs + controllers
Exec=$BIN/start-virtualdj.sh
TryExec=$BIN/start-virtualdj.sh
Path=$DEST
Icon=audio-headphones
Terminal=false
StartupNotify=true
Categories=AudioVideo;Audio;Player;
Keywords=DJ;Numark;VirtualDJ;NV;Wine;
EOF
chmod 0644 "$DESKTOP"
ok "Desktop entry → $DESKTOP"

if have update-desktop-database; then
  update-desktop-database "$APPS" 2>/dev/null || true
fi

case ":$PATH:" in
  *":$BIN:"*) ok "$BIN is on PATH" ;;
  *)
    warn "$BIN is not on PATH yet"
    echo "    Add to ~/.bashrc:  export PATH=\"$BIN:\$PATH\""
    echo "    Or always run:     $BIN/start-virtualdj.sh"
    ;;
esac

step 4/6 "DXVK video stack (deck video / karaoke under Wine)…"
DXVK_SCRIPT="$DEST/scripts/install-dxvk.sh"
if [[ "$INSTALL_DXVK" == "0" || "$INSTALL_DXVK" == "no" ]]; then
  warn "Skipped DXVK (NV_INSTALL_DXVK=0)"
elif [[ ! -x "$DXVK_SCRIPT" && ! -f "$DXVK_SCRIPT" ]]; then
  warn "No install-dxvk.sh — video stack not in this tree"
elif [[ ! -d "$DEST/wine-stack/dxvk/x64" ]]; then
  warn "No prebuilt DXVK DLLs at wine-stack/dxvk/x64 — skip video stack"
elif [[ ! -d "$WINEPREFIX/drive_c/windows/system32" ]]; then
  warn "No Wine prefix at $WINEPREFIX yet"
  echo "    Install VirtualDJ under Wine first, then run:"
  echo "      WINEPREFIX=$WINEPREFIX $DXVK_SCRIPT"
elif ask_yn "Install DXVK for VDJ video in $WINEPREFIX? [Y/n] " Y; then
  bash "$DXVK_SCRIPT" || warn "DXVK install reported errors — check Wine prefix"
else
  warn "Skipped DXVK"
fi

step 5/6 "USB udev rules (optional password)…"
RULES_SRC="$DEST/config/udev/99-numark-nv.rules"
if [[ -f "$RULES_SRC" ]]; then
  if [[ -f /etc/udev/rules.d/99-numark-nv.rules ]]; then
    ok "udev rules already present"
  elif [[ -w /etc/udev/rules.d ]] 2>/dev/null; then
    cp -a "$RULES_SRC" /etc/udev/rules.d/99-numark-nv.rules
    udevadm control --reload-rules 2>/dev/null || true
    ok "udev rules installed"
  else
    echo "  Manual (if needed later):"
    echo "    sudo cp $RULES_SRC /etc/udev/rules.d/"
    echo "    sudo udevadm control --reload-rules && sudo udevadm trigger"
    if [[ -z "$AUTO_YES" ]] && [[ -t 0 ]] && ask_yn "Run with sudo now? [Y/n] " Y; then
      if sudo cp -a "$RULES_SRC" /etc/udev/rules.d/99-numark-nv.rules \
        && sudo udevadm control --reload-rules \
        && sudo udevadm trigger; then
        ok "udev rules installed"
      else
        warn "sudo udev install failed — run the commands above later"
      fi
    else
      warn "Skipped udev for now — you may need root for USB bulk"
    fi
  fi
fi

step 6/6 "Logo restore sudoers (optional)"
RESET="$DEST/scripts/usb-reset-nv.sh"
echo "  For passwordless logo restore on VDJ exit, add to sudoers:"
echo -e "    ${B}$USER ALL=(root) NOPASSWD: $RESET${N}"
echo "  (compat wrapper: $DEST/tools/usb-reset-nv.sh)"

STATE="${XDG_STATE_HOME:-$HOME/.local/state}/nv-screens"
mkdir -p "$STATE" 2>/dev/null || true

echo
ok "Install complete — version $(cat "$DEST/VERSION" 2>/dev/null || echo "$VER")"
echo
echo "  What you have:"
echo "    • Numark NV dual LCD host + launcher"
echo "    • Optional DXVK (video in VDJ under Wine)"
echo "    • winealsa patch bind (if wine-patch present)"
echo
echo "  Start:"
echo -e "    ${B}$BIN/start-virtualdj.sh${N}"
echo "  or app menu:  ${B}VirtualDJ (Numark NV)${N}"
echo
echo "  Video check:  DXVK_HUD=1 $BIN/start-virtualdj.sh"
echo "  Logs:         $STATE/screens-live.log"
echo "                $STATE/midi-connect.log"
echo
