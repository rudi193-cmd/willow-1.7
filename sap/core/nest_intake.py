"""
nest_intake.py — Nest file staging and review pipeline (SAP/portless)
======================================================================
b17: LENN0
ΔΣ=42

Flow:
  1. scan_nest()      — scan WILLOW_NEST_DIR, stage all new files
  2. stage_file()     — read snippet + classify + match entities → pending
  3. get_queue()      — return pending items
  4. confirm_review() — Sean ratifies → file moves + knowledge ingested

Routing (two-partition):
  Personal files → /home/sean-campbell/Ashokoa/Filed/{category}/
  System files   → /media/willow/{project}/   (direct to project home)

File stays in Nest until Sean confirms. Nothing touches the graph until
ratified. Dual Commit: AI proposes, human ratifies.

Authority: Sean Campbell
"""

import hashlib
import json
import logging
import os
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("nest_intake")

UTC = timezone.utc

# ── Paths ──────────────────────────────────────────────────────────────────────

def _nest_dir() -> Path:
    """Nest directory — where Sean drops files for intake."""
    return Path(os.environ.get("WILLOW_NEST_DIR", "/home/sean-campbell/Desktop/Nest"))


def _ashokoa_filed() -> Path:
    """Root for personal filed content (Sean's home partition)."""
    return Path(os.environ.get("WILLOW_FILED_DIR", "/home/sean-campbell/Ashokoa/Filed"))


def _willow_partition() -> Path:
    """Root for system/project content (Willow partition)."""
    return Path(os.environ.get("WILLOW_PARTITION_DIR", "/media/willow"))


def _personal_dir() -> Path:
    """Root for personal content outside Ashokoa (photos, knowledge, policy)."""
    return Path(os.environ.get("WILLOW_PERSONAL_DIR", Path.home() / "personal"))


# ── Destination path validation ───────────────────────────────────────────────

def _allowed_dest_roots() -> list:
    """Return the list of allowed destination root directories."""
    return [
        _ashokoa_filed(),
        _willow_partition(),
        _personal_dir(),
    ]


def _validate_dest_path(path: str) -> str:
    """Resolve destination path and verify it's within an allowed root."""
    if not path or not path.strip():
        raise ValueError("Empty destination path")
    resolved = Path(path).resolve()
    for root in _allowed_dest_roots():
        try:
            resolved.relative_to(root.resolve())
            return str(resolved)
        except ValueError:
            continue
    raise ValueError(f"Destination {path!r} is outside all allowed roots")


# ── DB connection (LOAM / pg_bridge) ──────────────────────────────────────────

def _connect():
    """Open a psycopg2 connection via pg_bridge params."""
    import psycopg2
    import os
    params = {
        "dbname": os.environ.get("WILLOW_PG_DB", "willow"),
        "user":   os.environ.get("WILLOW_PG_USER", "sean-campbell"),
    }
    host = os.environ.get("WILLOW_PG_HOST")
    if host:
        params["host"] = host
        params["port"] = int(os.environ.get("WILLOW_PG_PORT", "5432"))
        params["password"] = os.environ.get("WILLOW_PG_PASS", "")
    return psycopg2.connect(**params)


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA_CREATED = False

def _ensure_schema():
    """Create nest_review_queue table if it doesn't exist."""
    global _SCHEMA_CREATED
    if _SCHEMA_CREATED:
        return
    conn = _connect()
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nest_review_queue (
                id               SERIAL PRIMARY KEY,
                filename         TEXT NOT NULL,
                original_path    TEXT NOT NULL,
                file_hash        TEXT,
                ocr_text         TEXT,
                proposed_summary TEXT,
                proposed_category TEXT,
                proposed_path    TEXT,
                matched_entities JSONB DEFAULT '[]',
                status           TEXT NOT NULL DEFAULT 'pending',
                user_summary     TEXT,
                user_category    TEXT,
                user_path        TEXT,
                dispose_file     BOOLEAN DEFAULT FALSE,
                dispose_data     BOOLEAN DEFAULT FALSE,
                staged_at        TIMESTAMPTZ,
                reviewed_at      TIMESTAMPTZ
            )
        """)
        cur.close()
        _SCHEMA_CREATED = True
        logger.info("NEST: schema ready")
    except Exception as e:
        logger.error(f"NEST: schema creation failed: {e}")
    finally:
        conn.close()


# ── File snippet extraction ────────────────────────────────────────────────────

def _read_snippet(file_path: str, max_bytes: int = 3000) -> str:
    """Read a text snippet from a file. Binary files return empty string."""
    path = Path(file_path)
    ext = path.suffix.lower()

    # Binary formats — skip text extraction
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mp3",
               ".wav", ".mov", ".avi", ".pdf", ".zip", ".tar", ".gz"):
        return ""

    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
        # Try UTF-8, fall back to latin-1
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return raw.decode("latin-1", errors="replace")
    except Exception as e:
        logger.warning(f"NEST: snippet read failed for {path.name}: {e}")
        return ""


# ── Proposed destination path ──────────────────────────────────────────────────

# Personal categories → Ashokoa/Filed/
_PERSONAL_ROUTES = {
    "journal":           "reference/ideas-journal",
    "narrative":         "narrative",
    "handoff":           "reference/handoffs",
    "session":           "reference/handoffs",
    "reference":         "reference/general",
    "conversation":      "reference/conversations",
    "personal":          "reference/personal",
    "media":             "reference/screenshots",
    "legal":             "legal",
    "legal_agreement":   "legal/contracts",
    "terms_of_service":  "legal/contracts",
    "contract":          "legal/contracts",
}

# Personal subcategory overrides
_PERSONAL_PHOTO_KEYWORDS = ["feeld", "facebook", "messages", "tinder", "hinge"]
_CAMERA_RE = re.compile(r"^\d{8}_\d{6}|\d{13}\.")

# System categories → /media/willow/{project}/
# Maps (category, keyword hints) → relative path under /media/willow/
_SYSTEM_ROUTES = {
    "code":          "projects",
    "architecture":  "projects",
    "specs":         "projects",
    "utety":         "projects/utety",
    "agent_task":    "agents",
    "agent_chain":   "agents",
    "corpus":        "training_data/corpus",
    "die-namic":     "projects/die-namic",
    "safe":          "projects/safe",
    "system":        "projects",
}

# Known project keyword → subdirectory under /media/willow/projects/
_PROJECT_KEYWORD_MAP = {
    "willow":       "willow-1.7",
    "willow-1.7":   "willow-1.7",
    "willow-1.4":   "willow-1.4",
    "safe":         "safe",
    "utety":        "utety",
    "die-namic":    "die-namic",
    "nasa":         "nasa-archive",
    "gazelle":      "gazelle",
    "kart":         "kart",
    "aios":         "aios-minimal",
    "yggdrasil":    "yggdrasil",
}


def _proposed_path(filename: str, category: str, matched_entities: list) -> str:
    """
    Propose a destination path for a staged file.

    Personal files  → /home/sean-campbell/Ashokoa/Filed/{subfolder}/{filename}
    System files    → /media/willow/{project}/{filename}
    """
    name_lower = filename.lower()
    entity_names = {e["name"].lower() for e in matched_entities
                    if e.get("confidence", 0) >= 0.7}

    # ── System routing ─────────────────────────────────────────────────────────
    if category in _SYSTEM_ROUTES:
        # Check entity names for known project keywords
        for kw, proj in _PROJECT_KEYWORD_MAP.items():
            if kw in entity_names or kw in name_lower:
                dest = _willow_partition() / "projects" / proj / filename
                return str(dest)
        # Fall back to category-based system route
        rel = _SYSTEM_ROUTES[category]
        return str(_willow_partition() / rel / filename)

    # ── Photo routing (personal) ───────────────────────────────────────────────
    ext = Path(filename).suffix.lower()
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        if any(k in name_lower for k in _PERSONAL_PHOTO_KEYWORDS):
            return str(_personal_dir() / "photos" / "personal" / filename)
        if _CAMERA_RE.match(filename):
            return str(_personal_dir() / "photos" / "camera" / filename)
        return str(_ashokoa_filed() / "reference" / "screenshots" / filename)

    # ── Knowledge (personal, different root) ──────────────────────────────────
    if category in ("knowledge",):
        return str(_personal_dir() / "knowledge" / filename)

    # ── Standard personal routing ──────────────────────────────────────────────
    subfolder = _PERSONAL_ROUTES.get(category, "reference/general")
    return str(_ashokoa_filed() / subfolder / filename)


# ── Entity matching (against LOAM) ────────────────────────────────────────────

def _match_entities(filename: str, ocr_text: str) -> list:
    """Search LOAM knowledge graph for entities matching this file's content."""
    name_stem = Path(filename).stem.lower()
    parts = name_stem.replace("_", " ").replace("-", " ").split()
    search_terms = set(parts)

    if ocr_text:
        ocr_parts = ocr_text[:500].lower().replace("\n", " ").split()
        search_terms.update(ocr_parts)

    noise = {
        "screenshot", "img", "image", "jpg", "png", "jpeg", "the", "and",
        "for", "of", "to", "a", "an", "in", "on", "at", "2025", "2026",
        "messages", "android", "with", "from", "this", "that", "not", "are",
        "was", "were", "have", "has", "will", "would", "could", "should",
        "bash", "grep", "glob", "read", "write", "edit", "pip", "npm",
        "node", "curl", "wget", "git", "ssh", "cat", "head", "tail",
        "code", "html", "json", "yaml", "true", "false", "null", "none",
        "self", "class", "def", "import", "return", "async", "await",
        "file", "path", "data", "name", "text", "value", "error", "status",
    }
    search_terms -= noise

    matched = []
    seen_ids = set()

    try:
        conn = _connect()
        conn.autocommit = True
        cur = conn.cursor()
        for term in search_terms:
            if len(term) < 4:
                continue
            cur.execute(
                "SELECT id, name, entity_type, mention_count FROM entities "
                "WHERE lower(name) = %s OR lower(name) LIKE %s LIMIT 5",
                (term.lower(), f"{term.lower()}%")
            )
            for row in cur.fetchall():
                eid, ename, etype, ecount = row
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)
                confidence = 0.9 if term.lower() == ename.lower() else 0.6
                matched.append({
                    "id": eid, "name": ename, "entity_type": etype,
                    "mention_count": ecount, "confidence": confidence,
                })
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"NEST: entity match failed: {e}")

    matched.sort(key=lambda x: (x["confidence"], x["mention_count"]), reverse=True)
    return matched[:10]


# ── TOS policy check ───────────────────────────────────────────────────────────

def _data_policy_file() -> Path:
    """Sean's personal data policy — used for TOS tripwire context."""
    return Path(os.environ.get(
        "WILLOW_DATA_POLICY_FILE",
        _personal_dir() / "sean_data_policy.md"
    ))

_TOS_TRIPWIRES = [
    ("sells_personal_data",   "BLOCK", [{"sell", "data"}, {"sell", "personal"}, {"share", "third party", "sell"}]),
    ("perpetual_irrevocable", "BLOCK", [{"perpetual", "irrevocable"}]),
    ("ai_output_ownership",   "BLOCK", [{"ownership", "generated"}, {"own", "output"}, {"rights", "ai generated"}]),
    ("arbitration_waiver",    "FLAG",  [{"arbitration"}, {"binding arbitration"}]),
    ("class_action_waiver",   "FLAG",  [{"class action"}, {"class-action"}]),
    ("data_broker_sharing",   "FLAG",  [{"partners", "share"}, {"affiliates", "share", "data"}, {"third parties", "data"}]),
    ("biometric_collection",  "FLAG",  [{"biometric"}, {"facial recognition"}, {"voice print"}]),
]

_LEGAL_CATEGORIES = {"legal_agreement", "terms_of_service", "contract", "legal", "legal_document"}


def _check_tos_policy(text: str) -> dict:
    if not text:
        return {"verdict": "FLAG", "triggered": [{"rule": "no_text_extracted", "verdict": "FLAG"}],
                "policy_file": str(_data_policy_file())}
    lower = text.lower()
    triggered = []
    for label, verdict, phrase_sets in _TOS_TRIPWIRES:
        for phrase_set in phrase_sets:
            if all(phrase in lower for phrase in phrase_set):
                triggered.append({"rule": label, "verdict": verdict})
                break
    if any(t["verdict"] == "BLOCK" for t in triggered):
        overall = "BLOCK"
    elif any(t["verdict"] == "FLAG" for t in triggered):
        overall = "FLAG"
    else:
        overall = "PASS"
    return {"verdict": overall, "triggered": triggered, "policy_file": str(_data_policy_file())}


# ── Stage a file ───────────────────────────────────────────────────────────────

def stage_file(file_path: str, file_hash: str = None) -> dict:
    """
    Read + classify + match entities → insert into nest_review_queue.
    File is NOT moved. Returns the queue item dict.
    """
    _ensure_schema()
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Already staged and pending?
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "SELECT id, status FROM nest_review_queue "
        "WHERE filename=%s ORDER BY id DESC LIMIT 1",
        (path.name,)
    )
    existing = cur.fetchone()
    cur.close()
    conn.close()
    if existing and existing[1] == "pending":
        return get_queue_item(existing[0])

    # Extract snippet
    ocr_text = _read_snippet(str(path))

    # Classify
    try:
        from sap.core.classifier import classify
        result = classify(path.name, ocr_text)
        proposed_category = result.get("category", "reference")
        proposed_summary  = result.get("summary", "")
    except Exception as e:
        logger.warning(f"NEST: classify failed for {path.name}: {e}")
        proposed_category = "reference"
        proposed_summary  = ""

    # Match entities
    matched = _match_entities(path.name, ocr_text)

    # TOS policy check
    if proposed_category in _LEGAL_CATEGORIES:
        policy = _check_tos_policy(ocr_text)
        verdict = policy["verdict"]
        rules_hit = ", ".join(t["rule"] for t in policy["triggered"]) or "none"
        proposed_summary = f"[POLICY:{verdict}] Rules triggered: {rules_hit}\n\n" + (proposed_summary or "")
        logger.info(f"NEST: TOS policy check {path.name} → {verdict}")

    # Propose destination
    proposed_path = _proposed_path(path.name, proposed_category, matched)

    # Hash
    if not file_hash:
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            file_hash = h.hexdigest()
        except Exception:
            file_hash = None

    # Strip NUL bytes (Postgres rejects them)
    def _pg_safe(s):
        return s.replace("\x00", "") if s else s

    ocr_text          = _pg_safe(ocr_text)
    proposed_summary  = _pg_safe(proposed_summary)
    proposed_category = _pg_safe(proposed_category)
    proposed_path     = _pg_safe(proposed_path)

    now = datetime.now(UTC)
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO nest_review_queue
           (filename, original_path, file_hash, ocr_text,
            proposed_summary, proposed_category, proposed_path,
            matched_entities, status, staged_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id""",
        (path.name, str(path), file_hash, ocr_text,
         proposed_summary, proposed_category, proposed_path,
         json.dumps(matched), "pending", now)
    )
    item_id = cur.fetchone()[0]
    cur.close()
    conn.close()

    logger.info(f"NEST: staged {path.name} → #{item_id} ({proposed_category})")
    return get_queue_item(item_id)


# ── Queue access ───────────────────────────────────────────────────────────────

def get_queue(status: str = "pending") -> list:
    """Return all review queue items, optionally filtered by status."""
    _ensure_schema()
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM nest_review_queue WHERE status=%s ORDER BY staged_at DESC",
        (status,)
    )
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    cur.close()
    conn.close()
    return [_row_to_dict(cols, r) for r in rows]


def get_queue_item(item_id: int) -> dict:
    _ensure_schema()
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT * FROM nest_review_queue WHERE id=%s", (item_id,))
    row = cur.fetchone()
    cols = [d[0] for d in cur.description]
    cur.close()
    conn.close()
    if not row:
        raise KeyError(f"Queue item #{item_id} not found")
    return _row_to_dict(cols, row)


def _row_to_dict(cols, row) -> dict:
    d = dict(zip(cols, row))
    if isinstance(d.get("matched_entities"), str):
        try:
            d["matched_entities"] = json.loads(d["matched_entities"])
        except Exception:
            d["matched_entities"] = []
    return d


# ── Confirm review ─────────────────────────────────────────────────────────────

def confirm_review(
    item_id: int,
    user_summary: str = None,
    user_category: str = None,
    user_path: str = None,
    dispose_file: bool = False,
    dispose_data: bool = False,
    move_file: bool = True,
) -> dict:
    """
    Execute Sean's decision on a staged file. Dual Commit ratification.

    move_file=True, dispose_file=False → move to proposed path + ingest
    dispose_file=True, dispose_data=False → delete file + ingest data
    dispose_file=True, dispose_data=True  → delete file + no ingest
    """
    item = get_queue_item(item_id)
    if item["status"] != "pending":
        raise ValueError(f"Item #{item_id} is not pending (status={item['status']})")

    src_path = Path(item["original_path"])
    final_summary  = user_summary  or item["proposed_summary"]  or ""
    final_category = user_category or item["proposed_category"] or "reference"
    final_path     = user_path     or item["proposed_path"]

    errors = []
    filed_to = None

    # ── File disposition ───────────────────────────────────────────────────────
    if src_path.exists():
        if src_path.is_symlink():
            errors.append(f"symlink not allowed as source: {src_path.name}")
            logger.warning("NEST: rejecting symlink: %s", src_path)
        elif dispose_file:
            try:
                resolved_src = Path(src_path).resolve()
                nest_resolved = _nest_dir().resolve()
                resolved_src.relative_to(nest_resolved)
            except ValueError:
                errors.append(f"dispose_file rejected: {src_path} is outside Nest directory")
            else:
                try:
                    src_path.unlink()
                    logger.info(f"NEST: deleted {src_path.name}")
                except Exception as e:
                    errors.append(f"delete failed: {e}")
        elif move_file:
            try:
                final_path = _validate_dest_path(final_path)
            except ValueError as e:
                errors.append(f"invalid destination path: {e}")
            else:
                dest = Path(final_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    stem, suffix, i = dest.stem, dest.suffix, 1
                    while dest.exists():
                        dest = dest.parent / f"{stem}_{i}{suffix}"
                        i += 1
                try:
                    shutil.move(str(src_path), str(dest))
                    filed_to = str(dest)
                    logger.info(f"NEST: filed {src_path.name} → {dest}")
                except Exception as e:
                    errors.append(f"move failed: {e}")
    else:
        logger.warning(f"NEST: source file missing: {src_path}")

    # ── Knowledge ingest ───────────────────────────────────────────────────────
    if not dispose_data:
        try:
            _ingest_to_loam(
                filename=item["filename"],
                category=final_category,
                summary=final_summary,
                ocr_text=item.get("ocr_text") or "",
                file_hash=item.get("file_hash") or "",
            )
            logger.info(f"NEST: ingested {item['filename']} → {final_category}")
        except Exception as e:
            errors.append(f"ingest failed: {e}")
            logger.warning(f"NEST: ingest error for {item['filename']}: {e}")

    # ── Update queue record ────────────────────────────────────────────────────
    now = datetime.now(UTC)
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        """UPDATE nest_review_queue SET
           status=%s, user_summary=%s, user_category=%s, user_path=%s,
           dispose_file=%s, dispose_data=%s, reviewed_at=%s
           WHERE id=%s""",
        ("confirmed", final_summary, final_category,
         filed_to or final_path,
         dispose_file, dispose_data, now, item_id)
    )
    cur.close()
    conn.close()

    return {
        "ok": True,
        "item_id": item_id,
        "filename": item["filename"],
        "filed_to": filed_to,
        "data_ingested": not dispose_data,
        "file_deleted": dispose_file,
        "errors": errors,
    }


def _ingest_to_loam(filename: str, category: str, summary: str,
                    ocr_text: str, file_hash: str):
    """Write a knowledge atom to LOAM for this file."""
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    content = (summary + "\n\n" + ocr_text).strip() if summary else ocr_text
    now = datetime.now(UTC)
    cur.execute(
        """INSERT INTO knowledge
           (title, category, content_snippet, summary, source_type,
            provider, file_hash, created_at, updated_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT DO NOTHING""",
        (filename, category, content[:2000], summary[:500] if summary else "",
         "nest_intake", "nest_intake", file_hash, now, now)
    )
    cur.close()
    conn.close()


# ── Skip item ──────────────────────────────────────────────────────────────────

def skip_item(item_id: int) -> dict:
    """Mark an item as skipped — leaves file in Nest, no processing."""
    now = datetime.now(UTC)
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "UPDATE nest_review_queue SET status='skipped', reviewed_at=%s WHERE id=%s",
        (now, item_id)
    )
    cur.close()
    conn.close()
    return {"ok": True, "item_id": item_id, "status": "skipped"}


# ── Scan Nest ──────────────────────────────────────────────────────────────────

_SCAN_LOCK = threading.Lock()


def scan_nest() -> list:
    """
    Scan the Nest directory. Stage all new files.
    Returns list of newly staged items.
    """
    nest = _nest_dir()
    if not nest.exists():
        logger.warning(f"NEST: Nest directory not found: {nest}")
        return []

    _ensure_schema()

    # Load already-staged filenames + hashes
    conn = _connect()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT filename, file_hash FROM nest_review_queue")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    already_names  = {r[0] for r in rows}
    already_hashes = {r[1] for r in rows if r[1]}

    staged = []
    with _SCAN_LOCK:
        for item in sorted(nest.iterdir()):
            # is_file() follows symlinks on POSIX; is_symlink() must be explicit to reject them
            if not item.is_file() or item.name.startswith(".") or item.is_symlink():
                continue
            if item.name in already_names:
                continue
            # Hash check
            try:
                h = hashlib.sha256()
                with open(item, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
                fhash = h.hexdigest()
            except Exception:
                fhash = None

            if fhash and fhash in already_hashes:
                logger.debug(f"NEST: skipping duplicate: {item.name}")
                continue

            try:
                result = stage_file(str(item), fhash)
                staged.append(result)
                already_names.add(item.name)
                if fhash:
                    already_hashes.add(fhash)
            except Exception as e:
                logger.error(f"NEST: staging failed for {item.name}: {e}")

    return staged
