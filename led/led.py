#!/usr/bin/env python3
"""ARAD LED-Dienst: schaltet den COB-Ring über MOSFET an GPIO18.
GET /light?level=0..100   GET /status
Installation: sudo apt install python3-gpiozero
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from gpiozero import PWMLED

PIN = 18        # GPIO18 = Pin 12
PORT = 8080
FADE_MS = 120   # kurzer Fade; 0 = hart schalten

led = PWMLED(PIN, frequency=1000)
lock = threading.Lock()


def fade_to(v: float):
    with lock:
        start = led.value
        steps = max(1, FADE_MS // 10)
        for i in range(1, steps + 1):
            led.value = start + (v - start) * i / steps
            time.sleep(0.01)
        led.value = v  # 0.0 oder 1.0 = kein PWM -> kein Kameraflackern


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/light":
            try:
                lvl = max(0, min(100, int(q.get("level", ["100"])[0])))
            except ValueError:
                return self._reply(400, '{"error":"level 0..100"}')
            threading.Thread(target=fade_to, args=(lvl / 100,), daemon=True).start()
            return self._reply(200, f'{{"level":{lvl}}}')
        if u.path == "/status":
            return self._reply(200, f'{{"level":{round(led.value * 100)}}}')
        self._reply(404, '{"error":"not found"}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    fade_to(1.0)  # beim Start: Licht an (Fail-safe für Autodarts)
    print(f"[ARAD LED] GPIO{PIN} auf Port {PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
