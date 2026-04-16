"""
sap/core/memory_gate.py — SAP memory quality gate
b17: MG001
ΔΣ=42

Wraps memory_scorer for use inside the SAP MCP server.
Called by the willow_memory_check MCP tool.
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools.memory_scorer import score_record


def check_candidate(title: str, summary: str, domain: str,
                    store, pg, collection: str = "hanuman/atoms") -> dict:
    """
    Score a candidate write. Used by willow_memory_check MCP tool.

    Args:
        title:      Proposed title
        summary:    Proposed summary
        domain:     Proposed domain (unused in scoring, reserved for future)
        store:      WillowStore instance
        pg:         PgBridge instance
        collection: SOIL collection to check for near-duplicates

    Returns:
        {
          "flags":             list[str],
          "recommendation":    str,
          "redundant_matches": list[str],
          "contradictions":    list[str],
          "dark_result_count": int,
        }
    """
    try:
        records = store.all(collection)
        all_titles = [r.get("title", "") for r in records if r.get("title")]
    except Exception:
        all_titles = []

    candidate = {"title": title, "summary": summary, "_created": None}
    result = score_record(candidate, all_titles, pg)

    flags = result["flags"]
    if not flags:
        recommendation = "clean — proceed with write"
    elif "REDUNDANT" in flags:
        recommendation = "near-duplicate exists — consider updating existing record"
    elif "CONTRADICTION" in flags:
        recommendation = "contradictory language detected — review before writing"
    else:
        recommendation = "review flags before writing"

    return {
        "flags":             flags,
        "recommendation":    recommendation,
        "redundant_matches": result["redundant_matches"],
        "contradictions":    result["contradictions"],
        "dark_result_count": result["dark_result_count"],
    }
