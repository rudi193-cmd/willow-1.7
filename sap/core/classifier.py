"""
classifier.py — File classification for Willow 1.7 (SAP/portless)
===================================================================
b17: 831C9
ΔΣ=42

Hard rules handle the obvious cases. Everything else falls back to
filename keyword matching. No agent_engine — SAP is the bus, not HTTP.
Taxonomy loads from LOAM (pg_bridge) on first call, cached in memory.

Callers:
  - nest_intake.stage_file()   — classifies at staging time
  - sap_mcp.py tools           — willow_nest_scan, willow_nest_file

Authority: Sean Campbell
"""

import json
import logging
import re

logger = logging.getLogger("willow.classifier")

# ── Taxonomy cache ─────────────────────────────────────────────────────────────

_TAXONOMY_CACHE: set | None = None

FALLBACK_CATEGORIES = {
    "session", "narrative", "architecture", "research", "reference",
    "corpus", "utety", "governance", "legal", "legal_agreement",
    "terms_of_service", "contract", "personal", "media",
    "conversation", "die-namic", "agent", "safe", "system",
    "agent_task", "agent_chain", "journal", "handoff", "code", "specs",
}


def get_valid_categories() -> set:
    """Load canonical categories from LOAM (pg_bridge). Cached after first call."""
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is not None:
        return _TAXONOMY_CACHE
    try:
        from pg_bridge import try_connect
        pg = try_connect()
        if pg:
            cur = pg.cursor()
            cur.execute(
                "SELECT content_snippet, summary FROM knowledge "
                "WHERE title = 'WILLOW_CATEGORY_MAPPING' LIMIT 1"
            )
            row = cur.fetchone()
            cur.close()
            pg.close()
            if row:
                raw = row[0] or row[1]
                if raw and raw.strip().startswith("{"):
                    mapping = json.loads(raw)
                    _TAXONOMY_CACHE = set(mapping.values()) | {"agent_task", "agent_chain"}
                    return _TAXONOMY_CACHE
    except Exception as e:
        logger.warning(f"CLASSIFIER: taxonomy load failed: {e}")
    _TAXONOMY_CACHE = FALLBACK_CATEGORIES
    return _TAXONOMY_CACHE


def get_category_mapping() -> dict:
    """Load old-root → canonical mapping from LOAM."""
    try:
        from pg_bridge import try_connect
        pg = try_connect()
        if pg:
            cur = pg.cursor()
            cur.execute(
                "SELECT content_snippet, summary FROM knowledge "
                "WHERE title = 'WILLOW_CATEGORY_MAPPING' LIMIT 1"
            )
            row = cur.fetchone()
            cur.close()
            pg.close()
            if row:
                raw = row[0] or row[1]
                if raw and raw.strip().startswith("{"):
                    return json.loads(raw)
    except Exception as e:
        logger.warning(f"CLASSIFIER: category mapping load failed: {e}")
    return {}


# ── Agent / chain detection (hard rules — no LLM) ─────────────────────────────

AGENT_NAMES = {
    "willow", "kart", "ada", "riggs", "steve", "shiva", "ganesha",
    "oakenscroll", "hanz", "nova", "alexis", "ofshield", "gerald",
    "mitra", "consus", "jane", "jeles", "binder", "pigeon", "heimdallr",
}


def _detect_chain(upper_text: str) -> list[str] | None:
    """Detect multi-agent routing chains."""
    route_match = re.search(
        r"(?:ROUTE|CHAIN)\s*:\s*(.+?)(?:\n|$)", upper_text, re.IGNORECASE
    )
    if route_match:
        agents = re.split(r"\s*(?:→|->|>|»)\s*", route_match.group(1))
        chain = [a.strip().lower() for a in agents if a.strip().lower() in AGENT_NAMES]
        if len(chain) >= 2:
            return chain

    conf_match = re.search(
        r"(?:CONF|CONFERENCE|FACULTY)\s*:\s*(.+?)(?:\n|$)", upper_text, re.IGNORECASE
    )
    if conf_match:
        agents = re.split(r"\s*[,;]\s*", conf_match.group(1))
        chain = [a.strip().lower() for a in agents if a.strip().lower() in AGENT_NAMES]
        if len(chain) >= 2:
            return chain

    return None


def _detect_agent_target(filename: str, snippet: str) -> str | list[str] | None:
    """Check if a file is addressed to agent(s)."""
    text = filename.upper()
    head = snippet[:1000].upper()
    combined = text + " " + head

    chain = _detect_chain(combined)
    if chain:
        return chain

    for agent in AGENT_NAMES:
        if f"FOR {agent.upper()}" in text or f"TO {agent.upper()}" in text:
            return agent.lower()
    for agent in AGENT_NAMES:
        if f"HANDOFF FOR {agent.upper()}" in head or f"TASK FOR {agent.upper()}" in head:
            return agent.lower()
    return None


# ── Main classification function ───────────────────────────────────────────────

def classify(filename: str, snippet: str) -> dict:
    """
    Classify a file by filename and content snippet.

    Returns: {"category": str, "subcategory": str, "summary": str}

    Order:
    1. Agent-addressed files (hard rule)
    2. Session handoffs (hard rule)
    3. Filename keyword fallback
    4. Default: reference|general
    """
    name_upper = filename.upper()

    # 1. Agent routing
    target = _detect_agent_target(filename, snippet)
    if isinstance(target, list):
        chain_str = " → ".join(target)
        return {"category": "agent_chain", "subcategory": chain_str,
                "summary": f"Agent chain ({chain_str}): {filename}"}
    if target:
        return {"category": "agent_task", "subcategory": target,
                "summary": f"Task/handoff addressed to {target}: {filename}"}

    # 2. Session handoffs
    if "HANDOFF" in name_upper:
        return {"category": "handoff", "subcategory": "session",
                "summary": f"Session handoff: {filename}"}

    # 3. Filename keyword fallback
    return _fallback_classify(filename)


def _fallback_classify(filename: str) -> dict:
    """Filename keyword fallback."""
    name = filename.lower()
    rules = [
        # Legal / TOS
        (["terms_of_service", "terms-of-service", "tos_", "_tos", "privacy_policy",
          "privacy-policy", "eula", "user_agreement", "terms_and_conditions",
          "terms-and-conditions", "service_agreement", "data_processing"],
         "legal_agreement", "contracts", "Legal agreement / TOS"),
        (["legal", "court", "bankruptcy", "motion", "schedule", "creditor",
          "earnings_statement", "form_b", "debtor", "physical therapy",
          "work status report", "loa_extension", "approved leave"],
         "legal", "general", "Legal document"),
        # Journal (date-named markdown)
        ([], "journal", "daily", "Journal entry"),  # handled by DATE_RE below
        # Narrative / creative
        (["regarding jane", "chapter", "dispatch", "gerald", "soundtrack",
          "author's note", "books of mann", "world bible", "professor",
          "letter under blue sky", "bring a towel"],
         "narrative", "creative", "Narrative document"),
        # Handoffs / sessions
        (["session_handoff", "handoff_", "master_handoff"],
         "handoff", "session", "Session handoff"),
        # Code / system
        (["arch_", "schema", "endpoint", "daemon", "readme", "changelog",
          "deployment_guide", "architecture", "willow_safe", "safe os"],
         "code", "system", "System/architecture document"),
        # UTETY / lore
        (["oakenscroll", "utety", "hanz", "nova", "gerald", "working_paper",
          "llmphysics", "vibes_paper", "squeakdog"],
         "utety", "lore", "UTETY document"),
        # Knowledge extractions
        (["knowledge_extraction", "campbell_sean_knowledge", "aionic_record"],
         "reference", "knowledge", "Knowledge document"),
        # Conversation exports
        ([".jsonl", "claude", "chatgpt", "export", "sessions"],
         "conversation", "exports", "Conversation export"),
        # Media
        ([".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mp3", ".wav"],
         "media", "general", "Media file"),
        # Personal / social
        (["feeld", "facebook", "messages", "tinder", "hinge"],
         "personal", "social", "Personal/social document"),
    ]

    import re as _re
    DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
    if DATE_RE.match(filename):
        return {"category": "journal", "subcategory": "daily",
                "summary": f"Journal entry: {filename}"}

    for keywords, cat, sub, label in rules:
        if keywords and any(k in name for k in keywords):
            return {"category": cat, "subcategory": sub,
                    "summary": f"{label}: {filename}"}

    return {"category": "reference", "subcategory": "general",
            "summary": f"Document: {filename}"}


# ── Re-classification (bulk migration) ────────────────────────────────────────

def reclassify_category(old_category: str) -> str:
    """Map an old freestyle category to its canonical root."""
    mapping = get_category_mapping()
    root = old_category.split("|")[0] if old_category else "reference"
    return mapping.get(root, old_category)
