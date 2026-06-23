"""Filesystem paths for source runs and packaged desktop builds."""

import os
import sys


APP_NAME = "Dividend Notifier"


def is_frozen() -> bool:
    """Return True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> str:
    """Repository root when running from source."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_root() -> str:
    """Read-only bundled resource root."""
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return project_root()


def app_support_dir() -> str:
    """Writable per-user application data directory."""
    override = os.getenv("DIVIDEND_NOTIFIER_HOME", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))

    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    return os.path.join(os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "dividend-notifier")


def writable_root() -> str:
    """Writable data root. Source runs stay local; packaged apps use user data."""
    if is_frozen() or os.getenv("DIVIDEND_NOTIFIER_HOME"):
        return app_support_dir()
    return project_root()


def ensure_dir(*parts: str) -> str:
    path = os.path.join(writable_root(), *parts)
    os.makedirs(path, exist_ok=True)
    return path


def database_path() -> str:
    return os.path.join(ensure_dir("data"), "dividend_notifier.db")


def cache_dir() -> str:
    return ensure_dir("data", "cache")


def output_dir() -> str:
    return ensure_dir("output")


def logs_dir() -> str:
    return ensure_dir("logs")


def template_dir() -> str:
    return os.path.join(resource_root(), "app", "templates")


def static_dir() -> str:
    return os.path.join(resource_root(), "app", "static")
