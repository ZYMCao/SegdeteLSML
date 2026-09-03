"""WSGI entry: builds the SegDete Label Studio ML backend app.

`label-studio-ml start src/lsml` will load the module-level `app`.
Running this file directly (or via ``uv run lsml``) starts a uvicorn
server for local debugging.
"""

import argparse
import logging
import socket

import uvicorn
from label_studio_ml.api import init_app
from uvicorn.middleware.wsgi import WSGIMiddleware

try:
    from lsml.model import SegDeteMLBackend
except ImportError:  # pragma: no cover - direct script invocation fallback
    from model import SegDeteMLBackend

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MODEL_DIR = "/tmp/ml_backend_runtime"


def _build_app(host="0.0.0.0", port=9090, **kwargs):
    kwargs.setdefault("host", host)
    kwargs.setdefault("port", port)
    kwargs.setdefault("model_dir", MODEL_DIR)
    return init_app(model_class=SegDeteMLBackend, **kwargs)


def create_app():
    return _build_app()


app = create_app()


def _run(host, port):
    """Run uvicorn over the Flask WSGI app.

    ``host="0.0.0.0"`` binds IPv4 only; ``host="::"`` binds a dual-stack IPv6
    socket (IPV6_V6ONLY=0) so IPv4 and IPv6 clients can both reach the server.
    """
    app_obj = WSGIMiddleware(app)
    if host == "::":
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::", port))
        sock.listen(128)
        uvicorn.run(app_obj, fd=sock.fileno())
    else:
        uvicorn.run(app_obj, host=host, port=port)


def main(argv=None):
    """Console-script entry: parse --host/--port and run uvicorn."""
    parser = argparse.ArgumentParser(description="SegDete Label Studio ML backend")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=9090, type=int)
    args = parser.parse_args(argv)
    logger.info("Starting SegDete ML backend on %s:%s", args.host, args.port)
    _run(args.host, args.port)


if __name__ == "__main__":
    main()
