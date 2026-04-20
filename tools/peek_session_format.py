#!/usr/bin/env python3
"""Peek at Claude Code session JSONL format — find tool_result events with errors."""
import json
from pathlib import Path

SESSION = Path("/home/sean-campbell/.claude/projects/-home-sean-campbell-github-willow-1-7/9fcc703b-a445-4057-b582-19a3b4949be8.jsonl")

types_seen = set()
bash_errors = []
edit_events = []

with SESSION.open() as f:
    for line in f:
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get("type", ev.get("role", "?"))
        types_seen.add(t)

        msg = ev.get("message", {})
        content = msg.get("content", [])
        if not isinstance(content, list):
            content = []

        for block in content:
            if not isinstance(block, dict):
                continue
            # tool_result blocks with errors
            if block.get("type") == "tool_result":
                for inner in (block.get("content") or []):
                    if isinstance(inner, dict) and inner.get("type") == "text":
                        text = inner.get("text", "")
                        if any(k in text for k in ("Error", "error", "failed", "stderr")):
                            bash_errors.append({
                                "tool_use_id": block.get("tool_use_id"),
                                "text": text[:300],
                            })
            # tool_use blocks (Bash, Edit, Write)
            if block.get("type") == "tool_use":
                name = block.get("name", "")
                if name in ("Bash", "Edit", "Write"):
                    inp = block.get("input", {})
                    edit_events.append({"tool": name, "input_keys": list(inp.keys()), "snippet": str(inp)[:150]})

print("Event types seen:", types_seen)
print(f"\nBash/tool errors found: {len(bash_errors)}")
for e in bash_errors[:3]:
    print(f"  {e['text'][:200]}")

print(f"\nEdit/Bash/Write events: {len(edit_events)}")
for e in edit_events[:3]:
    print(f"  {e['tool']}: {e['snippet']}")
