"""Serve local demo assets with an explicit UTF-8 content type."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(SimpleHTTPRequestHandler):
    def guess_type(self, path):
        kind = super().guess_type(path)
        return kind + "; charset=utf-8" if kind.startswith("text/") else kind


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path(".playwright-mcp"))
    parser.add_argument("--port", type=int, default=8932)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                 partial(Handler, directory=str(args.directory.resolve())))
    print(f"Serving http://127.0.0.1:{args.port}/calibration-demo/calibration.html", flush=True)
    server.serve_forever()
