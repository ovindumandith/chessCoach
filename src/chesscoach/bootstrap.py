"""Create the first administrator (there are no default credentials).

    python -m chesscoach.bootstrap --email admin@example.org

The password is read from CHESSCOACH_BOOTSTRAP_PASSWORD or prompted for.
"""

import argparse
import getpass
import os

from chesscoach import accounts
from chesscoach.db.enums import UserRole
from chesscoach.db.session import get_sessionmaker


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an administrator or coach account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", choices=["admin", "coach"], default="admin")
    args = parser.parse_args()
    password = os.environ.get("CHESSCOACH_BOOTSTRAP_PASSWORD") or getpass.getpass("Password: ")
    with get_sessionmaker()() as db:
        user = accounts.create_user(
            db, None, email=args.email, password=password, role=UserRole(args.role)
        )
    print(f"Created {user.role.value} {user.email}")


if __name__ == "__main__":
    main()
