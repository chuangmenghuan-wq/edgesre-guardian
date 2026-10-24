"""Loopback-only replay server. There is no API or provider proxy route."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent / "docs"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'")
        super().end_headers()

    def allowed(self):
        import urllib.parse
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        return path in {"/", "/index.html", "/style.css", "/app.js", "/favicon.svg", "/evidence/r13_public_trace.json"}

    def do_GET(self):
        if not self.allowed():
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        if not self.allowed():
            self.send_error(404)
            return
        super().do_HEAD()


if __name__ == "__main__":
    port = int(os.environ.get("EDGESRE_DEMO_PORT", "8765"))
    if not 1024 <= port <= 65535:
        raise ValueError("Port must be between 1024 and 65535")
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"REPLAY_ONLY http://127.0.0.1:{port}/", flush=True)
        server.serve_forever()
