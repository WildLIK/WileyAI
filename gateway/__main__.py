"""Explicit initialization and a separate server process; no personal credentials are read."""
import argparse
import json
import os
from pathlib import Path
import secrets
import stat

import uvicorn

from .app import create_app
from .store import Store, new_id, private_directory


def main():
    parser = argparse.ArgumentParser(prog="python -m gateway")
    parser.add_argument("command", choices=["init", "serve"])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=48500)
    parser.add_argument("--development-loopback", action="store_true")
    parser.add_argument("--test-provider", action="store_true")
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--forwarded-allow-ips", default="127.0.0.1")
    args = parser.parse_args()
    if os.name != "nt":
        os.umask(0o077)
    if args.command == "init":
        private_directory(args.data_dir)
        private_directory(args.key_file.parent)
        if args.key_file.exists() or (args.data_dir / "gateway.db").exists():
            parser.error("Initialization would overwrite existing Gateway state; use the existing key and database")
        with args.key_file.open("xb") as file:
            file.write(secrets.token_bytes(32))
        if os.name != "nt":
            args.key_file.chmod(0o600)
        store = Store(args.data_dir, args.key_file.read_bytes())
        try:
            token = store.token(new_id(), "admin", "Owner")
            path = args.data_dir / "owner.token"
            with path.open("x", encoding="ascii") as file:
                file.write(token + "\n")
            if os.name != "nt":
                path.chmod(0o600)
            print("Initialized Gateway. Owner token file:", path.resolve())
        finally:
            store.close()
        return
    if not args.key_file.is_file():
        parser.error("Initialize Gateway first; the master key file is required")
    if os.name != "nt" and stat.S_IMODE(args.key_file.stat().st_mode) & 0o077:
        parser.error("Master key must not be accessible to group or other users")
    if (args.development_loopback or args.test_provider) and args.host not in {"127.0.0.1", "::1"}:
        parser.error("Development/test mode may bind only loopback")
    profiles = json.loads(args.profiles.read_text(encoding="utf-8")) if args.profiles else []
    app = create_app(args.data_dir, args.key_file.read_bytes(), test_mode=args.test_provider,
                     development=args.development_loopback, api_profiles=profiles)
    uvicorn.run(app, host=args.host, port=args.port, access_log=False, proxy_headers=True,
                forwarded_allow_ips=args.forwarded_allow_ips, server_header=False)


if __name__ == "__main__":
    main()
