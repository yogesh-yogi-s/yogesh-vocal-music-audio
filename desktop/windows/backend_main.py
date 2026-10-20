"""Desktop-only entry point for the existing VMA FastAPI application."""

from __future__ import annotations

import os
import socket
import sys
import threading


def main() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2048)
    port = listener.getsockname()[1]

    os.environ["VMA_ENVIRONMENT"] = "development"
    os.environ["VMA_TRUSTED_HOSTS"] = "127.0.0.1"
    os.environ["VMA_ALLOWED_ORIGINS"] = f"http://127.0.0.1:{port}"
    os.environ["VMA_HEALTHCHECK_HOST"] = "127.0.0.1"
    os.environ["VMA_TRUSTED_PROXIES"] = ""

    from backend.app.main import app
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, proxy_headers=False, workers=1)
    )

    def await_shutdown() -> None:
        for command in sys.stdin:
            if command.strip() == "shutdown":
                server.should_exit = True
                return

    threading.Thread(target=await_shutdown, daemon=True).start()
    print(f"VMA_PORT={port}", flush=True)
    server.run(sockets=[listener])


if __name__ == "__main__":
    main()
