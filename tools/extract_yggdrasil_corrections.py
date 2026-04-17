#!/usr/bin/env python3
"""
b17: YGX41
extract_yggdrasil_corrections.py — Mine handoff corpus for Sean→AI corrections.

Scans handoffs.db raw_content for instances where Sean corrected, rejected,
or redirected AI behavior. Outputs structured JSONL for Yggdrasil training.

Usage:
    python3 tools/extract_yggdrasil_corrections.py
    python3 tools/extract_yggdrasil_corrections.py --output corrections.jsonl
    python3 tools/extract_yggdrasil_corrections.py --preview 20

Output format (one JSON object per line):
    {
        "source_file": "SESSION_HANDOFF_20260303_night.md",
        "date": "2026-03-03",
        "correction_signal": "Sean's 'FFS' and 'you are not getting it done'",
        "ai_behavior_bad": "Submitted three consecutive partial fixes",
        "ai_behavior_good": "Full codebase audit before proposing more patches",
        "context": "DB lock debugging — incremental patches missing systemic issues",
        "category": "thoroughness",
        "raw_excerpt": "..."
    }
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH = Path(os.environ.get(
    "WILLOW_HANDOFF_DB",
    Path.home() / "Ashokoa/agents/heimdallr/index/haumana_handoffs/handoffs.db"
))

# Patterns that signal Sean correcting AI behavior
# Each is (label, regex) — matched against raw_content
# NOTE: Use \bSean\b to avoid matching path components like 'sean-campbell/'
CORRECTION_PATTERNS = [
    # Direct quotes / frustration markers
    ("frustration", r'\bSean\b.{0,60}(?:FFS|"you are not|"you\'re not|"stop |"don\'t|"no,|"wrong|"that\'s not right|"that is not right)'),
    ("rejection",   r'\bSean\b\s+(?:rejected|pushed back|corrected|redirected|said\s+no|overruled|blocked)\b'),
    ("direct_call", r'\bSean\b called it directly[:\s]+"([^"]{10,200})"'),
    # Decision log entries triggered by Sean
    ("decision_log", r'When \bSean\b (?:rejected|pushed back|said|told|corrected|refused)[^\n]{0,300}'),
    # Pattern: Sean's "X" were the signal
    ("signal",      r"\bSean\b's ['\"]([^'\"]{5,100})['\"](?:[^.]{0,60})?(?:were?|was) the signal"),
    # Imperative corrections in quotes
    ("imperative",  r'\bSean\b.{0,30}["\'](?:don\'t|stop|no more|never|always|you must|you should not)[^"\']{0,200}["\']'),
    # Rule violations
    ("rule_viol",   r'(?:rule violation|violated rule|broke rule|ignored rule|bypassed rule)[^\n]{0,200}'),
    # Session-level behavior critique
    ("critique",    r'\bSean\b\s+(?:wasn\'t happy|was frustrated|was annoyed|complained|objected)\b[^\n]{0,200}'),
    # Trust score events — "ended the session at 0% trust"
    ("trust_event", r'(?:ended the session at|trust(?:\s+dropped| fell| reset| score)[^\n]{0,50})[0-9]+%[^\n]{0,200}'),
    # "The lesson is" / post-mortem statements
    ("lesson",      r'[Tt]he (?:lesson|principle|rule) (?:is|was|here)[:\s]+[^\n]{20,300}'),
    # "Should have" statements describing missed correct behavior
    ("should_have", r'(?:should have|shouldn\'t have|ought to have)[^\n]{20,200}'),
    # "Instead of X, AI did Y" — classic narrative correction format
    ("instead_of",  r'[Ii]nstead of [^\n,]{10,100}(?:,|—)[^\n]{10,200}'),
]

# Category heuristics based on content keywords
CATEGORIES = [
    ("tool_use",        ["glob", "grep", "bash", "sqlite3", "tool", "mcp", "search"]),
    ("thoroughness",    ["audit", "partial fix", "incremental", "missing", "systemic", "root cause"]),
    ("scope_creep",     ["scope", "feature", "abstraction", "refactor", "over-engineer", "unnecessary"]),
    ("communication",   ["explain", "summarize", "verbose", "terse", "tone", "summary"]),
    ("architecture",    ["architecture", "design", "pattern", "structure", "schema"]),
    ("process",         ["propose before", "ratify", "gate", "approve", "confirm"]),
    ("identity",        ["persona", "identity", "agent", "name", "rule"]),
]


def infer_category(text: str) -> str:
    text_lower = text.lower()
    for cat, keywords in CATEGORIES:
        if any(k in text_lower for k in keywords):
            return cat
    return "general"


def extract_context_window(content: str, match_start: int, match_end: int, window: int = 400) -> str:
    """Extract text around a match, snapping to paragraph boundaries."""
    start = max(0, match_start - window)
    end = min(len(content), match_end + window)

    # Snap to paragraph start/end
    para_start = content.rfind("\n\n", 0, match_start)
    para_end = content.find("\n\n", match_end)

    if para_start != -1 and para_start > start:
        start = para_start
    if para_end != -1 and para_end < end:
        end = para_end

    return content[start:end].strip()


def extract_decisions_log_entries(content: str) -> list[dict]:
    """Parse DECISIONS_LOG sections for Sean-triggered decisions."""
    results = []
    if "DECISIONS_LOG" not in content and "## Decisions" not in content:
        return results

    # Find decision blocks — ### Header followed by bullet points
    decision_pattern = re.compile(
        r'###\s+(.+?)\n((?:[-*]\s+\*\*[^*]+\*\*[^\n]*\n?)+)',
        re.MULTILINE
    )
    for m in decision_pattern.finditer(content):
        decision_text = m.group(0)
        if not re.search(r'[Ss]ean', decision_text):
            continue

        title = m.group(1).strip()
        block = m.group(2)

        decided = re.search(r'\*\*Decided:\*\*\s*(.+?)(?=\n|$)', block)
        rationale = re.search(r'\*\*Rationale:\*\*\s*(.+?)(?=\n|$)', block)
        impact = re.search(r'\*\*Impact:\*\*\s*(.+?)(?=\n|$)', block)

        if not decided:
            continue

        correction_signal = ""
        ai_behavior_bad = ""
        if rationale:
            rat_text = rationale.group(1)
            sean_quote = re.search(r"Sean's ['\"]([^'\"]+)['\"]", rat_text)
            if sean_quote:
                correction_signal = sean_quote.group(0)
            # Look for what AI was doing wrong
            if "was" in rat_text or "were" in rat_text:
                ai_behavior_bad = rat_text[:200]

        results.append({
            "pattern": "decision_log",
            "title": title,
            "correction_signal": correction_signal,
            "ai_behavior_bad": ai_behavior_bad,
            "ai_behavior_good": decided.group(1).strip()[:300],
            "rationale": rationale.group(1).strip()[:300] if rationale else "",
            "impact": impact.group(1).strip()[:200] if impact else "",
            "raw_excerpt": decision_text[:600],
        })

    return results


def extract_gaps_corrections(content: str) -> list[dict]:
    """Extract Sean's direct critiques from Gaps / Prompt sections."""
    results = []
    for section in ("## Gaps", "## Prompt", "## Open Threads", "**Open Threads**"):
        if section not in content:
            continue
        start = content.find(section) + len(section)
        end_markers = ["##", "---", "ΔΣ"]
        end = len(content)
        for marker in end_markers:
            pos = content.find(marker, start + 10)
            if pos != -1 and pos < end:
                end = pos

        block = content[start:end].strip()

        # Find Sean quotes
        for m in re.finditer(r'Sean[^"\']*["\']([^"\']{10,300})["\']', block):
            results.append({
                "pattern": "gaps_critique",
                "correction_signal": f'Sean: "{m.group(1)}"',
                "ai_behavior_bad": "",
                "ai_behavior_good": "",
                "rationale": "",
                "raw_excerpt": block[:400],
            })

        # Find "Sean said/told/directed" without quotes
        for m in re.finditer(r'Sean\s+(?:said|told|directed|instructed|pushed back|rejected)[^.\n]{10,200}', block):
            results.append({
                "pattern": "gaps_direction",
                "correction_signal": m.group(0).strip(),
                "ai_behavior_bad": "",
                "ai_behavior_good": "",
                "rationale": "",
                "raw_excerpt": block[:400],
            })

    return results


def scan_raw_patterns(content: str) -> list[dict]:
    """Run regex correction patterns against full content."""
    results = []
    for label, pattern in CORRECTION_PATTERNS:
        for m in re.finditer(pattern, content, re.IGNORECASE | re.DOTALL):
            excerpt = extract_context_window(content, m.start(), m.end(), window=300)
            results.append({
                "pattern": label,
                "correction_signal": m.group(0)[:200].strip(),
                "ai_behavior_bad": "",
                "ai_behavior_good": "",
                "rationale": "",
                "raw_excerpt": excerpt,
            })
    return results


def process_handoff(row: dict) -> list[dict]:
    """Extract all corrections from one handoff record."""
    content = row.get("raw_content") or ""
    if not content or len(content) < 100:
        return []

    filename = row.get("filename", "")
    date = row.get("handoff_date") or ""
    file_type = row.get("file_type", "")

    corrections = []
    corrections.extend(extract_decisions_log_entries(content))
    corrections.extend(extract_gaps_corrections(content))
    corrections.extend(scan_raw_patterns(content))

    # Deduplicate by correction_signal text
    seen = set()
    unique = []
    for c in corrections:
        key = c["correction_signal"][:80]
        if key and key not in seen:
            seen.add(key)
            c.update({
                "source_file": filename,
                "date": date,
                "file_type": file_type,
                "category": infer_category(
                    c["correction_signal"] + " " + c.get("rationale", "") + " " + c.get("raw_excerpt", "")
                ),
            })
            unique.append(c)

    return unique


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract Sean→AI corrections from handoff corpus")
    parser.add_argument("--output", default="", help="Output JSONL file (default: stdout)")
    parser.add_argument("--preview", type=int, default=0, help="Print first N corrections and exit")
    parser.add_argument("--min-length", type=int, default=200, help="Min raw_content length to process")
    parser.add_argument("--types", default="session,pigeon,daily_log", help="Handoff types to scan")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: DB not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    types = [t.strip() for t in args.types.split(",")]
    placeholders = ",".join("?" * len(types))

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"""
        SELECT h.file_type, h.handoff_date, h.raw_content,
               f.filename
        FROM handoffs h
        JOIN files f ON h.file_id = f.id
        WHERE h.file_type IN ({placeholders})
          AND h.raw_content IS NOT NULL
          AND LENGTH(h.raw_content) >= ?
        ORDER BY h.handoff_date
    """, types + [args.min_length])

    rows = cur.fetchall()
    conn.close()

    print(f"Scanning {len(rows)} handoffs...", file=sys.stderr)

    all_corrections = []
    for row in rows:
        corrections = process_handoff(dict(row))
        all_corrections.extend(corrections)

    print(f"Found {len(all_corrections)} correction instances", file=sys.stderr)

    # Category breakdown
    from collections import Counter
    cats = Counter(c["category"] for c in all_corrections)
    print("Categories:", file=sys.stderr)
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}", file=sys.stderr)

    if args.preview:
        for c in all_corrections[:args.preview]:
            print(json.dumps(c, indent=2))
        return

    if args.output:
        out_path = Path(args.output)
        with out_path.open("w") as f:
            for c in all_corrections:
                f.write(json.dumps(c) + "\n")
        print(f"Written {len(all_corrections)} records to {out_path}", file=sys.stderr)
    else:
        for c in all_corrections:
            print(json.dumps(c))


if __name__ == "__main__":
    main()
