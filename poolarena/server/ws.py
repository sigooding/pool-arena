"""A dependency-free HTTP + WebSocket server.

RFC 6455 is small enough to implement directly, and doing so means the pool-room
PC needs nothing but CPython to serve the overlay. No pip install, no venv
surprises on a machine you only touch once a month.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x1, 0x2, 0x8, 0x9, 0xA


class Client:
    """One connected overlay or scoreboard."""

    def __init__(self, sock: socket.socket, addr) -> None:
        self.sock = sock
        self.addr = addr
        self.alive = True
        self._lock = threading.Lock()

    def send(self, payload: str) -> bool:
        data = payload.encode("utf-8")
        header = bytearray([0x80 | OP_TEXT])
        n = len(data)
        if n < 126:
            header.append(n)
        elif n < (1 << 16):
            header.append(126)
            header += struct.pack(">H", n)
        else:
            header.append(127)
            header += struct.pack(">Q", n)
        try:
            with self._lock:
                self.sock.sendall(bytes(header) + data)
            return True
        except OSError:
            self.alive = False
            return False

    def close(self) -> None:
        self.alive = False
        try:
            with self._lock:
                self.sock.sendall(bytes([0x80 | OP_CLOSE, 0]))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def _read_exactly(sock: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def read_frame(sock: socket.socket) -> tuple[int, bytes] | None:
    head = _read_exactly(sock, 2)
    if not head:
        return None
    b0, b1 = head
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F
    if length == 126:
        ext = _read_exactly(sock, 2)
        if not ext:
            return None
        length = struct.unpack(">H", ext)[0]
    elif length == 127:
        ext = _read_exactly(sock, 8)
        if not ext:
            return None
        length = struct.unpack(">Q", ext)[0]
    if length > 4 << 20:          # 4 MiB cap: the overlay never sends bulk data
        return None
    mask = _read_exactly(sock, 4) if masked else b""
    if masked and mask is None:
        return None
    data = _read_exactly(sock, length) if length else b""
    if data is None:
        return None
    if masked:
        data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
    return opcode, data


class Hub:
    """Fan-out to every connected client, with a last-state replay for joiners."""

    def __init__(self) -> None:
        self.clients: list[Client] = []
        self._lock = threading.Lock()
        self.sticky: dict[str, dict[str, Any]] = {}
        self.on_message: Callable[[dict[str, Any], Client], None] | None = None

    def add(self, c: Client) -> None:
        with self._lock:
            self.clients.append(c)
        for msg in self.sticky.values():
            c.send(json.dumps(msg))

    def remove(self, c: Client) -> None:
        with self._lock:
            if c in self.clients:
                self.clients.remove(c)

    def broadcast(self, msg: dict[str, Any], sticky_key: str | None = None) -> None:
        if sticky_key:
            self.sticky[sticky_key] = msg
        blob = json.dumps(msg)
        with self._lock:
            targets = list(self.clients)
        for c in targets:
            if not c.send(blob):
                self.remove(c)

    def count(self) -> int:
        with self._lock:
            return len(self.clients)


def make_handler(hub: Hub, static_root: Path,
                 http_routes: dict[str, Callable[[], dict[str, Any]]] | None = None):
    routes = http_routes or {}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "poolarena"

        def log_message(self, fmt: str, *args) -> None:      # quiet by default
            if os.environ.get("POOLARENA_HTTP_LOG"):
                super().log_message(fmt, *args)

        # --- websocket ----------------------------------------------------
        def _is_ws(self) -> bool:
            return (self.headers.get("Upgrade", "").lower() == "websocket"
                    and "websocket" in self.headers.get("Upgrade", "").lower())

        def _handshake(self) -> Client | None:
            key = self.headers.get("Sec-WebSocket-Key")
            if not key:
                self.send_error(400, "missing Sec-WebSocket-Key")
                return None
            accept = base64.b64encode(
                hashlib.sha1((key + GUID).encode()).digest()).decode()
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.close_connection = True       # we own the socket from here
            return Client(self.connection, self.client_address)

        def _serve_ws(self) -> None:
            client = self._handshake()
            if client is None:
                return
            hub.add(client)
            try:
                while client.alive:
                    frame = read_frame(self.connection)
                    if frame is None:
                        break
                    opcode, data = frame
                    if opcode == OP_CLOSE:
                        break
                    if opcode == OP_PING:
                        with client._lock:
                            self.connection.sendall(bytes([0x80 | OP_PONG, len(data)]) + data)
                        continue
                    if opcode == OP_TEXT and hub.on_message:
                        try:
                            hub.on_message(json.loads(data.decode("utf-8")), client)
                        except Exception as exc:    # a bad frame must not kill the hub
                            client.send(json.dumps({"type": "error", "error": str(exc)}))
            finally:
                hub.remove(client)
                client.close()

        # --- static + json ------------------------------------------------
        def do_GET(self) -> None:                     # noqa: N802
            path = self.path.split("?")[0]
            if path in ("/ws", "/socket") and self.headers.get("Upgrade", "").lower() == "websocket":
                self._serve_ws()
                return
            if path in routes:
                self._json(routes[path]())
                return
            self._static(path)

        def do_POST(self) -> None:                    # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b"{}"
            try:
                msg = json.loads(body.decode("utf-8") or "{}")
            except ValueError:
                self._json({"ok": False, "error": "bad json"}, 400)
                return
            if hub.on_message:
                try:
                    hub.on_message(msg, None)   # type: ignore[arg-type]
                except Exception as exc:        # a bad command is not a crash
                    self._json({"ok": False, "error": str(exc)}, 400)
                    return
            self._json({"ok": True})

        def _json(self, obj: Any, status: int = 200) -> None:
            blob = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(blob)

        def _static(self, path: str) -> None:
            rel = path.lstrip("/") or "index.html"
            target = (static_root / rel).resolve()
            if not str(target).startswith(str(static_root.resolve())):
                self.send_error(403)
                return
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                self.send_error(404)
                return
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            blob = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(blob)

    return Handler


def serve(hub: Hub, static_root: Path, host: str = "0.0.0.0", port: int = 8777,
          http_routes: dict[str, Callable[[], dict[str, Any]]] | None = None):
    """Start the server on a daemon thread and return it."""
    handler = make_handler(hub, static_root, http_routes)
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, name="poolarena-http", daemon=True)
    t.start()
    return httpd
