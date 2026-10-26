"""Run a .sql file (or one query) against whatever db.py points at, print each result as a table.

    python runsql.py sql/00_inventory.sql
    python runsql.py -c "SELECT count(*) FROM measurements"

Statements are split on ';' — so keep ';' out of comments.
"""

import argparse

from db import get_conn


def print_rows(cur):
    cols = [d.name for d in cur.description]
    rows = cur.fetchall()
    widths = [max(len(c), *(len(str(r[i])) for r in rows)) if rows else len(c)
              for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    print(f"({len(rows)} rows)\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="path to a .sql file")
    ap.add_argument("-c", dest="command", help="a single SQL statement instead of a file")
    args = ap.parse_args()
    sql = args.command if args.command else open(args.file, encoding="utf-8").read()

    with get_conn() as conn, conn.cursor() as cur:
        for statement in [s.strip() for s in sql.split(";") if s.strip()]:
            print(">>", statement.splitlines()[0][:90])
            cur.execute(statement)
            if cur.description is None:          # not a SELECT: nothing to print
                print(f"-- ok, {cur.rowcount} rows affected\n")
            else:
                print_rows(cur)


if __name__ == "__main__":
    main()