#!/usr/bin/env bash
# Install custom DXVK (Linux shared textures) into a Wine prefix for VirtualDJ video.
# Portable: uses WINEPREFIX, no machine-specific paths.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DXVK_DIR="${NV_DXVK_DIR:-$ROOT/wine-stack/dxvk}"
WINEPREFIX="${WINEPREFIX:-$HOME/.wine}"
export WINEPREFIX

if [[ -t 1 ]]; then
  G='\033[32m'; Y='\033[33m'; R='\033[31m'; B='\033[1m'; N='\033[0m'
else
  G=''; Y=''; R=''; B=''; N=''
fi
ok()   { echo -e "  ${G}✓${N} $*"; }
warn() { echo -e "  ${Y}!${N} $*"; }
bad()  { echo -e "  ${R}✗${N} $*"; }

echo -e "${B}DXVK for VirtualDJ (video under Wine)${N}"
echo "  Prefix: $WINEPREFIX"
echo "  Source: $DXVK_DIR"
echo

if [[ ! -d "$WINEPREFIX/drive_c/windows/system32" ]]; then
  bad "Wine prefix not found at $WINEPREFIX"
  echo "  Create one first:  wineboot -u"
  echo "  Or set:            WINEPREFIX=/path/to/prefix $0"
  exit 1
fi

need=(d3d11.dll d3d9.dll d3d10core.dll dxgi.dll d3d8.dll)
for bit in x64 x32; do
  for f in "${need[@]}"; do
    if [[ ! -f "$DXVK_DIR/$bit/$f" ]]; then
      bad "Missing $DXVK_DIR/$bit/$f"
      echo "  Rebuild from wine-stack/dxvk/README.md or re-clone full repo."
      exit 1
    fi
  done
done

# Optional Vulkan check (soft)
if command -v vulkaninfo >/dev/null 2>&1; then
  if vulkaninfo --summary 2>/dev/null | grep -qi 'deviceName\|GPU'; then
    ok "Vulkan looks available"
  else
    warn "vulkaninfo ran but no GPU listed — video may fail"
  fi
else
  warn "vulkaninfo not installed (optional check)"
fi

SYS32="$WINEPREFIX/drive_c/windows/system32"
WOW64="$WINEPREFIX/drive_c/windows/syswow64"
mkdir -p "$SYS32"
[[ -d "$WOW64" ]] || mkdir -p "$WOW64"

echo "  Installing 64-bit DLLs → system32"
for f in "${need[@]}"; do
  install -m 0644 "$DXVK_DIR/x64/$f" "$SYS32/$f"
done
ok "x64 d3d8/d3d9/d3d10core/d3d11/dxgi"

if [[ -d "$WOW64" ]]; then
  echo "  Installing 32-bit DLLs → syswow64"
  for f in "${need[@]}"; do
    install -m 0644 "$DXVK_DIR/x32/$f" "$WOW64/$f"
  done
  ok "x32 d3d8/d3d9/d3d10core/d3d11/dxgi"
fi

# DLL overrides: native DXVK (not Wine builtin wined3d)
set_override() {
  local name="$1"
  if command -v wine >/dev/null 2>&1 || command -v wine64 >/dev/null 2>&1; then
    local WINEBIN
    WINEBIN=$(command -v wine64 2>/dev/null || command -v wine)
    # Quiet; Wine may spit fixme noise
    "$WINEBIN" reg add 'HKCU\Software\Wine\DllOverrides' /v "$name" /t REG_SZ /d native /f >/dev/null 2>&1 || true
    "$WINEBIN" reg add 'HKCU\Software\Wine\DllOverrides' /v "*$name" /t REG_SZ /d native /f >/dev/null 2>&1 || true
  fi
}

echo "  Setting Wine DLL overrides (native)"
for name in d3d8 d3d9 d3d10core d3d11 dxgi; do
  set_override "$name"
done
ok "DllOverrides → native for d3d* / dxgi"

# User config (do not clobber a custom one)
CONF_DST="${XDG_CONFIG_HOME:-$HOME/.config}/dxvk.conf"
mkdir -p "$(dirname "$CONF_DST")"
if [[ -f "$CONF_DST" ]]; then
  ok "Keeping existing $CONF_DST"
else
  install -m 0644 "$DXVK_DIR/dxvk.conf" "$CONF_DST"
  ok "Wrote $CONF_DST"
fi

# Also drop a copy next to VDJ if present (some setups look at cwd)
for vdjdir in \
  "$WINEPREFIX/drive_c/Program Files/VirtualDJ" \
  "$WINEPREFIX/drive_c/Program Files (x86)/VirtualDJ"
do
  if [[ -d "$vdjdir" ]]; then
    install -m 0644 "$DXVK_DIR/dxvk.conf" "$vdjdir/dxvk.conf" 2>/dev/null || true
  fi
done

echo
ok "DXVK installed for this Wine prefix"
echo "  Prove it:  DXVK_HUD=1 wine \"\$WINEPREFIX/drive_c/Program Files/VirtualDJ/virtualdj.exe\""
echo "  (HUD text in the corner means DXVK is active, not wined3d)"
echo
