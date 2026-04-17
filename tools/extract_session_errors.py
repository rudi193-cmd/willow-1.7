#!/usr/bin/env python3
"""
b17: ESE39
extract_session_errors.py — Mine Claude Code session JSOLs for AI errors and repeated fixes.

Scans ~/.claude/projects/* session files for:
  1. Bash errors — non-zero returncode or non-empty stderr
  2. Failed tool calls — MCP errors, unauthorized, task failures
  3. Repeated file edits — same file edited 3+ times in one session (thrashing)

Emits JSONL correction pairs for Yggdrasil DPO training.

Output: yggdrasil/session_errors_v1.jsonl

Usage:
    python3 tools/extract_session_errors.py
    python3 tools/extract_session_errors.py --preview 10
    python3 tools/extract_session_errors.py --projects willow-1-7,hanuman
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude/projects"
OUT_PATH = Path(__file__).parent.parent / "yggdrasil/session_errors_v1.jsonl"

# Which projects to scan — map slug → label
PROJECT_ALLOWLIST = {
    "-home-sean-campbell-github-willow-1-7":              "willow",
    "-home-sean-campbell-github-safe-app-llmphysics-bot": "llmphysics",
    "-home-sean-campbell-github-safe-apps-safe-app-kart": "kart",
    "-home-sean-campbell-willow-1-5":                     "willow15",
    "-home-sean-campbell--claude":                        "claude_root",
    "-home-sean-campbell-agents-hanuman":                 "hanuman",
}

# Repeated-edit threshold
REPEAT_THRESHOLD = 3


def iter_events(jsonl_path: Path):
    """Yield parsed event dicts from a session JSONL."""
    try:
        with jsonl_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    pass
    except Exception:
        pass


def extract_content_blocks(event: dict) -> list[dict]:
    """Extract all content blocks from an event."""
    msg = event.get("message", event)
    content = msg.get("content", [])
    if isinstance(content, str):
        return []
    return [b for b in content if isinstance(b, dict)]


def get_tool_use_blocks(event: dict) -> list[dict]:
    return [b for b in extract_content_blocks(event) if b.get("type") == "tool_use"]


def get_tool_result_blocks(event: dict) -> list[dict]:
    return [b for b in extract_content_blocks(event) if b.get("type") == "tool_result"]


def result_text(block: dict) -> str:
    """Extract text from a tool_result block."""
    inner = block.get("content") or []
    if isinstance(inner, str):
        return inner
    parts = []
    for item in inner:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts)


_BASH_ERROR_RE = re.compile(
    r'\b(command not found|No such file or directory|Permission denied|'
    r'ModuleNotFoundError|ImportError|SyntaxError|NameError|AttributeError|'
    r'Traceback \(most recent call\)|subprocess\.CalledProcessError|'
    r'exit status [1-9]|returned non-zero exit|FAILED|ENOENT)\b',
    re.IGNORECASE,
)


def is_bash_error(result_str: str) -> tuple[bool, str]:
    """Return (is_error, error_text) for a bash tool result."""
    try:
        d = json.loads(result_str)
        if isinstance(d, dict):
            rc = d.get("returncode")
            stderr = (d.get("stderr") or "").strip()
            stdout = (d.get("stdout") or "").strip()
            if rc not in (None, 0):
                return True, f"exit {rc}: stderr={stderr[:300]} stdout={stdout[:100]}"
            if stderr and len(stderr) > 10:
                if not re.match(r'^(warning:|hint:|note:|remote:|Cloning|Fetching|From |Branch |HEAD)', stderr, re.I):
                    return True, f"stderr: {stderr[:300]}"
    except Exception:
        pass
    # Plain-text fallback: only specific, unambiguous error patterns
    m = _BASH_ERROR_RE.search(result_str)
    if m:
        start = max(0, m.start() - 40)
        return True, result_str[start:start + 300]
    return False, ""


def is_tool_failure(result_str: str) -> tuple[bool, str]:
    """Return (is_failure, reason) for MCP/non-bash tool results."""
    try:
        d = json.loads(result_str)
        if isinstance(d, dict):
            if d.get("error"):
                return True, f"error: {str(d['error'])[:200]}"
            if d.get("status") == "failed":
                res = d.get("result", {})
                return True, f"task failed: {str(res)[:200]}"
            if "unauthorized" in str(d).lower():
                return True, f"unauthorized: {str(d)[:200]}"
    except Exception:
        pass
    return False, ""


def process_session(jsonl_path: Path, project_label: str) -> list[dict]:
    """Extract error events from one session file."""
    events = list(iter_events(jsonl_path))
    if len(events) < 3:
        return []

    session_id = jsonl_path.stem
    results = []

    # Build a map: tool_use_id → (tool_name, input, assistant_text_before)
    tool_use_map: dict[str, dict] = {}
    last_assistant_text = ""
    edit_counts: dict[str, list[int]] = defaultdict(list)  # file_path → [event indices]

    for i, ev in enumerate(events):
        role = ev.get("type") or ev.get("role") or ""
        msg = ev.get("message", ev)
        content_role = msg.get("role", role)

        if content_role == "assistant":
            # Collect tool_use blocks
            text_parts = []
            for block in extract_content_blocks(ev):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_use_map[block["id"]] = {
                        "name": block.get("name", ""),
                        "input": block.get("input", {}),
                        "context": last_assistant_text[-500:],
                    }
                    # Track file edits
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    if name in ("Edit", "Write") and "file_path" in inp:
                        edit_counts[inp["file_path"]].append(i)
            last_assistant_text = " ".join(text_parts)

        elif content_role == "user":
            # Collect tool_result blocks
            for block in get_tool_result_blocks(ev):
                tu_id = block.get("tool_use_id", "")
                rtext = result_text(block)
                if not rtext:
                    continue

                tu = tool_use_map.get(tu_id, {})
                tool_name = tu.get("name", "")
                tool_input = tu.get("input", {})
                context = tu.get("context", "")

                is_err, err_detail = False, ""
                category = "general"

                if tool_name == "Bash":
                    is_err, err_detail = is_bash_error(rtext)
                    category = "tool_use"
                else:
                    is_err, err_detail = is_tool_failure(rtext)
                    if is_err:
                        category = "tool_use"

                if is_err:
                    cmd = tool_input.get("command", tool_input.get("description", str(tool_input)[:100]))
                    results.append({
                        "source": "session_error",
                        "source_file": f"{project_label}/{session_id}",
                        "date": "",
                        "label": "negative",
                        "category": category,
                        "error_type": "bash_error" if tool_name == "Bash" else "tool_failure",
                        "tool": tool_name,
                        "correction_signal": f"{tool_name} failed: {err_detail[:200]}",
                        "ai_behavior_bad": f"Ran: {cmd[:200]}\nError: {err_detail[:300]}",
                        "ai_behavior_good": "",
                        "context": context[:300],
                        "raw_excerpt": rtext[:400],
                    })

    # Detect repeated file edits (thrashing)
    for file_path, indices in edit_counts.items():
        if len(indices) >= REPEAT_THRESHOLD:
            results.append({
                "source": "session_repeat_edit",
                "source_file": f"{project_label}/{session_id}",
                "date": "",
                "label": "negative",
                "category": "thoroughness",
                "error_type": "repeat_edit",
                "tool": "Edit/Write",
                "correction_signal": f"File edited {len(indices)}x in one session: {Path(file_path).name}",
                "ai_behavior_bad": f"Edited {file_path} {len(indices)} times — indicates thrashing or incomplete initial analysis. Edit indices: {indices[:10]}",
                "ai_behavior_good": "Audit the full file before making changes. One well-considered edit beats three incremental patches.",
                "context": "",
                "raw_excerpt": file_path,
            })

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", type=int, default=0)
    parser.add_argument("--projects", default="", help="Comma-separated project slugs to scan (partial match)")
    args = parser.parse_args()

    filter_slugs = [s.strip() for s in args.projects.split(",") if s.strip()] if args.projects else []

    all_corrections = []
    file_count = 0

    for proj_slug, proj_label in PROJECT_ALLOWLIST.items():
        if filter_slugs and not any(f in proj_slug for f in filter_slugs):
            continue

        proj_dir = CLAUDE_PROJECTS / proj_slug
        if not proj_dir.exists():
            continue

        jsonl_files = list(proj_dir.glob("*.jsonl")) + list(proj_dir.glob("*/subagents/*.jsonl"))
        print(f"  {proj_label}: {len(jsonl_files)} session files", file=sys.stderr)

        for jf in jsonl_files:
            corrections = process_session(jf, proj_label)
            all_corrections.extend(corrections)
            file_count += 1

    print(f"\nScanned {file_count} session files", file=sys.stderr)
    print(f"Found {len(all_corrections)} error instances", file=sys.stderr)

    cats = Counter(c["category"] for c in all_corrections)
    etypes = Counter(c.get("error_type", "?") for c in all_corrections)
    print(f"Categories: {dict(cats.most_common())}", file=sys.stderr)
    print(f"Error types: {dict(etypes.most_common())}", file=sys.stderr)

    if args.preview:
        for c in all_corrections[:args.preview]:
            print(json.dumps(c, indent=2))
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for c in all_corrections:
            f.write(json.dumps(c) + "\n")
    print(f"\nWritten {len(all_corrections)} records to {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
