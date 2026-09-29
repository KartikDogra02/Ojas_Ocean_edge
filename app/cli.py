"""Admin CLI.

Create the first admin user (only admins can create users through the API, so the first one is made here):

    docker compose exec api python -m app.cli create-admin --email you@example.com --username admin
"""

import argparse
import asyncio
import getpass
import os
import sys

from fastapi import HTTPException

from app import db
from app.models import Role, UserCreate
from app.services import insert_user


async def create_admin(email: str, username: str, full_name: str | None, temporary: bool) -> None:
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Password for new admin: ")
    user = UserCreate(email=email, username=username, full_name=full_name, password=password, roles=[Role.ADMIN])
    await db.connect()
    try:
        try:
            doc = await insert_user(user, temporary_password=temporary)
        except HTTPException as exc:
            sys.exit(exc.detail)
    finally:
        await db.disconnect()
    print(f"Created admin {doc['username']} <{email}> (id {doc['_id']}). Log in with POST /auth/login.")
    if temporary:
        print("The password is temporary: change it with POST /auth/change-password after logging in.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Create an admin user")
    p.add_argument("--email", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--full-name")
    p.add_argument(
        "--permanent-password",
        action="store_true",
        help="Don't require a password change at first login (password is temporary by default)",
    )
    args = parser.parse_args()

    if args.command == "create-admin":
        asyncio.run(create_admin(args.email, args.username, args.full_name, not args.permanent_password))


if __name__ == "__main__":
    main()
