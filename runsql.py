"""Run a .sql file (or one query) against whatever db.py points at, print each result as a table.

    python runsql.py sql/00_inventory.sql
    python runsql.py -c "SELECT count(*) FROM measurements"

Comments (-- ...) are stripped BEFORE splitting on ';', so a ';' inside a comment is harmless.
The last comment line before a statement is printed as its label.
"""

import argparse

from db import get_conn


def statements(sql):
    """Yield (label, statement) pairs from a .sql text."""
    label, code = "", []
    for line in sql.splitlines():
        head, _, comment = line.partition("--")
        if comment.strip() and not head.strip() and not code:
            label = comment.strip()          # a comment-only line before the statement
        if head.strip():
            code.append(head)
        if ";" in head:
            stmt = "\n".join(code).replace(";", "").strip()
            if stmt:
                yield label, stmt
            label, code = "", []
    stmt = "\n".join(code).replace(";", "").strip()
    if stmt:                                 # a last statement without a ';'
        yield label, stmt


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
        for label, stmt in statements(sql):
            print(">>", (label or stmt.splitlines()[0])[:90])
            cur.execute(stmt)
            if cur.description is None:          # not a SELECT: nothing to print
                print(f"-- ok, {cur.rowcount} rows affected\n")
            else:
                print_rows(cur)


if __name__ == "__main__":
    main()