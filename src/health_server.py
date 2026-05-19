import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.runtime_status import STATUS


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/status", "/healthz"):
            body = json.dumps(STATUS.snapshot(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, format: str, *args) -> None:
        return


def serve_forever() -> None:
    host = os.getenv("HEALTH_HOST", "0.0.0.0")
    port = int(os.getenv("HEALTH_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), HealthHandler)
    server.serve_forever()
