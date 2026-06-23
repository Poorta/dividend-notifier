# Project Structure

This project is split into source code, local user data, generated reports, and
macOS packaging files. Keep those areas separate so the app is easier to debug,
package, and share later.

## Top-Level Folders

| Path | Purpose | Commit to Git? |
| --- | --- | --- |
| `app/` | Main application code: API, UI templates, data services, reports, database models. | Yes |
| `scripts/` | Developer/automation entry points, such as running the daily job or demo generation. | Yes |
| `tests/` | Automated tests. | Yes |
| `packaging/` | macOS app launcher, PyInstaller spec, and build script. | Yes, except generated build output |
| `data/` | Local development database and market-data cache. | Keep only `.gitkeep` |
| `output/` | Generated Excel/PDF reports during source-mode development. | Keep only `.gitkeep` |
| `logs/` | Local development logs. | Keep only `.gitkeep` |
| `.venv-build/` | Local Python environment for packaging. | No |
| `.cache-build/` | Local pip/PyInstaller cache used by packaging. | No |
| `private_backup_before_release*/` | Personal backup created before earlier release work. | No |

## Application Code Layout

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI routes, page rendering, settings APIs, refresh/report endpoints. |
| `app/paths.py` | Central path rules for source mode vs packaged app mode. |
| `app/config.py` | Loads environment/default settings. |
| `app/models/` | SQLite tables and database initialization/migrations. |
| `app/services/` | Business logic: fetching market data, screening stocks, settings, AI picker, watchlist, mail. |
| `app/reports/` | Excel and PDF report generation. |
| `app/templates/` | Jinja2 HTML pages. |
| `app/static/` | CSS and frontend static assets. |
| `app/utils/` | Shared helpers such as logging and colors. |

## Data Isolation Rules

### Source Mode

When running from source, writable data stays in the repository so development is
easy to inspect:

| Data Type | Source-Mode Path |
| --- | --- |
| SQLite database | `data/dividend_notifier.db` |
| market-data cache | `data/cache/` |
| generated reports | `output/` |
| app logs | `logs/` |

### Packaged macOS App

When running as the installed `.app`, writable data moves out of the app bundle
and into the current user's Application Support folder:

| Data Type | Packaged-App Path |
| --- | --- |
| SQLite database | `~/Library/Application Support/Dividend Notifier/data/dividend_notifier.db` |
| market-data cache | `~/Library/Application Support/Dividend Notifier/data/cache/` |
| generated reports | `~/Library/Application Support/Dividend Notifier/output/` |
| app logs | `~/Library/Application Support/Dividend Notifier/logs/` |
| launcher logs | `~/Library/Logs/Dividend Notifier/launcher.log` |

This means the installed app can be replaced or deleted without losing user
settings, reports, and cache. To reset the app completely, quit the app and
delete `~/Library/Application Support/Dividend Notifier`.

## Packaging Output

`bash packaging/build_mac.sh` creates local build artifacts in:

| Path | Purpose |
| --- | --- |
| `packaging/dist/Dividend Notifier.app` | The raw macOS app bundle. |
| `packaging/dist/DividendNotifier-mac-arm64.dmg` | Recommended installer for users. |
| `packaging/dist/DividendNotifier-mac-arm64.zip` | Backup archive for testing or GitHub release assets. |

Generated packaging folders are ignored by Git. Do not edit files inside
`packaging/dist/`; rebuild them from source instead.

## Cleanup Checklist

Before packaging or sharing the project:

1. Delete Python caches: `find app scripts tests packaging -type d -name __pycache__ -prune -exec rm -rf {} +`
2. Keep only placeholders in `data/`, `logs/`, and `output/`.
3. Do not commit `.env`, databases, caches, generated reports, `.venv-build/`, `.cache-build/`, or `packaging/dist/`.
4. Build the macOS app with `bash packaging/build_mac.sh`.
