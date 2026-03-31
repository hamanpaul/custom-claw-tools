from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .engine import queue_picoclaw_report


def serve_loopback(
    *,
    sync_root=None,
    vault_path=None,
    artifacts_root=None,
    root_note_path=None,
    pipeline_root=None,
    host: str = "127.0.0.1",
    port: int = 45460,
    run_pipeline: bool = False,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/health":
                self._write_json(404, {"error": f"unknown endpoint: {parsed.path}"})
                return

            self._write_json(
                200,
                {
                    "ok": True,
                    "host": host,
                    "port": port,
                    "run_pipeline": run_pipeline,
                    "callback_endpoint": "/picoclaw-report",
                },
            )

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/picoclaw-report":
                self._write_json(404, {"error": f"unknown endpoint: {parsed.path}"})
                return

            try:
                payload = self._read_json()
                result = queue_picoclaw_report(
                    report_payload=payload,
                    sync_root=sync_root,
                    vault_path=vault_path,
                    artifacts_root=artifacts_root,
                    root_note_path=root_note_path,
                    pipeline_root=pipeline_root,
                    run_pipeline=run_pipeline,
                )
            except json.JSONDecodeError as error:
                self._write_json(400, {"error": f"invalid JSON body: {error}"})
                return
            except RuntimeError as error:
                self._write_json(400, {"error": str(error)})
                return

            self._write_json(200, result.to_dict())

        def do_PUT(self) -> None:  # noqa: N802
            self._write_json(405, {"error": f"method PUT is not allowed for {urlparse(self.path).path}"})

        def do_DELETE(self) -> None:  # noqa: N802
            self._write_json(405, {"error": f"method DELETE is not allowed for {urlparse(self.path).path}"})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _read_json(self) -> Any:
            content_length = self.headers.get("content-length")
            if not content_length:
                raise RuntimeError("request body is required")
            body = self.rfile.read(int(content_length))
            if not body:
                raise RuntimeError("request body is required")
            return json.loads(body.decode("utf-8"))

        def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            self.send_response(status_code)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
