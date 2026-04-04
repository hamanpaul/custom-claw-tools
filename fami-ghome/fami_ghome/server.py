from __future__ import annotations

from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse
import json

from .app import FamiGhomeApp
from .config import RuntimeConfigError


SESSION_COOKIE_NAME = "fami_ghome_session"


def _first_form_value(values: dict[str, list[str]], key: str) -> str:
    items = values.get(key) or [""]
    return items[0]


def _extract_bearer_token(handler: BaseHTTPRequestHandler) -> str | None:
    header = handler.headers.get("authorization", "").strip()
    if not header:
        return None
    prefix = "bearer "
    if header.lower().startswith(prefix):
        return header[len(prefix):].strip()
    return None


def create_server(app: FamiGhomeApp, *, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "fami-ghome/1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/healthz":
                    self._write_json(
                        200,
                        {
                            "ok": True,
                            "service": "fami-ghome",
                            "device_id": app.config.local_home_device_id,
                            "project_root": str(app.config.project_root),
                            "wrapper": str(app.config.famiclean_wrapper),
                        },
                    )
                    return

                if parsed.path == "/oauth/authorize":
                    self._handle_authorize_get(parsed)
                    return

                if parsed.path == "/internal/state":
                    self._handle_internal_state()
                    return

                self._write_json(404, {"error": f"unknown endpoint: {parsed.path}"})
            except RuntimeConfigError as exc:
                self._write_json(400, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/oauth/authorize":
                    self._handle_authorize_post()
                    return
                if parsed.path == "/oauth/token":
                    self._handle_token()
                    return
                if parsed.path == "/fulfillment":
                    self._handle_fulfillment()
                    return
                self._write_json(404, {"error": f"unknown endpoint: {parsed.path}"})
            except RuntimeConfigError as exc:
                self._write_json(400, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _handle_authorize_get(self, parsed) -> None:
            params = {key: values[0] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
            request = app.authorize_request(params)
            session = app.get_session(self._session_cookie())
            if session is not None:
                self._redirect(
                    app.build_redirect_url(request, username=str(session["username"])),
                    set_cookie=None,
                )
                return
            self._write_html(200, app.render_authorize_html(request))

        def _handle_authorize_post(self) -> None:
            body = self._read_body()
            values = parse_qs(body.decode("utf-8"), keep_blank_values=True)
            request = app.authorize_request(
                {
                    "response_type": _first_form_value(values, "response_type"),
                    "client_id": _first_form_value(values, "client_id"),
                    "redirect_uri": _first_form_value(values, "redirect_uri"),
                    "state": _first_form_value(values, "state"),
                }
            )
            username = _first_form_value(values, "username")
            password = _first_form_value(values, "password")
            try:
                session_token = app.login_admin(username, password)
            except RuntimeConfigError as exc:
                self._write_html(401, app.render_authorize_html(request, error=str(exc)))
                return
            self._redirect(
                app.build_redirect_url(request, username=username),
                set_cookie=self._session_cookie_header(session_token),
            )

        def _handle_token(self) -> None:
            values = parse_qs(self._read_body().decode("utf-8"), keep_blank_values=True)
            grant_type = _first_form_value(values, "grant_type")
            client_id = _first_form_value(values, "client_id")
            client_secret = _first_form_value(values, "client_secret")
            if grant_type == "authorization_code":
                payload = app.exchange_authorization_code(
                    client_id=client_id,
                    client_secret=client_secret,
                    code=_first_form_value(values, "code"),
                    redirect_uri=_first_form_value(values, "redirect_uri"),
                )
                self._write_json(200, payload)
                return
            if grant_type == "refresh_token":
                payload = app.exchange_refresh_token(
                    client_id=client_id,
                    client_secret=client_secret,
                    refresh_token=_first_form_value(values, "refresh_token"),
                )
                self._write_json(200, payload)
                return
            self._write_json(400, {"error": f"unsupported grant_type: {grant_type}"})

        def _handle_fulfillment(self) -> None:
            payload = self._read_json()
            result = app.handle_fulfillment(payload, access_token=_extract_bearer_token(self))
            self._write_json(200, result)

        def _handle_internal_state(self) -> None:
            if not app.config.internal_api_enabled:
                self._write_json(404, {"error": "internal API disabled"})
                return
            token = (
                self.headers.get("x-internal-api-token")
                or _extract_bearer_token(self)
                or parse_qs(urlparse(self.path).query, keep_blank_values=True).get("token", [None])[0]
            )
            if token != app.config.internal_api_token:
                self._write_json(403, {"error": "invalid internal API token"})
                return
            self._write_json(200, app.read_snapshot())

        def _read_body(self) -> bytes:
            content_length = self.headers.get("content-length")
            if not content_length:
                raise RuntimeConfigError("request body is required")
            body = self.rfile.read(int(content_length))
            if not body:
                raise RuntimeConfigError("request body is required")
            return body

        def _read_json(self) -> dict[str, object]:
            body = self._read_body()
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeConfigError(f"invalid JSON body: {exc}") from exc
            if not isinstance(payload, dict):
                raise RuntimeConfigError("JSON body must be an object")
            return payload

        def _write_json(self, status_code: int, payload: dict[str, object]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            self.send_response(status_code)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _write_html(self, status_code: int, html_body: str) -> None:
            encoded = html_body.encode("utf-8")
            self.send_response(status_code)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _redirect(self, location: str, *, set_cookie: str | None) -> None:
            self.send_response(302)
            self.send_header("location", location)
            if set_cookie:
                self.send_header("set-cookie", set_cookie)
            self.end_headers()

        def _session_cookie(self) -> str | None:
            raw_cookie = self.headers.get("cookie")
            if not raw_cookie:
                return None
            jar = cookies.SimpleCookie()
            jar.load(raw_cookie)
            morsel = jar.get(SESSION_COOKIE_NAME)
            if morsel is None:
                return None
            return morsel.value

        def _session_cookie_header(self, value: str) -> str:
            cookie = cookies.SimpleCookie()
            cookie[SESSION_COOKIE_NAME] = value
            cookie[SESSION_COOKIE_NAME]["path"] = "/oauth"
            cookie[SESSION_COOKIE_NAME]["httponly"] = True
            cookie[SESSION_COOKIE_NAME]["samesite"] = "Lax"
            cookie[SESSION_COOKIE_NAME]["max-age"] = 24 * 3600
            if app.config.public_base_url.startswith("https://"):
                cookie[SESSION_COOKIE_NAME]["secure"] = True
            return cookie.output(header="").strip()

    return ThreadingHTTPServer((host, port), Handler)
