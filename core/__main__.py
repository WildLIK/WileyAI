import argparse
import socket

import uvicorn

from .api import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    app = create_app()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    app.state.local_port = sock.getsockname()[1]
    print(f"WILEYAI_PORT={sock.getsockname()[1]}", flush=True)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
