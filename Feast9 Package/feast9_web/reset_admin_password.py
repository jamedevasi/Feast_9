"""
Emergency password reset — run this directly on the server if you've
forgotten both your password AND your security-question answer.

This requires the same access you used to deploy the app (SSH into your
VPS, or your host's "run a command" / shell feature). It does not need the
app to be running.

Usage:
    python reset_admin_password.py
"""
import getpass
import sys

from app import db
from app.auth import hash_password


def run():
    db.init_db()
    with db.get_conn() as conn:
        users = [dict(r) for r in conn.execute("SELECT id, username FROM users").fetchall()]

    if not users:
        print("No user account exists yet — just visit the app's /setup page instead.")
        return

    if len(users) == 1:
        user = users[0]
        print(f"Found one account: '{user['username']}'")
    else:
        print("Multiple accounts found:")
        for u in users:
            print(f"  [{u['id']}] {u['username']}")
        choice = input("Enter the username to reset: ").strip()
        match = next((u for u in users if u["username"] == choice), None)
        if not match:
            print("No account with that username. Aborting.")
            sys.exit(1)
        user = match

    print(f"\nResetting password for '{user['username']}'.")
    while True:
        pw1 = getpass.getpass("New password (min 6 characters): ")
        if len(pw1) < 6:
            print("Too short — try again.")
            continue
        pw2 = getpass.getpass("Confirm new password: ")
        if pw1 != pw2:
            print("Passwords didn't match — try again.")
            continue
        break

    db.update_user_password(user["id"], hash_password(pw1))
    print(f"\nDone — password for '{user['username']}' has been reset.")
    print("You can now log in with the new password. Consider also setting up "
          "a new security question from Settings once you're logged in.")


if __name__ == "__main__":
    run()
