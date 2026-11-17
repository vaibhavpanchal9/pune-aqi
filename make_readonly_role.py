"""Step 12. A database user for the public API that can read five tables and do nothing else.

    python make_readonly_role.py            # create the role, save its connection string in .env
    python make_readonly_role.py --rotate   # give the role a new password (the old one stops working)
    python make_readonly_role.py --check    # only test the saved connection string: read yes, write no

Why: the API is about to be on a public address. Until now it has used the same credentials as the
ingestion job, which can insert, delete and drop. If the API's credentials ever leak -- a log line, a
misconfigured host -- the damage should be "someone can read public air-quality numbers", not
"someone can delete twenty months of data". Same idea as the GitHub token that can only start a workflow.

What it does, using the owner credentials in .env (DATABASE_URL):
  1. creates the login role `aqi_api` with a random 32-character password generated on this machine
  2. grants CONNECT on the database, USAGE on schema public, SELECT on the five tables the API reads
  3. sets a 5 second statement timeout and a limit of 10 connections for that role
  4. writes the role's connection string to .env as API_DATABASE_URL (the file is git-ignored)
  5. connects AS the new role and proves it: a SELECT works, a DELETE is refused

The password is never printed. Copy API_DATABASE_URL from .env into the host's settings (Render),
nowhere else: not into the repository, not into a chat.
"""

import argparse
import os
import secrets
import string
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

ROLE = "aqi_api"
TABLES = ["measurements", "ingestion_runs", "forecasts", "sensors", "locations"]
ENV_FILE = Path(__file__).resolve().parent / ".env"
ENV_KEY = "API_DATABASE_URL"


def new_password(length=32):
    """Letters, digits, '-' and '_': safe inside a URL, and always with one of each kind."""
    alphabet = string.ascii_letters + string.digits + "-_"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in "-_" for c in pw)):
            return pw


def url_for_role(owner_url, role, password):
    """The owner's connection string with the user and password swapped; host, database, options kept."""
    u = urlparse(owner_url)
    host = u.hostname + (f":{u.port}" if u.port else "")
    return urlunparse(u._replace(netloc=f"{role}:{password}@{host}"))


def save_to_env(key, value, path=None):
    """Set key=value in the .env file, replacing an existing line for the same key."""
    path = path or ENV_FILE
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if not line.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    tmp = path.with_name(path.name + ".writing")           # write beside it, then swap: never a half-written .env
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)


def create_or_rotate(conn, role, password, tables):
    """Create the role (or change its password) and set its rights. Returns 'created' or 'rotated'."""
    ident = sql.Identifier(role)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        exists = cur.fetchone() is not None
        verb = sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s") if exists else sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s")
        cur.execute(verb.format(ident), (password,))
        cur.execute("SELECT current_database()")
        database = cur.fetchone()[0]
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), ident))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident))
        cur.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(
            sql.SQL(", ").join(sql.Identifier(t) for t in tables), ident))
        cur.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '5s'").format(ident))
        cur.execute(sql.SQL("ALTER ROLE {} CONNECTION LIMIT 10").format(ident))
    conn.commit()
    return "rotated" if exists else "created"


def check(url, tables):
    """Connect as the role. Returns (rows readable per table, whether a write was refused)."""
    conn = psycopg2.connect(url)
    try:
        counts = {}
        with conn.cursor() as cur:
            for t in tables:
                cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t)))
                counts[t] = cur.fetchone()[0]
        conn.rollback()
        refused = False
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM forecasts WHERE false")      # deletes nothing even if it were allowed
        except psycopg2.errors.InsufficientPrivilege:
            refused = True
        conn.rollback()
        return counts, refused
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotate", action="store_true", help="give the existing role a new password")
    ap.add_argument("--check", action="store_true", help="only test the saved API_DATABASE_URL")
    args = ap.parse_args()

    load_dotenv(ENV_FILE)
    owner_url = os.getenv("DATABASE_URL")
    saved = os.getenv(ENV_KEY)
    if not owner_url:
        raise SystemExit("DATABASE_URL is not set in .env")

    if args.check or (saved and not args.rotate):
        if not saved:
            raise SystemExit(f"{ENV_KEY} is not in .env yet. Run without --check to create the role.")
        print(f"{ENV_KEY} is already in .env; testing it (use --rotate for a new password)")
    else:
        password = new_password()
        conn = psycopg2.connect(owner_url)
        try:
            what = create_or_rotate(conn, ROLE, password, TABLES)
        finally:
            conn.close()
        saved = url_for_role(owner_url, ROLE, password)
        save_to_env(ENV_KEY, saved)
        print(f"role {ROLE}: {what}. Connection string saved to .env as {ENV_KEY} (password not shown).")

    counts, refused = check(saved, TABLES)
    print("read  : " + ", ".join(f"{t} {n:,}" for t, n in counts.items()))
    print("write : " + ("refused (permission denied) -- as it should be" if refused else "ALLOWED -- this role is NOT read-only"))
    if not refused:
        raise SystemExit(1)
    print(f"host  : {urlparse(saved).hostname}   user: {urlparse(saved).username}")


if __name__ == "__main__":
    main()
