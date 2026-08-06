# Branches

| Branch | Who | Purpose |
|--------|-----|---------|
| **main** | End users | Stable. Clone/download this. Tags and releases only from here. |
| **staging** | Development | Experiments, fixes, new features. May move fast or break. |

## Users

```bash
git clone https://github.com/shaneodoo/NumarkNV_Screens_VDJ_Linux.git
# defaults to main
```

Or download a **Release** — those track main.

## Development

Work on **staging** only. Promote to main when something is ready for everyone:

```bash
git checkout staging
# … commit work …
git push origin staging

# When ready for users:
git checkout main
git merge staging
git push origin main
# optional: tag a release
```

Do **not** push day-to-day work straight to main.
