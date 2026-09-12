"""Local account recovery. Requires direct access to the server's private data folder.
Stop the server before using this command. Password input is hidden and never logged.
"""
from __future__ import annotations

import argparse
import getpass
import sys

import server


def reset_password(identifier: str, password: str) -> bool:
    """Replace one account password and revoke every session. Return whether found."""
    if not server.DB.is_file():
        raise FileNotFoundError("No workspace database found. Complete first-time setup first.")
    server.password_value({"password": password})
    with server.db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        user = connection.execute(
            "SELECT id FROM users WHERE lower(email)=? OR upper(employee_id)=?",
            (identifier.strip().lower(), identifier.strip().upper()),
        ).fetchone()
        if user is None:
            return False
        connection.execute(
            "UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
            (server.hashpass(password), user["id"]),
        )
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        server.audit(connection, user["id"], "Local account recovery", "users", user["id"],
                     "Password replaced from the server console; all sessions revoked.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Colleague Workspace local account recovery")
    parser.add_argument("command", choices=["reset-password"])
    args = parser.parse_args()
    del args
    print("LOCAL ACCOUNT RECOVERY")
    print("Stop the running server first. Use only on a workspace you administer.")
    print("No password will be displayed or stored as plain text.")
    if not server.DB.is_file():
        print("No workspace database found. Complete first-time setup instead.")
        return 1
    try:
        identifier = input("Account email or employee ID: ").strip()
        if not identifier:
            print("Cancelled: no account selected.")
            return 1
        password = getpass.getpass("New password (12-128 characters): ")
        confirmation = getpass.getpass("Confirm new password: ")
        if password != confirmation:
            print("The passwords do not match. No change was made.")
            return 1
        if not reset_password(identifier, password):
            print("Account not found. No change was made.")
            return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1
    except server.HTTPException as error:
        print(error.detail)
        return 1
    except (OSError, server.sqlite3.Error) as error:
        print("Recovery could not complete: " + str(error))
        return 1
    print("Password updated. Previous sessions have ended.")
    print("Account status and role were not changed. Start the server and sign in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
