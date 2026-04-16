# sap/clients/ — Application-Side SAP Clients
<!-- b17: CL13N · ΔΣ=42 -->

These modules are the application-facing side of SAP. They combine gate authorization, context assembly, and inference into complete request patterns. Import them from any application code that needs to talk to a SAP-authorized persona.

```
sap/clients/
├── professor_client.py   # UTETY faculty interface
├── kart_client.py        # Kart task authorization wrapper
└── generic_client.py     # Any SAP-authorized app
```

---

## professor_client.py — UTETY Professor Client

The wire between application code and the UTETY faculty. Replaces the old Pigeon HTTP bus.

**Before (1.4/1.5 path):**
```
chat_engine.py → Pigeon HTTP drop → localhost:8420 → Willow → LLM
```

**Now (SAP path):**
```
professor_client.py → gate.authorized("utety-chat") → context.assemble() → Ollama
```

No HTTP server. No exposed port. The SAFE manifest check happens on every `ProfessorClient` instantiation.

### Faculty Roster

17 professors, each with:
- A `PROFESSOR_DOMAINS` list — which KB categories their context is scoped to
- A `PROFESSOR_SAFE_IDS` entry — which SAFE folder caches their context
- A `PROFESSOR_MODELS` entry — which Ollama model they use (default: `qwen2.5:3b`)
- A persona prompt loaded from `safe-app-utety-chat/personas.py`
- Optional professor-specific SQLite seed DB at `data/professors/<name>/<name>.db`

| Professor | KB Domains |
|---|---|
| Oakenscroll | governance, architecture, analysis, core, code |
| Riggs | architecture, code, system-state, analysis |
| Hanz | code, training, document, conversation |
| Nova | narrative, analysis, user_cognition |
| Ada | architecture, system-state, governance, core |
| Jeles | genealogy, reference, documents, general |
| Alexis | personal, general |
| Ofshield | personal, user_cognition, narrative |
| Shiva | architecture, system-state, code, core, governance |
| Gerald | governance, general |
| Pigeon | architecture, system-state |
| Binder | reference, genealogy, general |
| Mitra | general |
| Consus | governance, architecture |
| Jane | general, narrative |
| Steve | general |
| Willow | all (no filter, no skip_cache) |
| Kart | architecture, system-state, code |

### Usage

```python
from sap.clients.professor_client import ProfessorClient, conf_call

# Single professor
client = ProfessorClient("Oakenscroll")
response = client.ask("What does ΔΣ=42 mean?")

# Conf call — multiple professors, one topic
responses = conf_call(
    professors=["Oakenscroll", "Riggs", "Consus"],
    topic="Is ΔE=0 achievable under portless constraints?",
    facilitator="Gerald",   # facilitator speaks last with all other responses as context
)
# responses: {"Oakenscroll": "…", "Riggs": "…", "Consus": "…", "Gerald": "…synthesis…"}
```

### Inference Order

For each professor call, inference is attempted in order:
1. **Ollama Python client** (`ollama` library) — fastest if installed
2. **Ollama HTTP** (`requests.post` to `http://localhost:11434/api/chat`) — fallback if library fails
3. **Free fleet** — Groq → Cerebras → SambaNova, using keys from `credentials.json`

If all three fail, returns `None`.

### Professor Seed DBs

Optionally, each professor can have a local SQLite database at:
```
safe-app-utety-chat/data/professors/<name_lower>/<name_lower>.db
```

Two tables are read:
- `papers (title, domain, status)` — up to 5 most recent papers listed in the system prompt
- `equations (label, plain) WHERE consus_verified=1` — up to 5 verified equations

This injects professor-specific domain knowledge directly into their system prompt before the SAP context block.

---

## kart_client.py — Kart Task Authorization

Closes the gap between Kart's task execution and SAP authorization. Before this client, Kart could dispatch shell commands and write to Postgres without passing through the consent layer.

### Usage

```python
from sap.clients.kart_client import authorize_task, build_task_context

# Gate check before executing — returns True/False
if not authorize_task(task):
    raise PermissionError(f"Task {task['task_id']} not authorized")

# Assemble context for task execution
ctx_str = build_task_context(task, max_chars=2000)
```

### App ID Resolution

`authorize_task` looks for the app ID in this order:
1. `task["metadata"]["sap_app_id"]` — explicit per-task override
2. `task["agent"].title()` — agent name mapped to SAFE folder (e.g., `"kart"` → `"Kart"`)
3. `KART_DEFAULT_APP = "Kart"` — fallback

Denied tasks are logged to `sap/log/gaps.jsonl` automatically by `gate.py`. The Kart worker (`kart_worker.py`) calls `authorize_task` before executing any task. A non-fatal import error skips the check (rather than crashing the worker).

---

## generic_client.py — Generic SAP App Client

One client for any SAP application that has a SAFE folder and a `personas.py`. Does not assume anything about the application structure beyond those two requirements.

### Usage

```python
from sap.clients.generic_client import AppClient

client = AppClient(
    app_id="LawGazelle",
    personas_path="/path/to/safe-app-law-gazelle/personas.py",
    persona_name="Gazelle",
    model="llama3.2:1b",              # optional, defaults to llama3.2:1b
    category_filter=["legal", "reference"],   # optional KB filter
)
response = client.ask("I have a landlord who won't return my deposit.")
```

### What It Does

1. Calls `gate.authorized(app_id)` — raises `PermissionError` if denied
2. Loads persona from `personas.py` via `importlib` — supports both `get_persona(name)` and `PERSONAS[name]`
3. On `ask(question)`: assembles KB context → builds system prompt → calls Ollama → falls back to fleet

The fleet fallback in `generic_client.py` tries Groq then Cerebras (not SambaNova, for simplicity). Use `professor_client.py` for the full Groq → Cerebras → SambaNova chain.

---

## Shared Inference Pattern

All three clients follow the same inference path:

```
1. Ollama Python client   (ollama.Client.chat)
2. Ollama HTTP            (requests.post → /api/chat)
3. Free fleet             (credentials.json keys, round-robin with failover)
```

Thread count for Ollama is controlled by `SAP_OLLAMA_THREADS` (default: 4). On a machine with other workloads, lower this to avoid starving other processes.

All Ollama calls use a 300-second timeout. CPU inference on small models (~3B parameters) runs at roughly 5 tokens/second; a typical response of 200 tokens takes ~40 seconds.
