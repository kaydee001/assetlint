"""A small local web server for the app: the page, its files, and a JSON API.

It listens on 127.0.0.1 only, and every API call needs the session token that
is in the URL the app opens. It also checks the Host and Origin headers, so
another website open in the same browser can't drive it (the app can write
files, so that matters).
"""

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from assetlint.app import api

_STATIC = files("assetlint.app") / "static"
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}
_MAX_BODY = 1 << 20


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 0, start_folder: Path | None = None) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(24)
        self.start_folder = start_folder

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    @property
    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}


class Handler(BaseHTTPRequestHandler):
    server: AppServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        pass  # keep the terminal quiet; problems show in the page

    # --- routing ------------------------------------------------------------

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._send_error(HTTPStatus.FORBIDDEN, "Unexpected Host header.")
        path = urlsplit(self.path).path
        if path == "/":
            return self._send_static("index.html")
        if path.startswith("/static/"):
            return self._send_static(path.removeprefix("/static/"))
        if path == "/api/info":
            if not self._token_ok():
                return self._send_error(HTTPStatus.FORBIDDEN, "Missing or wrong token.")
            return self._send_json(api.info(self.server.start_folder))
        self._send_error(HTTPStatus.NOT_FOUND, "Not found.")

    def do_POST(self) -> None:
        if not (self._host_ok() and self._origin_ok()):
            return self._send_error(HTTPStatus.FORBIDDEN, "Request from another site refused.")
        if not self._token_ok():
            return self._send_error(HTTPStatus.FORBIDDEN, "Missing or wrong token.")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._send_error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
        try:
            body = self._read_json()
        except ValueError as exc:
            return self._send_error(HTTPStatus.BAD_REQUEST, str(exc))

        routes = {
            "/api/check": lambda: api.check(str(body.get("folder", ""))),
            "/api/browse": api.browse,
        }
        handler = routes.get(urlsplit(self.path).path)
        if handler is None:
            return self._send_error(HTTPStatus.NOT_FOUND, "Not found.")
        try:
            self._send_json(handler())
        except api.ApiError as exc:
            self._send_error(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc))

    # --- checks -------------------------------------------------------------

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.server.allowed_hosts

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or urlsplit(origin).netloc in self.server.allowed_hosts

    def _token_ok(self) -> bool:
        given = self.headers.get("X-Assetlint-Token", "")
        return secrets.compare_digest(given, self.server.token)

    # --- responses ----------------------------------------------------------

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > _MAX_BODY:
            raise ValueError("Request too large.")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data

    def _send_static(self, name: str) -> None:
        resource = _STATIC.joinpath(*[p for p in name.split("/") if p not in ("", ".", "..")])
        if not resource.is_file():
            return self._send_error(HTTPStatus.NOT_FOUND, "Not found.")
        content_type = _CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream")
        self._send(HTTPStatus.OK, resource.read_bytes(), content_type)

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(status, json.dumps(data).encode(), "application/json")

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"error": message}, status)

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)
