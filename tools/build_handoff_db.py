#!/usr/bin/env python3
"""
b17: BH7K2
Canonical handoff DB builder — scans multiple directories into one unified SQLite index.

Configuration (env vars):
  WILLOW_HANDOFF_DIRS  colon-separated list of directories to scan (required)
  WILLOW_HANDOFF_DB    path to write handoffs.db (default: first dir / handoffs.db)

Falls back to scanning the script's own parent directory if WILLOW_HANDOFF_DIRS is unset,
so it stays compatible with agent-local invocations.
"""

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

# ── Directory resolution ─────────────────────────────────────────────────────

_dirs_env = os.environ.get("WILLOW_HANDOFF_DIRS", "")
if _dirs_env:
    SCAN_DIRS = [Path(p) for p in _dirs_env.split(":") if p.strip()]
else:
    SCAN_DIRS = [Path(__file__).parent]

_db_env = os.environ.get("WILLOW_HANDOFF_DB", "")
DB_PATH = Path(_db_env) if _db_env else SCAN_DIRS[0] / "handoffs.db"

_SKIP = {"build_handoff_db.py", "handoffs.db"}


# ── File classification ──────────────────────────────────────────────────────

def classify_file(filename: str) -> str:
    name = filename.lower()
    if name.startswith("handoff-") and name.endswith(".md"):
        return "pigeon"
    if name.startswith("session_handoff") and name.endswith(".md"):
        return "session"
    if name.startswith("daily_log") and name.endswith(".md"):
        return "daily_log"
    if name.startswith("overnight_stack") and name.endswith(".md"):
        return "overnight"
    if "performance_review" in name:
        return "review"
    if "handoff" in name and name.endswith(".md"):
        return "session"
    return "other"


def date_from_filename(filename: str) -> str | None:
    m = re.search(r"(\d{4})(\d{2})(\d{2})_?(\d{4})?", filename)
    if m:
        d = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        if m.group(4):
            d += f" {m.group(4)[:2]}:{m.group(4)[2:]}"
        return d
    m = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    if m:
        return m.group(1)
    return None


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_session_meta(content: str, filename: str = "") -> dict:
    result = {}
    m = re.search(r"session_id:\s*(\S+)", content)
    if m:
        result["session_id"] = m.group(1)
    m = re.search(r"^-\s*date:\s*(.+)$", content, re.MULTILINE)
    if m:
        result["handoff_date"] = m.group(1).strip()
    else:
        m = re.search(r"^Date:\s*(.+)$", content, re.MULTILINE)
        if m:
            result["handoff_date"] = m.group(1).strip()
        elif filename:
            result["handoff_date"] = date_from_filename(filename)
    m = re.search(r"turns:\s*(\d+)", content)
    if m:
        result["turns"] = int(m.group(1))
    m = re.search(r"tools_used:\s*(.+)", content)
    if m:
        result["tools_used"] = json.dumps([t.strip() for t in m.group(1).split(",")])
    if "## LAST_USER_MESSAGES" in content and "## KEY_ACTIONS" in content:
        block = content[content.find("## LAST_USER_MESSAGES"):content.find("## KEY_ACTIONS")]
        msgs = re.findall(r"^-\s(.+)$", block, re.MULTILINE)
        if msgs:
            result["last_messages"] = json.dumps(msgs)
    if "## KEY_ACTIONS" in content:
        block = content[content.find("## KEY_ACTIONS"):]
        actions = re.findall(r"\[(\w[^\]]+)\]", block)
        if actions:
            result["key_actions"] = json.dumps(actions)
    return result


def parse_session_handoff(content: str, filename: str = "") -> dict:
    result = parse_session_meta(content, filename)
    for marker in ("**Open Threads**", "## Open Threads"):
        if marker in content:
            start = content.find(marker) + len(marker)
            block = re.split(r"\n(?=##|\n---)", content[start:])[0]
            threads = re.findall(r"^[-*]\s(.+)$", block, re.MULTILINE)
            if threads:
                result["open_threads"] = json.dumps(threads)
            break
    for marker in ("## 17 Questions", "## Questions"):
        if marker in content:
            section = content[content.find(marker):]
            questions = re.findall(r"^\d+\.\s(.+)$", section, re.MULTILINE)
            if questions:
                result["questions"] = json.dumps(questions)
            break
    m = re.search(r"\*\*What Happened\*\*\n(.+?)(?=\n\*\*|\n---)", content, re.DOTALL)
    if m:
        result["summary"] = m.group(1).strip()
    elif "## The Session" in content:
        section = content[content.find("## The Session") + len("## The Session"):]
        paras = [p.strip() for p in section.split("\n\n") if p.strip()]
        if paras:
            result["summary"] = paras[0][:500]
    if not result.get("summary") and "LLM_DENSE_BEGIN" in content:
        dense = re.search(r"LLM_DENSE_BEGIN\n(.+?)LLM_DENSE_END", content, re.DOTALL)
        if dense:
            result["summary"] = dense.group(1).strip()[:500]
    if not result.get("summary") and "## Gaps" in content:
        start = content.find("## Gaps") + len("## Gaps")
        block = re.split(r"\n(?=##|\n---)", content[start:])[0]
        text = block.strip()
        if text:
            result["summary"] = text[:500]
    if not result.get("open_threads") and "## Gaps" in content:
        start = content.find("## Gaps") + len("## Gaps")
        block = re.split(r"\n(?=##|\n---)", content[start:])[0]
        threads = re.findall(r"^[-*]\s(.+)$", block, re.MULTILINE)
        if threads:
            result["open_threads"] = json.dumps(threads)
    if not result.get("questions") and "## Prompt" in content:
        start = content.find("## Prompt") + len("## Prompt")
        block = re.split(r"\n(?=##|\n---)", content[start:])[0]
        text = block.strip()
        if text:
            result["questions"] = json.dumps([text[:1000]])
    return result


# ── Discovery ────────────────────────────────────────────────────────────────

def collect_files(scan_dirs: list[Path]) -> list[Path]:
    """Walk each dir, deduplicate by filename (first dir wins), return sorted list."""
    seen: dict[str, Path] = {}
    for d in scan_dirs:
        if not d.exists():
            print(f"  SKIP (not found): {d}")
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            if f.name in _SKIP:
                continue
            if f.name not in seen:
                seen[f.name] = f
    return sorted(seen.values(), key=lambda f: f.name)


# ── Build ────────────────────────────────────────────────────────────────────

def build_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE files (
            id          INTEGER PRIMARY KEY,
            filename    TEXT NOT NULL,
            filepath    TEXT NOT NULL,
            file_type   TEXT,
            file_size   INTEGER,
            mtime       TEXT,
            indexed_at  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE handoffs (
            id            INTEGER PRIMARY KEY,
            file_id       INTEGER REFERENCES files(id),
            file_type     TEXT,
            session_id    TEXT,
            handoff_date  TEXT,
            turns         INTEGER,
            tools_used    TEXT,
            last_messages TEXT,
            key_actions   TEXT,
            open_threads  TEXT,
            questions     TEXT,
            summary       TEXT,
            raw_content   TEXT
        );
        CREATE INDEX idx_handoffs_date    ON handoffs(handoff_date);
        CREATE INDEX idx_handoffs_session ON handoffs(session_id);
        CREATE INDEX idx_files_type       ON files(file_type);
    """)

    files = collect_files(SCAN_DIRS)
    file_count = handoff_count = 0

    for f in files:
        stat = f.stat()
        ftype = classify_file(f.name)
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()
        cur.execute(
            "INSERT INTO files (filename, filepath, file_type, file_size, mtime) VALUES (?,?,?,?,?)",
            (f.name, str(f), ftype, stat.st_size, mtime),
        )
        file_id = cur.lastrowid
        file_count += 1

        if ftype in ("pigeon", "session", "daily_log", "overnight", "review"):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                content = f"[read error: {e}]"
            parsed = (
                parse_session_handoff(content, f.name) if ftype == "session"
                else parse_session_meta(content, f.name) if ftype == "pigeon"
                else {}
            )
            cur.execute("""
                INSERT INTO handoffs
                    (file_id, file_type, session_id, handoff_date, turns,
                     tools_used, last_messages, key_actions, open_threads,
                     questions, summary, raw_content)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                file_id, ftype,
                parsed.get("session_id"), parsed.get("handoff_date"), parsed.get("turns"),
                parsed.get("tools_used"), parsed.get("last_messages"), parsed.get("key_actions"),
                parsed.get("open_threads"), parsed.get("questions"), parsed.get("summary"),
                content,
            ))
            handoff_count += 1

    conn.commit()
    conn.close()

    print(f"Built {DB_PATH}")
    print(f"  Scanned dirs ({len(SCAN_DIRS)}):")
    for d in SCAN_DIRS:
        status = "ok" if d.exists() else "missing"
        print(f"    [{status}] {d}")
    print(f"  {file_count} files indexed")
    print(f"  {handoff_count} handoffs parsed")
    print(f"  DB size: {DB_PATH.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    build_db()
