# Claude Code Hooks — Example Configuration
<!-- b17: HKEX0 · ΔΣ=42 -->

These hooks live in your **global** `~/.claude/settings.json`, not in the project repo.
Copy the blocks you want into your global config under the `"hooks"` key.

---

## SessionStart — JSONL indexer

Registers session turn files at boot so `willow_handoff_search` can find them.

```json
"SessionStart": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "python3 /path/to/your/agent/bin/session-index-builder.py",
        "timeout": 15,
        "statusMessage": "Building session index..."
      }
    ]
  }
]
```

---

## PreToolUse — MCP-first guard

Blocks `find`, `grep`, `ls`, `psql`, `cat` direct shell calls in favor of MCP equivalents.

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "python3 /path/to/your/agent/bin/pretool-mcp-guard.py",
      "timeout": 5
    }
  ]
}
```

Guard script checks the command string and exits non-zero with a message if it detects a
blocked pattern. Claude Code surfaces the message to the model as a blocking error.

---

## PreToolUse — KB write guard

Enforces the Angular Deviation Rubric on every `store_put`, `store_update`, or `willow_knowledge_ingest` call.

```json
{
  "matcher": "mcp__willow__store_put|mcp__willow__store_update|mcp__willow__willow_knowledge_ingest|mcp__willow__willow_ratify",
  "hooks": [
    {
      "type": "command",
      "command": "python3 /path/to/your/agent/bin/write-guard.py",
      "timeout": 5
    }
  ]
}
```

---

## UserPromptSubmit — Turns logger

Appends each turn to the agent's JSONL store for handoff indexing and governance.

```json
"UserPromptSubmit": [
  {
    "hooks": [
      {
        "type": "command",
        "command": "python3 /path/to/your/agent/bin/turns-logger.py",
        "timeout": 5
      }
    ]
  }
]
```

---

## Skills

Skills (slash commands) live in your Claude Code plugin directory (`~/.claude/plugins/`).

| Skill | Command | Purpose |
|---|---|---|
| handoff | `/handoff` | Generate session handoff document, index in Postgres, copy to Desktop |
| restart-server | `/restart-server` | Hot-reload willow modules without restarting Claude Code |

See the [Claude Code plugin documentation](https://docs.anthropic.com/en/docs/claude-code/plugins)
for how to install skills from a plugin directory.
