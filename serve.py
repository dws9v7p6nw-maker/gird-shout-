#!/usr/bin/env python3
"""
Fallback server for hosts (like Render's "Web Service" type) that insist on
running a Python start command instead of serving this as a static site.
Serves the current directory on the port the host assigns via $PORT.

Set the host's Start Command to:  python serve.py
(Not needed if the service is a proper Static Site — Render then serves
index.html directly and this file is unused.)
"""
import http.server
import os

port = int(os.environ.get("PORT", 8000))
handler = http.server.SimpleHTTPRequestHandler
with http.server.ThreadingHTTPServer(("0.0.0.0", port), handler) as httpd:
    print(f"Serving GridScout on 0.0.0.0:{port}")
    httpd.serve_forever()
