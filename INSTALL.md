# Install (simple)

## One command

```bash
chmod +x install.sh
./install.sh
```

The script will:

1. Check Python, Wine, USB tools  
2. Copy the NV software into `~/src/nv-screens`  
3. Put **start-virtualdj.sh** in `~/bin`  
4. Add an app menu entry: **VirtualDJ (Numark NV)**  
5. Install USB permissions (asks for your password)  
6. Optionally offer to launch DJ when done  

## After install

1. Plug in the Numark NV  
2. Open **VirtualDJ (Numark NV)** from the menu  
   (or run `start-virtualdj.sh`)  

## First time in VirtualDJ

- Controllers: **Numark NV**, **NV Display Left**, **NV Display Right**  
- Load a track → screens should update  
- Audio: choose **NV Audio** if listed (master 1–2, phones 3–4)  

## If something is missing

**Fedora**

```bash
sudo dnf install wine python3-pyusb bubblewrap alsa-utils
```

**Ubuntu / Debian**

```bash
sudo apt install wine python3-pyusb bubblewrap alsa-utils
```

Also:

```bash
sudo usermod -aG audio,plugdev $USER
# then log out and back in
```

## Uninstall

```bash
pkill -f tools2/nv_screens.py 2>/dev/null || true
rm -rf ~/src/nv-screens
rm -f ~/bin/start-virtualdj.sh ~/bin/vdj-set-nv-audio.py
rm -f ~/.local/share/applications/numark-nv-virtualdj.desktop
sudo rm -f /etc/udev/rules.d/99-numark-nv.rules
```

More help: `docs/TROUBLESHOOTING.md`
