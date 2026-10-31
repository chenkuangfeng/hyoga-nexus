"""Operator commands. Run from the repository root with the configured database.

    uv run python -m nexus_api.cli create-owner --tenant "公司名" --username alice

The password is read with a hidden prompt and never accepted as an argument or environment value.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from nexus_platform.auth.accounts import create_owner_account
from nexus_platform.persistence.database import create_database_engine, session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexus_api.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    owner = commands.add_parser("create-owner", help="create a tenant and its first owner account")
    owner.add_argument("--tenant", required=True)
    owner.add_argument("--username", required=True)
    owner.add_argument("--display-name", default="")
    args = parser.parse_args(argv)
    password = getpass.getpass("Initial password (at least 10 characters): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match", file=sys.stderr)
        return 1
    engine = create_database_engine()
    try:
        with session_factory(engine)() as db:
            tenant_id = create_owner_account(db, tenant_name=args.tenant, username=args.username,
                                             display_name=args.display_name, password=password)
    except ValueError as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    print(f"Created tenant {tenant_id} with owner {args.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
