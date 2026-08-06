# Install — VirtualDJ on Linux (NV screens + video)

## What you need

| Item | Notes |
|------|--------|
| Linux PC | Fedora, Ubuntu, Arch, … |
| Wine | Wine or Wine Staging |
| VirtualDJ | Install under Wine from virtualdj.com |
| Vulkan | GPU drivers that work with DXVK (for video) |
| Python 3 + pyusb | LCD host |
| alsa-utils | `aconnect` / `amidi` |
| Numark NV | For dual hardware LCDs (optional if you only want VDJ video) |

## 1. Packages

**Fedora**

```bash
sudo dnf install wine python3-pyusb bubblewrap alsa-utils git vulkan-tools
```

**Ubuntu / Debian / Zorin**

```bash
sudo apt update
sudo apt install wine python3-pyusb bubblewrap alsa-utils git vulkan-tools
```

**Arch**

```bash
sudo pacman -S wine python-pyusb bubblewrap alsa-utils git vulkan-tools
```

Install your vendor Vulkan driver (Mesa / NVIDIA / AMD) the usual way for your distro.

If pyusb is missing: `python3 -m pip install --user pyusb`

## 2. VirtualDJ under Wine (once)

```bash
wineboot -u   # if you have no prefix yet
wine ~/Downloads/install_virtualdj.exe   # path may vary
```

Default:

`~/.wine/drive_c/Program Files/VirtualDJ/virtualdj.exe`

**64-bit VirtualDJ** is recommended (this is what the DXVK x64 stack targets).

## 3. Clone and install

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux.git
cd NumarkNV_Screens_VDJ_Linux
./install.sh
```

Answer **Y** for DXVK when asked (enables deck video / karaoke under Wine).

### What install.sh does

| Step | Action |
|------|--------|
| Tree | Copies to `~/src/nv-screens` by default |
| Launcher | `~/bin/start-virtualdj.sh` + app menu |
| **DXVK** | Native d3d11/d3d9/dxgi into your Wine prefix |
| udev | USB rules for NV bulk LCD (optional password) |
| Hint | sudoers line for logo restore on quit |

### Useful env vars

| Variable | Meaning |
|----------|---------|
| `WINEPREFIX` | Which Wine bottle gets DXVK (default `~/.wine`) |
| `NV_INSTALL_ROOT` | Where files are copied (default `~/src/nv-screens`) |
| `NV_BIN_DIR` | Where the launcher goes (default `~/bin`) |
| `NV_INSTALL_DXVK=0` | Skip video DLL install |
| `NV_INSTALL_YES=1` | Non-interactive (yes to prompts) |

## 4. DXVK only (video, any prefix)

If you already installed the tree:

```bash
export WINEPREFIX=$HOME/.wine
~/src/nv-screens/scripts/install-dxvk.sh
```

Prove DXVK is active:

```bash
DXVK_HUD=1 start-virtualdj.sh
```

You should see a small DXVK overlay (fps / device), not a blank wined3d fail for video.

## 5. USB permissions (Numark NV)

```bash
sudo cp config/udev/99-numark-nv.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and replug the NV once.

## 6. Logos on quit (optional)

```bash
sudo visudo
```

```text
YOURUSER ALL=(root) NOPASSWD: /home/YOURUSER/src/nv-screens/scripts/usb-reset-nv.sh
```

## 7. Start

- App menu → **VirtualDJ (Numark NV)**  
- Or: `start-virtualdj.sh` / `~/bin/start-virtualdj.sh`

## Everyday

| Action | How |
|--------|-----|
| Start | `start-virtualdj.sh` |
| Stop | Quit VirtualDJ |
| NV LCD logs | `~/.local/state/nv-screens/` (capped ~1 MiB; CSV off unless `NV_CSV_LOG=1`) |
| Re-apply DXVK | `scripts/install-dxvk.sh` |

## Troubleshooting

| Problem | Try |
|---------|-----|
| No deck video / black video | Run `scripts/install-dxvk.sh`. Check Vulkan. `DXVK_HUD=1`. |
| Virtual DJ screen glitching | In VDJ open settings > Options, Search for 'experimentalSkinEngine' set to NO |
| NV Screens stay on logo | Host running? udev? `screens-live.log`. Replug NV. |
| No controllers | `aconnect -l` — look for `nv-screens`. |
| No sound | VDJ audio → NV Audio / ALSA. |
| DXVK install: no prefix | Install VDJ under Wine first, then re-run `./install.sh` or `install-dxvk.sh`. |
| App menu wrong path | Re-run `./install.sh`. |

## Upgrade

```bash
cd ~/src/NumarkNV_Screens_VDJ_Linux
git pull
./install.sh
```

## Not supported officially

Atomix does not ship this. Wine can change; re-run install after big Wine upgrades if video or audio acts up.
