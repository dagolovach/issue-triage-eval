"""Serve the local dashboard so it can read results/scores.json (file:// blocks fetch).

    python scripts/serve.py    # -> http://localhost:8000/web/
"""
import http.server, socketserver, webbrowser, os
from pathlib import Path

os.chdir(Path(__file__).resolve().parents[1])
PORT = int(os.environ.get("PORT", 8000))
url = f"http://localhost:{PORT}/web/"
print(f"dashboard: {url}\n(reads results/scores.json if present, else bundled sample)")
try:
    webbrowser.open(url)
except Exception:
    pass
with socketserver.TCPServer(("", PORT), http.server.SimpleHTTPRequestHandler) as httpd:
    httpd.serve_forever()
