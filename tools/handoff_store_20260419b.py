import shutil, psycopg2

AGENT    = "hanuman"
TITLE    = "Yggdrasil v8 Pipeline + M2.7 Distillation"
FILENAME = "SESSION_HANDOFF_20260419_heimdallr_b.md"
SRC      = f"/home/sean-campbell/Ashokoa/agents/{AGENT}/index/haumana_handoffs/{FILENAME}"
DST      = f"/home/sean-campbell/Desktop/{FILENAME}"

try:
    conn = psycopg2.connect(dbname="willow", user="sean-campbell")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO {AGENT}.handoffs (title, content, pointer_path, session_date) VALUES (%s, %s, %s, CURRENT_DATE)",
        (TITLE, "See file: " + SRC, FILENAME)
    )
    cur.close()
    conn.close()
    print("pointer ok")
except Exception as e:
    print(f"pg skip: {e}")

shutil.copy2(SRC, DST)
print(f"{FILENAME} on Desktop")
