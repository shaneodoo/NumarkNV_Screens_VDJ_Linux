# v1.1.1 — Left LCD browser stability

## Fixed
- Left LCD list twitch / double highlight between selected track and row below
- Browse MIDI inject spam (selection blip); mouse inject off unless `NV_MOUSE_LIBRARY_INJECT=1`
- Confident scroll only; highlight-only updates no longer reverse-guess the list

## Upgrade
```bash
git pull
./install.sh   # optional
start-virtualdj.sh
```

Full notes: [CHANGELOG.md](CHANGELOG.md)
