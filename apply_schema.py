"""Apply schema.sql to whatever database get_conn() points at (DATABASE_URL, else local)."""
from db import get_conn


def main():
    sql = open("schema.sql", encoding="utf-8").read()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY 1")
        print("tables:", [r[0] for r in cur.fetchall()])


if __name__ == "__main__":
    main()