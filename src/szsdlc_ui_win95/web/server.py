"""uvicorn serving an ASGI app on a socket bound up front."""

from __future__ import annotations

import logging
import socket
import threading


class Server:
    """Bound in the constructor, as `http.server` did: a busy port raises OSError
    before anything is printed, and port 0's choice is known at once."""

    def __init__(self, app, host: str, port: int, *, token: str, verbose: bool = False):
        import uvicorn

        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.socket = socket.socket(family, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.bind((host, port))
            self.socket.listen(128)
        except OSError:
            self.socket.close()
            raise
        self.server_port = self.socket.getsockname()[1]
        self.token = token
        self.app = app
        config = uvicorn.Config(app, log_level=logging.INFO if verbose else logging.WARNING,
                                access_log=verbose, server_header=False, lifespan="off",
                                timeout_graceful_shutdown=2)
        self._server = uvicorn.Server(config)
        self._running = threading.Event()
        self._stopped = threading.Event()

    def serve_forever(self) -> None:
        """Serve until shutdown() (or Ctrl-C on the main thread, which uvicorn handles)."""
        self._running.set()
        try:
            self._server.run(sockets=[self.socket])
        finally:
            self._stopped.set()

    def shutdown(self) -> None:
        """Stop serving, and wait until it has."""
        self._server.should_exit = True
        if self._running.is_set():
            self._stopped.wait(10)

    def server_close(self) -> None:
        self.socket.close()
