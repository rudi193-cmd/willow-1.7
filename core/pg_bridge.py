"""
pg_bridge.py — LOAM (1.7)
===========================
L — Layer
O — Of
A — Accumulated
M — Memory

Knowledge retrieval from Willow's Postgres graph.
1.4 LOAM was SQLite FTS5. 1.5 LOAM is Postgres direct — portless.

Retrieval cascade:
  local WillowStore → Postgres (this) → fleet generation

Optional dependency. Shell and MCP server work without it (standalone mode).
"""

import os
from typing import Optional


def _pg_params() -> dict:
    """Connection params — Unix socket by default (no ports, no network)."""
    params = {
        "dbname": os.environ.get("WILLOW_PG_DB", "willow"),
        "user": os.environ.get("WILLOW_PG_USER", "sean-campbell"),
    }
    # Only add host/port if explicitly set via env vars (escape hatch)
    host = os.environ.get("WILLOW_PG_HOST")
    if host:
        params["host"] = host
        params["port"] = int(os.environ.get("WILLOW_PG_PORT", "5432"))
        params["password"] = os.environ.get("WILLOW_PG_PASS", "")
    return params


class PgBridge:
    """Bridge to Willow's Postgres knowledge graph. Optional — shell works without it."""

    def __init__(self, params: dict = None):
        import psycopg2
        self._psycopg2 = psycopg2
        self._params = params or _pg_params()
        self._conn = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._psycopg2.connect(**self._params)
            self._conn.autocommit = True
        else:
            try:
                self._conn.cursor().execute("SELECT 1")
            except Exception:
                self._conn = self._psycopg2.connect(**self._params)
                self._conn.autocommit = True
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def ping(self) -> bool:
        """Check if Postgres is reachable."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
            return True
        except Exception:
            self._conn = None
            return False

    # ── Knowledge Search ──────────────────────────────────────────────

    def search_knowledge(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search on knowledge_slim view (no content_snippet)."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            terms = " | ".join(t.strip() for t in query.split() if t.strip())
            cur.execute("""
                SELECT id, title, summary, source_type, source_id, category,
                       lattice_domain, lattice_type, lattice_status,
                       ts_rank(search_vector, to_tsquery('english', %s)) AS rank
                FROM knowledge
                WHERE search_vector @@ to_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
            """, (terms, terms, limit))
            columns = [d[0] for d in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            return results
        except Exception:
            return []

    def search_entities(self, query: str, limit: int = 20) -> list[dict]:
        """Search entities table."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, name, entity_type, first_seen, mention_count
                FROM entities
                WHERE name ILIKE %s
                ORDER BY mention_count DESC
                LIMIT %s
            """, (f"%{query}%", limit))
            columns = [d[0] for d in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            return results
        except Exception:
            return []

    def search_ganesha(self, query: str, limit: int = 20) -> list[dict]:
        """Search ganesha.atoms by title or content."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, domain, depth, source_file, created
                FROM ganesha.atoms
                WHERE title ILIKE %s OR content ILIKE %s
                ORDER BY created DESC
                LIMIT %s
            """, (f"%{query}%", f"%{query}%", limit))
            columns = [d[0] for d in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            return results
        except Exception:
            return []

    # ── Opus ─────────────────────────────────────────────────────────

    def search_opus(self, query: str, limit: int = 20) -> list[dict]:
        """Search opus.atoms by title or content."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, title, domain, depth, source_file, created
                FROM opus.atoms
                WHERE title ILIKE %s OR content ILIKE %s
                ORDER BY created DESC
                LIMIT %s
            """, (f"%{query}%", f"%{query}%", limit))
            columns = [d[0] for d in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            return results
        except Exception:
            return []

    def ingest_opus_atom(self, content: str, domain: str = "meta",
                         depth: int = 1, source_session: str = None) -> Optional[int]:
        """Write an atom to opus.atoms."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            title = content[:80].split(".")[0] if "." in content[:80] else content[:80]
            cur.execute("""
                INSERT INTO opus.atoms (content, title, domain, depth, source_session, source_file)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (content, title, domain, depth, source_session,
                  f"session:{source_session}" if source_session else None))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else None
        except Exception:
            return None

    def opus_feedback(self, domain: str = None) -> list[dict]:
        """Read opus feedback entries. If domain given, filter by it."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            if domain:
                cur.execute("SELECT id, domain, principle, source, created FROM opus.feedback WHERE domain = %s ORDER BY created", (domain,))
            else:
                cur.execute("SELECT id, domain, principle, source, created FROM opus.feedback ORDER BY created")
            columns = [d[0] for d in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            return results
        except Exception:
            return []

    def opus_feedback_write(self, domain: str, principle: str, source: str = "self") -> bool:
        """Write an opus feedback entry."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO opus.feedback (domain, principle, source, created)
                VALUES (%s, %s, %s, NOW())
            """, (domain, principle, source))
            cur.close()
            return True
        except Exception:
            return False

    def opus_journal_write(self, entry: str, session_id: str = None) -> Optional[int]:
        """Write a journal entry to opus.journal."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO opus.journal (entry, session_id, created_at)
                VALUES (%s, %s, NOW())
                RETURNING id
            """, (entry, session_id))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else None
        except Exception:
            return None

    # ── Edges ─────────────────────────────────────────────────────────

    def edges_for(self, atom_id: int) -> list[dict]:
        """Get all edges involving an atom."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT e.source_id, e.target_id, e.edge_type, e.weight,
                       s.title AS source_title, t.title AS target_title
                FROM knowledge_edges e
                LEFT JOIN knowledge s ON e.source_id = s.id
                LEFT JOIN knowledge t ON e.target_id = t.id
                WHERE e.source_id = %s OR e.target_id = %s
                ORDER BY e.weight DESC
                LIMIT 50
            """, (atom_id, atom_id))
            columns = [d[0] for d in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            return results
        except Exception:
            return []

    # ── Ingest ────────────────────────────────────────────────────────

    def ingest_atom(self, title: str, summary: str, source_type: str,
                    source_id: str, category: str = "general",
                    domain: str = None, lattice_type: str = None,
                    lattice_status: str = None) -> Optional[int]:
        """Write a new atom to the knowledge table. Returns atom id."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO knowledge (title, summary, source_type, source_id, category,
                                       lattice_domain, lattice_type, lattice_status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW()::text)
                RETURNING id
            """, (title, summary, source_type, source_id, category,
                  domain, lattice_type, lattice_status))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else None
        except Exception as e:
            self._last_ingest_error = str(e)
            return None

    def ingest_ganesha_atom(self, content: str, domain: str = "meta",
                            depth: int = 1, source_session: str = None) -> Optional[int]:
        """Write an atom to ganesha.atoms."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            title = content[:80].split(".")[0] if "." in content[:80] else content[:80]
            cur.execute("""
                INSERT INTO ganesha.atoms (content, title, domain, depth, source_session, source_file)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (content, title, domain, depth, source_session,
                  f"session:{source_session}" if source_session else None))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else None
        except Exception:
            return None

    # ── Task Queue ──────────────────────────────────────────────────────

    def submit_task(self, task: str, submitted_by: str = "ganesha",
                    agent: str = "kart") -> Optional[str]:
        """Submit a task to the queue. Returns task_id."""
        import hashlib, time
        task_id = hashlib.sha256(f"{task}{time.time()}".encode()).hexdigest()[:12]
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO kart_task_queue (task_id, submitted_by, agent, task)
                VALUES (%s, %s, %s, %s)
                RETURNING task_id
            """, (task_id, submitted_by, agent, task))
            row = cur.fetchone()
            cur.close()
            return row[0] if row else None
        except Exception:
            return None

    def task_status(self, task_id: str) -> Optional[dict]:
        """Get task status by task_id."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT task_id, submitted_by, agent, task, status, result,
                       steps, created_at, started_at, completed_at
                FROM kart_task_queue WHERE task_id = %s
            """, (task_id,))
            row = cur.fetchone()
            if not row:
                cur.close()
                return None
            columns = [d[0] for d in cur.description]
            cur.close()
            return dict(zip(columns, row))
        except Exception:
            return None

    def claim_task(self, agent: str = "kart") -> Optional[dict]:
        """Claim the oldest pending task for an agent. Returns task or None."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE kart_task_queue
                SET status = 'running', started_at = NOW()
                WHERE id = (
                    SELECT id FROM kart_task_queue
                    WHERE status = 'pending' AND agent = %s
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING task_id, task, submitted_by
            """, (agent,))
            row = cur.fetchone()
            if not row:
                cur.close()
                return None
            columns = [d[0] for d in cur.description]
            cur.close()
            return dict(zip(columns, row))
        except Exception:
            return None

    def complete_task(self, task_id: str, result: dict, steps: int = 0) -> bool:
        """Mark a task as complete with result."""
        import json as _json
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE kart_task_queue
                SET status = 'complete', result = %s, steps = %s, completed_at = NOW()
                WHERE task_id = %s
            """, (_json.dumps(result), steps, task_id))
            cur.close()
            return True
        except Exception:
            return False

    def fail_task(self, task_id: str, error: str) -> bool:
        """Mark a task as failed."""
        import json as _json
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                UPDATE kart_task_queue
                SET status = 'failed', result = %s, completed_at = NOW()
                WHERE task_id = %s
            """, (_json.dumps({"error": error}), task_id))
            cur.close()
            return True
        except Exception:
            return False

    def pending_tasks(self, agent: str = "kart", limit: int = 10) -> list[dict]:
        """List pending tasks for an agent."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT task_id, task, submitted_by, created_at
                FROM kart_task_queue
                WHERE status = 'pending' AND agent = %s
                ORDER BY created_at ASC
                LIMIT %s
            """, (agent, limit))
            columns = [d[0] for d in cur.description]
            results = [dict(zip(columns, row)) for row in cur.fetchall()]
            cur.close()
            return results
        except Exception:
            return []

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Knowledge graph stats."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            result = {}
            for table, query in [
                ("knowledge", "SELECT COUNT(*) FROM knowledge"),
                ("entities", "SELECT COUNT(*) FROM entities"),
                ("edges", "SELECT COUNT(*) FROM knowledge_edges"),
                ("ganesha_atoms", "SELECT COUNT(*) FROM ganesha.atoms"),
                ("ganesha_handoffs", "SELECT COUNT(*) FROM ganesha.handoffs"),
                ("opus_atoms", "SELECT COUNT(*) FROM opus.atoms"),
                ("opus_feedback", "SELECT COUNT(*) FROM opus.feedback"),
            ]:
                try:
                    cur.execute(query)
                    result[table] = cur.fetchone()[0]
                except Exception:
                    conn.rollback()
                    result[table] = -1
            cur.close()
            return result
        except Exception:
            return {}

    # ── BASE 17 ID generation ─────────────────────────────────────

    @staticmethod
    def gen_id(length: int = 5) -> str:
        """Generate a BASE 17 ID."""
        import time, random
        _ALPHABET = "0123456789ACEHKLNRTXZ"
        seed = int(time.time() * 1000) ^ os.getpid() ^ random.randint(0, 0xFFFFFF)
        chars = []
        for _ in range(length):
            seed, rem = divmod(seed, 17)
            chars.append(_ALPHABET[rem])
        return "".join(reversed(chars))

    # ── Agent creation ───────────────────────────────────────────

    def agent_create(self, name: str, trust: str = "WORKER", role: str = "",
                     folder_root: str = None) -> dict:
        """Create agent schema with pipeline tables + folder structure."""
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {name}")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {name}.raw_jsonls (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    filed_path TEXT,
                    turn_count INTEGER,
                    cwd TEXT,
                    file_size BIGINT,
                    status TEXT DEFAULT 'pending',
                    filed_at TIMESTAMPTZ,
                    created TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {name}.atoms (
                    id TEXT PRIMARY KEY,
                    jsonl_id TEXT,
                    content TEXT NOT NULL,
                    title TEXT,
                    domain TEXT DEFAULT 'meta',
                    depth INTEGER DEFAULT 1,
                    certainty REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'tmp',
                    source_session TEXT,
                    source_file TEXT,
                    created TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {name}.edges (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_schema TEXT NOT NULL DEFAULT '{name}',
                    target_id TEXT NOT NULL,
                    target_schema TEXT NOT NULL DEFAULT '{name}',
                    edge_type TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    status TEXT DEFAULT 'tmp',
                    created TIMESTAMPTZ DEFAULT now(),
                    UNIQUE(source_id, source_schema, target_id, target_schema, edge_type)
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {name}.feedback (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    domain TEXT NOT NULL,
                    principle TEXT NOT NULL,
                    source TEXT DEFAULT 'self',
                    created TIMESTAMPTZ DEFAULT now()
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {name}.handoffs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    session_id UUID NOT NULL DEFAULT gen_random_uuid(),
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    session_date DATE,
                    working_dir TEXT,
                    turn_count INTEGER,
                    tools_used TEXT[],
                    b17 TEXT,
                    pointer_path TEXT,
                    created TIMESTAMPTZ DEFAULT now()
                )
            """)
            if folder_root:
                import pathlib
                for sub in ("raw", ".tmp", "cache"):
                    pathlib.Path(folder_root, sub).mkdir(parents=True, exist_ok=True)
            cur.close()
            return {"status": "created", "schema": name, "tables": [
                "raw_jsonls", "atoms", "edges", "feedback", "handoffs"
            ]}
        except Exception as e:
            cur.close()
            return {"status": "error", "error": str(e)}

    # ── Jeles: register + extract from JSONL ─────────────────────

    def jeles_register_jsonl(self, agent: str, jsonl_path: str,
                             session_id: str, cwd: str = None,
                             turn_count: int = 0, file_size: int = 0) -> dict:
        """Register a raw JSONL in the agent's schema. Returns BASE 17 ID."""
        jid = self.gen_id()
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(f"""
                INSERT INTO {agent}.raw_jsonls (id, session_id, source_path, cwd, turn_count, file_size, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                ON CONFLICT (id) DO NOTHING
                RETURNING id
            """, (jid, session_id, jsonl_path, cwd, turn_count, file_size))
            row = cur.fetchone()
            cur.close()
            return {"id": jid if row else None, "status": "registered" if row else "duplicate"}
        except Exception as e:
            cur.close()
            return {"error": str(e)}

    def jeles_extract_atom(self, agent: str, jsonl_id: str, content: str,
                           domain: str = "meta", depth: int = 1,
                           certainty: float = 0.98, title: str = None) -> dict:
        """Write an extracted atom to the agent's .tmp (status='tmp'). Requires certainty > 0.95."""
        if certainty < 0.95:
            return {"status": "rejected", "reason": f"certainty {certainty} < 0.95 threshold"}
        aid = self.gen_id()
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(f"""
                INSERT INTO {agent}.atoms (id, jsonl_id, content, title, domain, depth, certainty, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'tmp')
                RETURNING id
            """, (aid, jsonl_id, content, title, domain, depth, certainty))
            cur.close()
            return {"id": aid, "status": "tmp"}
        except Exception as e:
            cur.close()
            return {"error": str(e)}

    # ── Binder: file JSONL + propose edges ───────────────────────

    def binder_file(self, agent: str, jsonl_id: str, dest_path: str) -> dict:
        """Move JSONL to agent's .tmp/ folder, update status."""
        import shutil
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT source_path FROM {agent}.raw_jsonls WHERE id = %s", (jsonl_id,))
            row = cur.fetchone()
            if not row:
                cur.close()
                return {"error": "jsonl not found", "id": jsonl_id}
            source = row[0]
            import pathlib
            pathlib.Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest_path)
            cur.execute(f"""
                UPDATE {agent}.raw_jsonls
                SET filed_path = %s, status = 'filed_tmp', filed_at = now()
                WHERE id = %s
            """, (dest_path, jsonl_id))
            cur.close()
            return {"id": jsonl_id, "status": "filed_tmp", "path": dest_path}
        except Exception as e:
            cur.close()
            return {"error": str(e)}

    def binder_propose_edge(self, agent: str, source_atom: str, target_atom: str,
                            edge_type: str) -> dict:
        """Propose an edge found while filing. Status='tmp' until ratified."""
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(f"""
                INSERT INTO {agent}.edges (source_id, target_id, edge_type, status)
                VALUES (%s, %s, %s, 'tmp')
                ON CONFLICT DO NOTHING
            """, (source_atom, target_atom, edge_type))
            cur.close()
            return {"status": "proposed", "edge": f"{source_atom} --{edge_type}--> {target_atom}"}
        except Exception as e:
            cur.close()
            return {"error": str(e)}

    # ── Ratification ─────────────────────────────────────────────

    def ratify(self, agent: str, jsonl_id: str, approve: bool = True,
               cache_path: str = None) -> dict:
        """Ratify or reject a JSONL and all its extracted atoms/edges."""
        new_status = "ratified" if approve else "rejected"
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            if approve and cache_path:
                cur.execute(f"SELECT filed_path FROM {agent}.raw_jsonls WHERE id = %s", (jsonl_id,))
                row = cur.fetchone()
                if row and row[0]:
                    import shutil, pathlib
                    pathlib.Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(row[0], cache_path)
                cur.execute(f"""
                    UPDATE {agent}.raw_jsonls SET status = %s, filed_path = %s WHERE id = %s
                """, (new_status, cache_path, jsonl_id))
            else:
                cur.execute(f"""
                    UPDATE {agent}.raw_jsonls SET status = %s WHERE id = %s
                """, (new_status, jsonl_id))
            cur.execute(f"""
                UPDATE {agent}.atoms SET status = %s WHERE jsonl_id = %s
            """, (new_status, jsonl_id))
            atoms_updated = cur.rowcount
            cur.execute(f"""
                UPDATE {agent}.edges SET status = %s
                WHERE source_id IN (SELECT id FROM {agent}.atoms WHERE jsonl_id = %s)
            """, (new_status, jsonl_id))
            edges_updated = cur.rowcount
            if not approve:
                cur.execute(f"SELECT filed_path FROM {agent}.raw_jsonls WHERE id = %s", (jsonl_id,))
                row = cur.fetchone()
                if row and row[0]:
                    import pathlib
                    p = pathlib.Path(row[0])
                    if p.exists() and '.tmp' in str(p):
                        p.unlink()
            cur.close()
            return {
                "status": new_status,
                "jsonl_id": jsonl_id,
                "atoms_updated": atoms_updated,
                "edges_updated": edges_updated,
            }
        except Exception as e:
            cur.close()
            return {"error": str(e)}


def try_connect() -> Optional[PgBridge]:
    """Try to create a PgBridge. Returns None if Postgres unavailable."""
    try:
        bridge = PgBridge()
        if bridge.ping():
            return bridge
        return None
    except Exception:
        return None
