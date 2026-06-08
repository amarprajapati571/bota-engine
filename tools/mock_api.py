"""
Zero-dependency mock backend for testing the --live API push.

    python tools/mock_api.py                 # listens on :8000

Then set in .env:
    API_BASE_URL=http://localhost:8000
and run `python main.py --live` (or replay logs/outbox.jsonl). Every POST is
printed and appended to tools/received_rounds.jsonl. GET / returns a health blob.

This only exists so you can see the full loop work without a real backend —
point API_BASE_URL at your own server when you have one.
"""
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "received_rounds.jsonl")
PORT = int(os.getenv("MOCK_API_PORT", 8000))


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        self._json(200, {"status": "ok", "ts": datetime.utcnow().isoformat()})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})

        with open(STORE, "a") as fh:
            fh.write(json.dumps(payload) + "\n")

        rid = payload.get("round_id", "?")
        has_auth = "yes" if self.headers.get("Authorization") else "no"
        print(
            f"[{datetime.now():%H:%M:%S}] round {rid} | "
            f"P={payload.get('player_value')} B={payload.get('banker_value')} "
            f"-> {payload.get('outcome')} | auth={has_auth}"
        )
        self._json(201, {"success": True, "round_id": rid})

    def log_message(self, *args):  # silence default per-request logging
        pass


def main() -> None:
    print(f"Mock API on http://localhost:{PORT}  (POST anything; stored in {STORE})")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
