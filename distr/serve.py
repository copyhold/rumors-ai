#!/usr/bin/env python3
"""
serve.py — Local HTTP server with Accept-Ranges support.

Python's built-in http.server handles Range requests but doesn't advertise
Accept-Ranges: bytes in its responses, so browsers mark audio/video as
non-seekable. This wrapper adds that header.

Usage:
    cd distr && python serve.py          # serves on port 8000
    cd distr && python serve.py 9000     # custom port
"""

import sys
from http.server import SimpleHTTPRequestHandler, HTTPServer


class SeekableHTTPHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def log_message(self, format, *args):
        # Suppress noisy request logs; print only errors
        if args and str(args[1]) not in ("200", "206", "304"):
            super().log_message(format, *args)


port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
server = HTTPServer(("", port), SeekableHTTPHandler)
print(f"Serving distr/ at http://localhost:{port}/play_player.html")
print("Press Ctrl-C to stop.")
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
