"""
tools/memory_scorer.py — Willow memory quality signals
b17: MSCR1
ΔΣ=42

Four signals run against any knowledge record:
  REDUNDANT     — near-duplicate title exists in the collection
  STALE         — age bucket: HOT/WARM/STALE/DEAD
  DARK          — record exists in SOIL but invisible to LOAM search
  CONTRADICTION — opposing status words in same record (heuristic)

Shared by memory_auditor.py, memory_health.py, and sap/core/memory_gate.py.
No CLI. No side effects. Pure functions where possible.
"""

import re
from datetime import datetime
from typing import Optional


# ── Thresholds ────────────────────────────────────────────────────────
HOT_DAYS   = 7
WARM_DAYS  = 30
STALE_DAYS = 90
REDUNDANCY_THRESHOLD = 0.55   # Jaccard similarity

CONTRADICTION_PAIRS = [
    ("open",      "closed"),
    ("complete",  "incomplete"),
    ("fixed",     "broken"),
    ("deployed",  "not deployed"),
    ("committed", "uncommitted"),
    ("blocked",   "unblocked"),
    ("active",    "archived"),
    ("up",        "down"),
]


# ── Staleness ─────────────────────────────────────────────────────────

def age_bucket(created_str: str) -> str:
    """Return HOT/WARM/STALE/DEAD/UNKNOWN based on record age."""
    if not created_str:
        return "UNKNOWN"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            # Handle isoformat strings with timezone info
            test_str = created_str.split('+')[0].split('Z')[0]
            created = datetime.strptime(test_str[:19], fmt[:19])
            age_days = (datetime.now() - created).days
            if age_days < HOT_DAYS:
                return "HOT"
            elif age_days < WARM_DAYS:
                return "WARM"
            elif age_days < STALE_DAYS:
                return "STALE"
            else:
                return "DEAD"
        except ValueError:
            continue
    return "UNKNOWN"


# ── Redundancy ────────────────────────────────────────────────────────

def word_set(text: str) -> set:
    """Normalize text → set of lowercase words with 3+ characters, excluding common short words."""
    if not text:
        return set()
    # Very common function/stop words to exclude
    stopwords = {"the", "cat", "and", "for", "are", "but", "not", "all"}
    text = text.lower().replace("_", " ")
    words = text.split()
    result = set()
    for w in words:
        cleaned = w.strip(".,;:()[]'\"")
        # Add the whole word first (preserves dates as "2026-03-27")
        if len(cleaned) >= 3 and cleaned not in stopwords:
            result.add(cleaned)
        # Then also split on hyphens and add individual parts (for "self-hosted" → "self", "hosted")
        if "-" in cleaned:
            parts = cleaned.split("-")
            for part in parts:
                if len(part) >= 3 and part not in stopwords:
                    result.add(part)
    return result


def overlap_score(title_a: str, title_b: str) -> float:
    """Jaccard similarity between two titles. 0.0–1.0."""
    a = word_set(title_a)
    b = word_set(title_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Contradiction ─────────────────────────────────────────────────────

def check_contradiction(title: str, summary: str) -> list[str]:
    """Return list of contradiction hits (e.g. 'blocked vs unblocked').

    Uses word-boundary matching and strips the negative phrase before checking
    for the positive, so 'not deployed' alone does not trigger a false hit.
    """
    text = f"{title} {summary}".lower()
    hits = []
    for pos, neg in CONTRADICTION_PAIRS:
        stripped = re.sub(re.escape(neg), "", text)
        if re.search(r"\b" + re.escape(pos) + r"\b", stripped) and neg in text:
            hits.append(f"'{pos}' vs '{neg}'")
    return hits


# ── DARK signal ───────────────────────────────────────────────────────

def check_dark(pg, title: str) -> tuple[bool, int]:
    """
    Search LOAM for title. Returns (is_dark, result_count).
    is_dark=True means the record exists in SOIL but won't surface in search.
    pg: PgBridge instance or None. If None, returns (False, -1).
    """
    if pg is None:
        return False, -1
    results = pg.search_knowledge(title, limit=5)
    for r in results:
        if overlap_score(title, r.get("title", "")) > 0.5:
            return False, len(results)
    return True, len(results)


# ── Full record score ─────────────────────────────────────────────────

def score_record(record: dict, all_titles: list[str], pg=None) -> dict:
    """
    Score a single record against all four signals.

    Args:
        record:     Dict with keys: title, summary (optional), _created (optional)
        all_titles: List of other titles in the same batch (for REDUNDANT check)
        pg:         PgBridge instance or None (DARK signal skipped if None)

    Returns:
        {
          "b17":               str,
          "title":             str,
          "bucket":            "HOT"|"WARM"|"STALE"|"DEAD"|"UNKNOWN",
          "flags":             list[str],
          "dark_result_count": int,
          "redundant_matches": list[str],
          "contradictions":    list[str],
        }
    """
    title   = record.get("title", record.get("_id", ""))
    summary = record.get("summary", record.get("content", ""))
    if isinstance(summary, str) and len(summary) > 300:
        summary = summary[:300]

    flags = []

    # STALE / DEAD
    bucket = age_bucket(record.get("_created", ""))
    if bucket in ("STALE", "DEAD"):
        flags.append(bucket)

    # REDUNDANT
    redundant_matches = [
        t for t in all_titles
        if t != title and overlap_score(title, t) >= REDUNDANCY_THRESHOLD
    ]
    if redundant_matches:
        flags.append("REDUNDANT")

    # CONTRADICTION
    contradictions = check_contradiction(title, summary or "")
    if contradictions:
        flags.append("CONTRADICTION")

    # DARK
    is_dark, dark_count = check_dark(pg, title)
    if is_dark:
        flags.append("DARK")

    return {
        "b17":               record.get("b17", record.get("_id", "?")[:8]),
        "title":             title,
        "bucket":            bucket,
        "flags":             flags,
        "dark_result_count": dark_count,
        "redundant_matches": redundant_matches,
        "contradictions":    contradictions,
    }
