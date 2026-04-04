from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

from .adapter import FamicleanAdapter
from .app import FamiGhomeApp
from .config import ensure_runtime_dirs, load_config
from .security import PasswordHashError, make_password_hash
from .server import create_server
from .store import AuthStateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fami-ghome")
    parser.add_argument("--home", help="Override project root")
    parser.add_argument("--env-file", help="Path to config/.env")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the fami-ghome HTTP service.")
    serve.add_argument("--host", default=None, help="Override listen host")
    serve.add_argument("--port", type=int, default=None, help="Override listen port")
    serve.set_defaults(func=cmd_serve)

    hash_password = subparsers.add_parser("hash-password", help="Generate a scrypt password hash for AUTH_ADMIN_PASSWORD_HASH.")
    hash_password.add_argument("--password", default=None, help="Password to hash; omit to prompt interactively.")
    hash_password.set_defaults(func=cmd_hash_password)
    return parser


def cmd_hash_password(args: argparse.Namespace) -> int:
    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
    try:
        print(make_password_hash(password), file=sys.stdout)
    except PasswordHashError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config = load_config(Path(__file__), env_file=args.env_file, explicit_root=args.home)
    ensure_runtime_dirs(config)

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    adapter = FamicleanAdapter(config)
    store = AuthStateStore(
        path=config.state_dir / "oauth-state.json",
        session_secret=config.session_secret,
        token_secret=config.token_encryption_key,
    )
    app = FamiGhomeApp(config, adapter=adapter, store=store)
    app.validate_runtime()

    host = args.host or config.host
    port = args.port or config.port
    server = create_server(app, host=host, port=port)
    logging.info("fami-ghome listening on %s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
