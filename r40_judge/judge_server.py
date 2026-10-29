"""Loopback judge test build: recorded replay plus fresh OFFLINE development lab."""
from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from judge_runtime import DEV_CASES, contract_preview, run_public_development_case

HERE = Path(__file__).resolve().parent
RUN_LOCK = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def log_message(self, format, *args):
        pass

    def list_directory(self, path):
        self.send_error(403, "Directory listing disabled")
        return None

    def send_json(self, status: int, data: dict):
        raw = json.dumps(data, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/judge/status":
            self.send_json(200, {"schema": "edgesre_r39_judge_status_1",
                                 "public_dev_lab": "READY_OFFLINE_POLICY",
                                 "case_ids": list(DEV_CASES),
                                 "recorded_real_provider_replay": "READY",
                                 "new_provider_calls_in_this_build": 0,
                                 "historical_provider_calls": 278,
                                 "live_inference": "DISABLED_PUBLIC_REPLAY_BUILD"})
            return
        if self.path == "/api/judge/contract":
            self.send_json(200, contract_preview())
            return
        if self.path.startswith("/api/"):
            self.send_json(404, {"error": "API_ROUTE_NOT_FOUND"})
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/judge/live":
            self.send_json(423, {"error": "LIVE_DISABLED_PUBLIC_REPLAY_BUILD",
                                 "provider_calls_sent": 0})
            return
        if self.path != "/api/judge/run":
            self.send_json(404, {"error": "API_ROUTE_NOT_FOUND"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self.send_json(415, {"error": "JSON_REQUIRED"})
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_json(411, {"error": "CONTENT_LENGTH_REQUIRED"})
            return
        if size < 1 or size > 256:
            self.send_json(413, {"error": "REQUEST_TOO_LARGE"})
            return
        try:
            body = json.loads(self.rfile.read(size))
        except ValueError:
            self.send_json(400, {"error": "JSON_INVALID"})
            return
        if not isinstance(body, dict) or set(body) != {"case_id"} or body["case_id"] not in DEV_CASES:
            self.send_json(400, {"error": "PUBLIC_DEVELOPMENT_CASE_ONLY"})
            return
        if not RUN_LOCK.acquire(blocking=False):
            self.send_json(429, {"error": "DEVELOPMENT_RUN_ALREADY_ACTIVE"})
            return
        try:
            self.send_json(200, run_public_development_case(body["case_id"]))
        except Exception as exc:
            self.send_json(500, {"error": "LOCAL_LAB_FAILURE", "type": type(exc).__name__})
        finally:
            RUN_LOCK.release()


def serve(port: int = 8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"R39 judge candidate: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    serve(parser.parse_args().port)
