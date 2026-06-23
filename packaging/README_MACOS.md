# macOS Packaging

The goal is to produce a normal macOS installer:

1. User downloads `DividendNotifier-mac-arm64.dmg`.
2. User opens the DMG.
3. User drags `Dividend Notifier.app` into `Applications`.
4. User double-clicks the app to use it.

## Build

From the repository root:

```bash
bash packaging/build_mac.sh
```

The script creates:

| File | Use |
| --- | --- |
| `packaging/dist/DividendNotifier-mac-arm64.dmg` | Recommended user installer. |
| `packaging/dist/DividendNotifier-mac-arm64.zip` | Backup archive for testing/release upload. |
| `packaging/dist/Dividend Notifier.app` | Raw app bundle for local inspection. |

## What Is Bundled

The packaged app includes:

- FastAPI backend
- Jinja2 pages and CSS
- SQLite support
- AkShare and report dependencies
- PyWebView desktop window

The packaged app does not include personal data, local databases, caches, reports,
or `.env` files.

## Runtime Data Location

Installed app data is stored here:

```text
~/Library/Application Support/Dividend Notifier/
```

Launcher logs are stored here:

```text
~/Library/Logs/Dividend Notifier/launcher.log
```

If the app does not open correctly, check the launcher log first.

## First Launch Notes

The app is currently ad-hoc signed, not notarized with an Apple Developer ID.
On a new Mac, macOS may show a security prompt. During local testing, right-click
the app and choose Open.

Before public distribution, consider Apple notarization to make first launch
smoother for non-technical users.
