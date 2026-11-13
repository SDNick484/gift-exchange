"""Command-line chores on the host.

  python3 manage.py hash-password   read a password from stdin (or a prompt on a terminal) and print its
                                    `scrypt$<salt hex>$<hash hex>` hash, for ADMIN_PASSWORD_HASH in deploy.env

Leading and trailing whitespace is dropped, as the sign-in forms drop it, so `echo pw | ...` works."""
import argparse
import getpass
import sys

import access

MIN_LEN, MAX_LEN = 4, 128


def hash_password_cmd() -> int:
    pw = getpass.getpass("Password: ") if sys.stdin.isatty() else sys.stdin.readline()
    pw = pw.strip()
    if not MIN_LEN <= len(pw) <= MAX_LEN:
        print(f"A password is {MIN_LEN} to {MAX_LEN} characters.", file=sys.stderr)
        return 1
    print(access.hash_password(pw))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="manage.py", description="Gift Exchange host chores.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hash-password", help="print the hash of a password read from stdin")
    args = parser.parse_args(argv)
    if args.command == "hash-password":
        return hash_password_cmd()
    return 2


if __name__ == "__main__":
    sys.exit(main())
