# DXVK for VirtualDJ on Linux

Prebuilt DXVK with **Linux shared-texture support** so 64-bit VirtualDJ can show
video (deck video, karaoke, stems UI), which stock Wine/DXVK often cannot.

## What we changed

Stock DXVK stubs shared D3D resources on Linux (`OpenSharedResource`, KMT
handles). VDJ video uses those. This build implements a Linux registry + FD path
so shared textures work under Wine.

Patch: `patches/dxvk-linux-shared-res.patch` (apply on upstream DXVK to rebuild).

## Install

Usually done by the top-level `./install.sh` (step “DXVK / video”).

Manual:

```bash
export WINEPREFIX="$HOME/.wine"
./scripts/install-dxvk.sh
```

## Needs

- Wine prefix with VirtualDJ installed
- Working **Vulkan** driver (`vulkaninfo` should list a GPU)
- 64-bit VirtualDJ recommended

## Rebuild (optional)

```bash
git clone https://github.com/doitsujin/dxvk.git
cd dxvk
patch -p1 < /path/to/patches/dxvk-linux-shared-res.patch
./package-release.sh master /tmp/dxvk-out
# copy /tmp/dxvk-out/dxvk-*/x64 and x32 into this folder
```

Requires mingw-w64 + meson + glslang (see upstream DXVK README).

## License

DXVK is zlib-licensed. See upstream LICENSE. This folder redistributes binaries
built from patched DXVK for Linux VDJ users.
