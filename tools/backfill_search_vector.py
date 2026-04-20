#!/usr/bin/env python3
"""
backfill_search_vector.py — One-time migration.
Populates search_vector for all knowledge atoms missing it.
b17: BKSV1
"""
import os
import psycopg2

def main():
    conn = psycopg2.connect(
        dbname=os.environ.get("WILLOW_PG_DB", "willow"),
        user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
    )
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM knowledge WHERE search_vector IS NULL OR search_vector = to_tsvector('')")
    count = cur.fetchone()[0]
    print(f"Rows to update: {count}")

    if count == 0:
        print("Already fully populated.")
        cur.close()
        conn.close()
        return

    cur.execute("""
        UPDATE knowledge
        SET search_vector =
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(summary, '')), 'B')
        WHERE search_vector IS NULL OR search_vector = to_tsvector('')
    """)
    print(f"Updated: {cur.rowcount} rows")

    cur.execute("SELECT COUNT(*) FROM knowledge WHERE search_vector IS NULL OR search_vector = to_tsvector('')")
    remaining = cur.fetchone()[0]
    print(f"Remaining empty: {remaining}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
