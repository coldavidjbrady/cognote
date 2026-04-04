from __future__ import annotations

import os
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if response.status < 500:
                    return True
        except (ConnectionError, OSError, urllib.error.URLError):
            time.sleep(0.2)
    return False


def main() -> int:
    os.environ.setdefault("COGNOTE_RUNTIME_MODE", "packaged")

    from .main import app

    host = "127.0.0.1"
    port = int(os.getenv("COGNOTE_PORT", "0")) or _pick_port()
    base_url = f"http://{host}:{port}"

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
        server_header=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="cognote-server", daemon=True)
    thread.start()

    if not _wait_for_server(f"{base_url}/api/health"):
        server.should_exit = True
        thread.join(timeout=2)
        raise SystemExit("Cognote could not start its local service.")

    try:
        import webview
    except ImportError:
        webbrowser.open(base_url)
        try:
            while thread.is_alive():
                thread.join(timeout=0.5)
        except KeyboardInterrupt:
            server.should_exit = True
        return 0

    webview.create_window("Cognote", base_url, width=1460, height=960, min_size=(1100, 720))
    webview.start()
    server.should_exit = True
    thread.join(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
