"""Desktop launcher used by PyInstaller.

It starts the FastAPI app on localhost and shows it in a native macOS window
through pywebview. If pywebview is unavailable, it falls back to the browser.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from traceback import format_exc

import uvicorn


HOST = "127.0.0.1"
LOG_DIR = Path.home() / "Library" / "Logs" / "Dividend Notifier"
LOG_FILE = LOG_DIR / "launcher.log"
_server_error = ""


def _log(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S "))
            f.write(message)
            f.write("\n")
    except Exception:
        pass


def _find_port() -> int:
    for port in range(8765, 8795):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError("No available local port found")


def _port_ready(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((HOST, port)) == 0


def _run_server(port: int) -> None:
    global _server_error
    try:
        from app.main import app as fastapi_app

        _log(f"Starting FastAPI server on {HOST}:{port}")
        uvicorn.run(
            fastapi_app,
            host=HOST,
            port=port,
            log_level="info",
            access_log=False,
        )
    except BaseException:
        _server_error = format_exc()
        _log("FastAPI server crashed")
        _log(_server_error)


def main() -> None:
    _log("Launcher started")
    try:
        port = _find_port()
    except Exception:
        port = 8765
        _log("Failed to find an available port")
        _log(format_exc())

    url = f"http://{HOST}:{port}"
    thread = threading.Thread(target=_run_server, args=(port,), daemon=True)
    thread.start()

    ready = False
    for _ in range(120):
        if _port_ready(port):
            ready = True
            _log(f"Server ready at {url}")
            break
        if not thread.is_alive():
            _log("Server thread exited before becoming ready")
            break
        time.sleep(0.25)

    try:
        import webview

        if ready:
            webview.create_window(
                "Dividend Notifier",
                url,
                width=1280,
                height=860,
                min_size=(980, 680),
            )
        else:
            _log("Server did not become ready before timeout")
            webview.create_window(
                "Dividend Notifier",
                html=(
                    "<html><body style='font-family:-apple-system,BlinkMacSystemFont,sans-serif;"
                    "padding:40px;line-height:1.6'>"
                    "<h2>Dividend Notifier 启动失败</h2>"
                    "<p>本地服务没有正常启动。请查看日志：</p>"
                    f"<pre>{LOG_FILE}</pre>"
                    f"<pre>{_server_error}</pre>"
                    "</body></html>"
                ),
                width=900,
                height=520,
            )
        webview.start(debug=False)
        return
    except Exception:
        _log("pywebview failed, falling back to browser")
        _log(format_exc())
        if ready:
            webbrowser.open(url)
        else:
            sys.exit(1)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
